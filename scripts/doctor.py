# -*- coding: utf-8 -*-
"""設定診断ツール。

.env の記述を検証し、APIへの疎通・プレイヤータグの存在・
カードレベル正規化の妥当性をまとめて確認する。

標準ライブラリのみで動作するため、依存パッケージの導入前でも実行できる。
"""
import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DB_PATH = ROOT / "data" / "battles.db"

PROXY_BASE = "https://proxy.royaleapi.dev/v1"
DIRECT_BASE = "https://api.clashroyale.com/v1"
PROXY_IP = "45.79.218.79"
# プロキシ前段のCloudflareが既定のUser-Agent（Python-urllib/x.y）を遮断するため、
# クライアントを明示するUser-Agentを必ず送出する。
USER_AGENT = "clash-royale-battle-analyzer/1.0.0"

OK = "[ OK ]"
NG = "[ NG ]"
INFO = "[INFO]"


def load_env():
    """.env を読み込んで辞書として返す。

    src/config.py の Config も同じ内容を読むが、あちらは python-dotenv に
    依存する。ここでは導入前でも診断できるよう独自に解析している。
    項目を追加した場合は両方に反映すること。
    """
    if not ENV_PATH.exists():
        print(f"{NG} .env が見つかりません: {ENV_PATH}")
        print("     .env.example をコピーして .env を作成してください。")
        sys.exit(1)

    env = {}
    # BOM付きで保存された場合にも対応する
    for raw in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def check_config(env):
    """.env の記述内容を検証する。トークン本体は表示しない。"""
    print("=== 1. 設定ファイルの検証 ===")
    ok = True

    token = env.get("CR_API_TOKEN", "")
    if not token:
        print(f"{NG} CR_API_TOKEN が空です")
        ok = False
    elif len(token) < 100:
        print(f"{NG} CR_API_TOKEN が短すぎます（{len(token)}文字）")
        print("     コピー時に途中で切れている可能性があります")
        ok = False
    elif not token.startswith("eyJ"):
        print(f"{NG} CR_API_TOKEN の形式が想定と異なります")
        ok = False
    else:
        print(f"{OK} CR_API_TOKEN: {token[:6]}...（{len(token)}文字）")

    tag = env.get("CR_PLAYER_TAG", "")
    if not tag:
        print(f"{NG} CR_PLAYER_TAG が空です")
        ok = False
    else:
        body = tag.lstrip("#").upper()
        invalid = set(body) - set("0289PYLQGRJCUV")
        if not tag.startswith("#"):
            print(f"{INFO} CR_PLAYER_TAG に # がありません。補って処理します")
        if invalid:
            print(f"{NG} CR_PLAYER_TAG に使われない文字が含まれます: {', '.join(sorted(invalid))}")
            if "O" in invalid:
                print("     'O'（オー）は使われません。'0'（ゼロ）の誤りと思われます")
            if "I" in invalid:
                print("     'I'（アイ）は使われません")
            ok = False
        else:
            print(f"{OK} CR_PLAYER_TAG: #{body}")

    use_proxy = env.get("CR_USE_PROXY", "true").lower() != "false"
    base = PROXY_BASE if use_proxy else DIRECT_BASE
    label = f"プロキシ経由（許可IPは {PROXY_IP}）" if use_proxy else "直接アクセス（許可IPは自分のIP）"
    print(f"{OK} 接続方式: {label}")
    print()
    return ok, token, "#" + env.get("CR_PLAYER_TAG", "").lstrip("#").upper(), base


def api_get(base, token, path):
    """APIへGETリクエストを送り、JSONを返す。"""
    req = urllib.request.Request(
        base + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def explain_error(err):
    """APIエラーの原因と対処を表示する。"""
    if isinstance(err, urllib.error.HTTPError):
        body = err.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
            detail = parsed.get("reason") or parsed.get("error_name") or ""
        except Exception:
            parsed, detail = {}, ""
        print(f"{NG} HTTP {err.code} {detail}")
        if parsed.get("error_code") == 1010:
            print("     プロキシ前段のCloudflareにUser-Agentを遮断されています")
            print("     APIクライアントは必ずUser-Agentを設定してください")
            return
        if err.code == 403 and "ip" in detail.lower():
            print(f"     許可IPの指定が誤っています。トークンには {PROXY_IP} を登録してください")
            print("     自分のIPを登録した場合、プロキシ経由のアクセスは拒否されます")
        elif err.code == 403:
            print("     トークンが不正です。末尾までコピーできているか確認してください")
        elif err.code == 404:
            print("     プレイヤータグが存在しません。'O' と '0' の取り違えを確認してください")
        elif err.code == 503:
            print("     Supercell側のメンテナンス中です。時間をおいて再試行してください")
    else:
        print(f"{NG} 通信に失敗しました: {err}")


def print_deck_levels(player, game_max):
    """現在のバトルデッキの正規化レベルを表示する。

    正規化式の定義元は src/api/models.py の normalize_level()。
    このスクリプトは依存パッケージの導入前でも動くよう標準ライブラリのみで
    書いており、本体を import できないため同じ式を再実装している。
    式を変更する場合は両方を合わせること。
    """
    print("     現在のバトルデッキの正規化レベル:")
    print("     " + "-" * 56)
    for c in player.get("currentDeck", []):
        raw = c.get("level", 0)
        mx = c.get("maxLevel", game_max)
        print(f"     {c.get('name', ''):<24} API level={raw:>2}"
              f" / maxLevel={mx:>2} -> Lv.{raw + (game_max - mx)}")
    print("     " + "-" * 56)
    print("     ゲーム内の表示レベルと一致するか確認してください。")


def open_db():
    """DBを開く。存在しなければ None を返す。"""
    if not DB_PATH.exists():
        print(f"{NG} データベースがありません: {DB_PATH}")
        print("     python -m src.collector.collect --init を先に実行してください")
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def cmd_list_cards():
    """カードマスタの一覧を表示する。ゲーム内表記との突き合わせに使う。"""
    conn = open_db()
    if conn is None:
        return 1
    rows = conn.execute(
        "SELECT card_id, name_en, name_ja, rarity FROM cards"
        " ORDER BY is_support, rarity, name_en").fetchall()
    print(f"カード一覧（{len(rows)}件）")
    print(f"  {'ID':<11} {'英語名':<22} 日本語名")
    print("  " + "-" * 58)
    for r in rows:
        print(f"  {r['card_id']:<11} {r['name_en']:<22} {r['name_ja'] or '（未登録）'}")
    print()
    print("ゲーム内の表記と異なる場合は src/data/card_names_ja.json を修正し、")
    print("python -m src.collector.collect --reload-names を実行してください。")
    conn.close()
    return 0


def cmd_missing_names():
    """日本語名が未登録のカードを表示する。"""
    conn = open_db()
    if conn is None:
        return 1
    rows = conn.execute(
        "SELECT card_id, name_en FROM cards"
        " WHERE name_ja IS NULL OR name_ja = '' ORDER BY card_id").fetchall()
    if not rows:
        print(f"{OK} 日本語名が未登録のカードはありません。")
        conn.close()
        return 0

    print(f"{INFO} 日本語名が未登録のカード: {len(rows)}件")
    print()
    print("src/data/card_names_ja.json に以下を追記してください:")
    print()
    for r in rows:
        print(f'  "{r["card_id"]}": {{ "en": "{r["name_en"]}", "ja": "" }},')
    print()
    print("追記後: python -m src.collector.collect --reload-names")
    conn.close()
    return 0


def cmd_check_levels(env):
    """現在のバトルデッキのレベル正規化を検証する。"""
    ok, token, tag, base = check_config(env)
    if not ok:
        return 1
    try:
        player = api_get(base, token, f"/players/{urllib.parse.quote(tag)}")
        cards = api_get(base, token, "/cards").get("items", [])
    except Exception as e:
        explain_error(e)
        return 1

    game_max = max(c.get("maxLevel", 0) for c in cards)
    print(f"{OK} ゲーム最大レベル（maxLevelの最大値から導出）: {game_max}")
    print()
    print_deck_levels(player, game_max)
    return 0


def full_diagnosis(env):
    """全項目の診断を行う。"""
    ok, token, tag, base = check_config(env)
    if not ok:
        print("設定に問題があるため、疎通確認を中止します。")
        return 1

    encoded = urllib.parse.quote(tag)

    print("=== 2. APIへの疎通確認 ===")
    try:
        player = api_get(base, token, f"/players/{encoded}")
    except Exception as e:
        explain_error(e)
        return 1

    print(f"{OK} プレイヤー名: {player.get('name')}")
    print(f"{OK} トロフィー: {player.get('trophies')}（最高 {player.get('bestTrophies')}）")
    print(f"{OK} 総対戦数: {player.get('battleCount')}")
    print()

    print("=== 3. カードマスタとレベル正規化 ===")
    try:
        cards = api_get(base, token, "/cards").get("items", [])
    except Exception as e:
        explain_error(e)
        return 1

    game_max = max(c.get("maxLevel", 0) for c in cards)
    print(f"{OK} カード総数: {len(cards)}枚")
    print(f"{OK} ゲーム最大レベル: {game_max}")
    print()
    print_deck_levels(player, game_max)
    print()

    print("=== 4. バトルログの取得 ===")
    try:
        battles = api_get(base, token, f"/players/{encoded}/battlelog")
    except Exception as e:
        explain_error(e)
        return 1

    print(f"{OK} 取得件数: {len(battles)}件")
    if battles:
        modes = {}
        for b in battles:
            modes[b.get("type", "unknown")] = modes.get(b.get("type", "unknown"), 0) + 1
        print(f"{OK} 最新の対戦: {battles[0].get('battleTime')}（UTC）")
        print(f"{OK} 最古の対戦: {battles[-1].get('battleTime')}（UTC）")
        print("     モード内訳: " + ", ".join(f"{k}={v}" for k, v in sorted(modes.items())))
    else:
        print(f"{INFO} バトルログが空です。しばらく対戦していない場合に起こります")
    print()

    print("=== 5. ローカルデータ ===")
    if not DB_PATH.exists():
        print(f"{INFO} データベース未作成。python -m src.collector.collect --init を実行してください")
    else:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
        countable = conn.execute(
            "SELECT COUNT(*) c FROM matches WHERE is_countable = 1").fetchone()["c"]
        missing = conn.execute(
            "SELECT COUNT(*) c FROM cards WHERE name_ja IS NULL OR name_ja = ''").fetchone()["c"]
        print(f"{OK} 蓄積済みの対戦: {total}件（うち集計対象 {countable}件）")
        if missing:
            print(f"{INFO} 日本語名が未登録のカード: {missing}件（--missing-names で確認できます）")
        else:
            print(f"{OK} 日本語名はすべて登録済みです")
        conn.close()
    print()
    print("すべての診断項目を通過しました。")
    return 0


def main():
    parser = argparse.ArgumentParser(description="設定と接続の診断")
    parser.add_argument("--list-cards", action="store_true",
                        help="カードマスタの一覧を表示する（ゲーム内表記との照合用）")
    parser.add_argument("--missing-names", action="store_true",
                        help="日本語名が未登録のカードを表示する")
    parser.add_argument("--check-levels", action="store_true",
                        help="現在のデッキのレベル正規化を検証する")
    args = parser.parse_args()

    if args.list_cards:
        return cmd_list_cards()
    if args.missing_names:
        return cmd_missing_names()

    env = load_env()
    if args.check_levels:
        return cmd_check_levels(env)
    return full_diagnosis(env)


if __name__ == "__main__":
    sys.exit(main())
