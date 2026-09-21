# -*- coding: utf-8 -*-
"""静的サイトの書き出し。

絞り込みの組み合わせごとに全画面をあらかじめHTMLとして生成する。
出力結果はサーバーを必要とせず、ファイルを置くだけで閲覧できる。

推測困難なディレクトリ名の下に出力することで、URLを知る人だけが
閲覧できる状態にする。
"""
import argparse
import logging
import secrets
import shutil
import sys

from src.config import CARD_WEB_DIR, ROOT, get_config
from src.db import repository as repo
from src.web import app as webapp
from src.web import urls as urlmod

DIST_DIR = ROOT / "dist"
STATIC_DIR = ROOT / "src" / "web" / "static"

PERIODS = ["all", "7d", "30d", "90d"]
MODES = [None, "PvP", "pathOfLegend"]

# 絞り込みの組み合わせではないディレクトリ。古いページの掃除で消さないよう除外する。
# 掃除の対象外にするディレクトリ。cards はカード画像、matches は対戦詳細、
# card はカードの性能値ページ、spells は呪文で倒せるユニットの画面。
# いずれも絞り込みの組み合わせではない。
RESERVED_DIRS = {"cards", "matches", "card", "spells"}


def get_secret(conn, rotate=False):
    """公開URLに使う推測困難な文字列を返す。無ければ生成して保存する。"""
    secret = None if rotate else repo.get_meta(conn, "static_secret")
    if not secret:
        secret = secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:32]
        repo.set_meta(conn, "static_secret", secret)
        conn.commit()
        logging.info("公開URLの文字列を新規発行しました")
    return secret


def enumerate_combos(conn):
    """書き出す絞り込みの組み合わせを列挙する。"""
    from src.analysis import decks as decks_analysis

    combos = []
    for player in repo.list_players(conn):
        tag = player["player_tag"]
        deck_ids = [None] + [g["group_id"]
                             for g in decks_analysis.list_deck_groups(conn, tag)]
        for period in PERIODS:
            for mode in MODES:
                for deck in deck_ids:
                    combos.append((tag, period, mode, deck))
    return combos


def query_for(tag, period, mode, deck, variant):
    """Flaskへ渡すクエリ文字列を組み立てる。"""
    params = [f"player={tag.lstrip('#')}", f"period={period}"]
    if mode:
        params.append(f"modes={mode}")
    if deck is not None:
        params.append(f"deck={deck}")
    if variant:
        params.append(f"unit={variant}")
    return "&".join(params)


def copy_assets(out_dir):
    """CSS・アイコン・カード画像を出力先へコピーする。"""
    for name in ("style.css", "manifest.json", "icon-180.png", "icon-192.png", "icon-512.png"):
        src = STATIC_DIR / name
        if src.exists():
            shutil.copy2(src, out_dir / name)

    cards_dir = out_dir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    expected = set()
    for img in CARD_WEB_DIR.glob("*.webp"):
        expected.add(img.name)
        dest = cards_dir / img.name
        # 既に同じ大きさで存在するなら再コピーしない（毎日の書き出しを速くする）
        if not dest.exists() or dest.stat().st_size != img.stat().st_size:
            shutil.copy2(img, dest)
            copied += 1

    # 形式変更などで不要になったファイルを残さない。
    # 残すと公開サイトの容量とアップロード時間が無駄に増える。
    removed = 0
    for old in cards_dir.iterdir():
        if old.is_file() and old.name not in expected:
            old.unlink()
            removed += 1
    if removed:
        logging.info("不要になった画像を削除しました: %d件", removed)
    return copied


def export_match_details(conn, client, out_dir):
    """対戦の詳細ページを書き出す。

    詳細は絞り込みに依存しないため、組み合わせごとには作らず1試合1ファイルに
    まとめる。ただし対戦が増えるほどファイル数が伸びるので、一覧から辿れる
    範囲（プレイヤーごとの直近ぶん）だけを対象にする。
    """
    from src.analysis import detail as detail_analysis

    match_dir = out_dir / "matches"
    match_dir.mkdir(parents=True, exist_ok=True)

    ids = detail_analysis.listed_match_ids(conn, get_config().publish_history_limit)
    for match_id in ids:
        response = client.get(f"/match/{match_id}")
        if response.status_code != 200:
            raise RuntimeError(f"詳細の書き出しに失敗しました: {match_id} -> {response.status_code}")
        (match_dir / f"{match_id}.html").write_bytes(response.data)

    # 一覧から辿れなくなった対戦のページは残さない
    expected = {f"{i}.html" for i in ids}
    for old in match_dir.iterdir():
        if old.is_file() and old.name not in expected:
            old.unlink()

    logging.info("対戦詳細を書き出しました: %d件", len(ids))
    return len(ids)


def export_card_details(conn, client, out_dir):
    """カードの性能値ページを書き出す。

    性能値は絞り込みに依存しないため、組み合わせごとには作らず1枚1ファイルに
    する。カードは増えても100枚台なので全件を対象にしてよい。
    画像を置く cards/ と混ざらないよう card/ に分ける。
    """
    card_dir = out_dir / "card"
    card_dir.mkdir(parents=True, exist_ok=True)

    ids = [r["card_id"] for r in conn.execute(
        "SELECT card_id FROM cards WHERE is_support = 0 ORDER BY card_id")]
    for card_id in ids:
        response = client.get(f"/card/{card_id}")
        if response.status_code != 200:
            raise RuntimeError(
                f"カード詳細の書き出しに失敗しました: {card_id} -> {response.status_code}")
        (card_dir / f"{card_id}.html").write_bytes(response.data)

    # カードマスタから消えたカードのページは残さない
    expected = {f"{i}.html" for i in ids}
    for old in card_dir.iterdir():
        if old.is_file() and old.name not in expected:
            old.unlink()

    logging.info("カード詳細を書き出しました: %d件", len(ids))
    return len(ids)


def export_spells_page(client, out_dir):
    """呪文で倒せるユニットの画面を書き出す。

    呪文とレベルの切り替えはブラウザ内で計算するため、組み合わせごとに
    ページを作る必要はなく、1ファイルで済む。
    """
    spells_dir = out_dir / "spells"
    spells_dir.mkdir(parents=True, exist_ok=True)
    response = client.get("/spells")
    if response.status_code != 200:
        raise RuntimeError(f"呪文の画面の書き出しに失敗しました: {response.status_code}")
    (spells_dir / "index.html").write_bytes(response.data)
    logging.info("呪文の画面を書き出しました")
    return 1


def write_index(out_dir, default_combo):
    """入口となるページ。既定の組み合わせへ転送する。"""
    target = f"{default_combo}/summary.html"
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url={target}">
<title>クラロワ対戦分析</title>
</head>
<body>
<p>読み込んでいます… <a href="{target}">開かない場合はこちら</a></p>
</body>
</html>
"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def export(conn, rotate_secret=False, clean=False):
    """静的サイト一式を dist/ へ書き出す。"""
    config = get_config()
    secret = get_secret(conn, rotate=rotate_secret)
    out_dir = DIST_DIR / secret

    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    combos = enumerate_combos(conn)
    if not combos:
        logging.error("書き出す対象がありません。先に収集を実行してください。")
        return None

    # テンプレートのURL生成を相対パスへ切り替える。
    webapp.STATIC_MODE = True
    client = webapp.app.test_client()
    webapp.app.config["PROPAGATE_EXCEPTIONS"] = True

    written = 0
    try:
        for tag, period, mode, deck in combos:
            key = urlmod.combo_key(tag, period, mode, deck)
            combo_dir = out_dir / key
            combo_dir.mkdir(parents=True, exist_ok=True)

            # 画面の定義は urls.SCREENS に一元化されている。
            for screen, (_endpoint, route, _file) in urlmod.SCREENS.items():
                for variant in [None] + urlmod.SCREEN_VARIANTS.get(screen, []):
                    url = route + "?" + query_for(tag, period, mode, deck, variant)
                    response = client.get(url)
                    if response.status_code != 200:
                        raise RuntimeError(
                            f"書き出しに失敗しました: {url} -> {response.status_code}")

                    filename = urlmod.static_filename(screen, variant)
                    (combo_dir / filename).write_bytes(response.data)
                    written += 1
        written += export_match_details(conn, client, out_dir)
        written += export_card_details(conn, client, out_dir)
        written += export_spells_page(client, out_dir)
    finally:
        webapp.STATIC_MODE = False

    # 絞り込みが減ったとき（デッキを使わなくなった等）に古いページを残さない。
    # 残すと公開サイトに存在しないはずの画面が居座り、容量も増え続ける。
    valid = {urlmod.combo_key(t, p, m, d) for t, p, m, d in combos}
    stale = 0
    for entry in out_dir.iterdir():
        if entry.is_dir() and entry.name not in RESERVED_DIRS and entry.name not in valid:
            shutil.rmtree(entry)
            stale += 1
    if stale:
        logging.info("不要になった絞り込みのページを削除しました: %d件", stale)

    images = copy_assets(out_dir)

    # 推測困難なURLで守る方式のため、検索エンジンに拾われないようにする。
    (DIST_DIR / "robots.txt").write_text(
        "User-agent: *\nDisallow: /\n", encoding="utf-8")
    (DIST_DIR / "_headers").write_text(
        "/*\n  X-Robots-Tag: noindex, nofollow\n", encoding="utf-8")

    default_tag = repo.default_player_tag(conn)
    write_index(out_dir, urlmod.combo_key(default_tag, "all", None, None))

    total_size = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
    logging.info("書き出し完了: %d組の絞り込み / %dページ / 画像 %d件",
                 len(combos), written, images)
    logging.info("出力先: %s（合計 %.1f MB）", out_dir, total_size / 1024 / 1024)
    return out_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description="静的サイトの書き出し")
    parser.add_argument("--rotate-secret", action="store_true",
                        help="公開URLの文字列を作り直す（旧URLは無効になる）")
    parser.add_argument("--clean", action="store_true", help="出力先を消してから書き出す")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = repo.connect()
    repo.init_schema(conn)
    try:
        out = export(conn, args.rotate_secret, args.clean)
        return 0 if out else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
