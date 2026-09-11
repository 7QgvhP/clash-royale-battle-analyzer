# -*- coding: utf-8 -*-
"""対戦履歴の収集。

バトルログは直近の数十戦しか取得できないため、定期的に実行して
ローカルDBへ蓄積していく。タスクスケジューラからの起動を想定する。
"""
import argparse
import json
import logging
import sys

from src.api import cardstats as cardstats_api
from src.api.client import ApiError, ClashRoyaleClient
from src.api.models import parse_battle
from src.config import (CARD_IMAGE_DIR, CARD_NAMES_PATH, CARD_STATS_MANUAL_PATH,
                        CARD_WEB_DIR, LOG_DIR, get_config)
from src.db import repository as repo


def setup_logging(verbose=False):
    """ログをファイルと標準出力の双方へ出す。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.FileHandler(LOG_DIR / "collect.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_name_map():
    """カード日本語名の対応表を読み込む。存在しなければ空とする。"""
    if not CARD_NAMES_PATH.exists():
        logging.warning("日本語名の対応表がありません: %s", CARD_NAMES_PATH)
        return {}
    with CARD_NAMES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def update_cards(conn, client):
    """カードマスタと日本語名を更新する。"""
    items, support_items = client.get_cards()
    unknown = repo.upsert_cards(conn, items, support_items, load_name_map())
    total = len(items) + len(support_items)
    logging.info("カードマスタを更新しました: %d件（うち日本語名 未登録 %d件）", total, len(unknown))
    for card_id, name_en in unknown:
        logging.warning("日本語名が未登録です: %s (%s)", name_en, card_id)
    max_level = repo.game_max_level(conn)
    repo.set_meta(conn, "game_max_level", max_level)
    conn.commit()
    logging.info("ゲーム最大レベル: %s", max_level)
    return unknown


def load_stats_manual():
    """自動取得できなかった性能値の補完ファイルを読み込む。"""
    if not CARD_STATS_MANUAL_PATH.exists():
        return {}
    with CARD_STATS_MANUAL_PATH.open(encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def update_card_stats(conn):
    """カードの性能値を Clash Royale Wiki から取得して保存する。

    公式APIは性能値を返さないため外部の情報源を使う。取得できなかったカードは
    名前を出すので、`src/data/card_stats_manual.json` に手で書き足す。
    """
    cards = conn.execute(
        "SELECT card_id, name_en, name_ja FROM cards WHERE is_support = 0"
        " ORDER BY name_en").fetchall()
    if not cards:
        logging.error("カードマスタが未取得です。--update-cards を先に実行してください。")
        return []

    names = [c["name_en"] for c in cards]
    logging.info("性能値を取得します: %d枚（%d件ずつ問い合わせ）",
                 len(names), cardstats_api.BATCH_SIZE)
    pages = cardstats_api.fetch_pages(names)
    manual = load_stats_manual()

    saved, missing = 0, []
    for card in cards:
        name_en = card["name_en"]
        wikitext, revid = pages.get(name_en, (None, None))
        stats = cardstats_api.build_stats(wikitext, name_en, revid)

        # 補完ファイルの内容を上書きで合成する
        extra = manual.get(name_en)
        if extra:
            stats = stats or {"units": [], "attributes": [], "extras": {},
                              "source": {"name": cardstats_api.SOURCE_NAME,
                                         "license": cardstats_api.LICENSE,
                                         "page": name_en,
                                         "url": cardstats_api.PAGE_URL + name_en.replace(" ", "_"),
                                         "base_level": cardstats_api.BASE_LEVEL}}
            if extra.get("units"):
                stats["units"] = extra["units"]
            if extra.get("attributes"):
                stats["attributes"] = extra["attributes"]

        if stats is None:
            missing.append(card["name_ja"] or name_en)
            continue
        repo.upsert_card_stats(conn, card["card_id"], stats)
        saved += 1
    conn.commit()

    with_units = conn.execute(
        "SELECT COUNT(*) AS c FROM card_stats"
        " WHERE stats_json LIKE '%\"hp\"%' OR stats_json LIKE '%\"dmg\"%'").fetchone()["c"]
    logging.info("性能値を保存しました: %d枚（うちレベル別の数値あり %d枚）", saved, with_units)
    for name in missing:
        logging.warning("性能値を取得できませんでした: %s", name)
    return missing


def download_images(conn, client, force=False):
    """カード画像をローカルへ保存する。既に存在するものは再取得しない。"""
    CARD_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for card in repo.all_cards(conn):
        icon_path = evo_path = None
        for url, suffix in ((card["icon_url"], ""), (card["evo_icon_url"], "_evo")):
            if not url:
                continue
            filename = f"{card['card_id']}{suffix}.png"
            dest = CARD_IMAGE_DIR / filename
            if force or not dest.exists():
                try:
                    dest.write_bytes(client.download(url))
                    saved += 1
                except Exception as e:
                    logging.warning("画像の取得に失敗しました: %s (%s)", card["name_en"], e)
                    continue
            if suffix:
                evo_path = filename
            else:
                icon_path = filename
        repo.set_icon_paths(conn, card["card_id"], icon_path, evo_path)
    conn.commit()
    logging.info("カード画像を保存しました: 新規 %d件（保存先 %s）", saved, CARD_IMAGE_DIR)


# カードの表示サイズは最大44px。高解像度画面を考慮しても132pxあれば足りる。
CARD_DISPLAY_PX = 132


def optimize_images(conn, force=False):
    """カード画像を表示サイズへ縮小し、WebPへ変換する。

    APIが返す画像は285x420で1枚あたり160KB前後あり、一覧画面では
    80枚以上を並べるため、そのまま配信すると通信量が過大になる。
    """
    from PIL import Image

    CARD_WEB_DIR.mkdir(parents=True, exist_ok=True)
    converted = 0
    for card in repo.all_cards(conn):
        icon_path = evo_path = None
        for suffix in ("", "_evo"):
            src = CARD_IMAGE_DIR / f"{card['card_id']}{suffix}.png"
            if not src.exists():
                continue
            name = f"{card['card_id']}{suffix}.webp"
            dest = CARD_WEB_DIR / name
            if force or not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
                try:
                    im = Image.open(src).convert("RGBA")
                    im.thumbnail((CARD_DISPLAY_PX, CARD_DISPLAY_PX), Image.LANCZOS)
                    im.save(dest, "WEBP", quality=82, method=6)
                    converted += 1
                except Exception as e:
                    logging.warning("画像の変換に失敗しました: %s (%s)", src.name, e)
                    continue
            if suffix:
                evo_path = name
            else:
                icon_path = name
        repo.set_icon_paths(conn, card["card_id"], icon_path, evo_path)
    conn.commit()

    total = sum(f.stat().st_size for f in CARD_WEB_DIR.glob("*.webp"))
    logging.info("カード画像を最適化しました: 変換 %d件 / 合計 %.1f MB",
                 converted, total / 1024 / 1024)


def collect_player(conn, client, config, player_tag):
    """1人分のバトルログを取得し、未登録の対戦をDBへ追加する。"""
    max_level = repo.game_max_level(conn)
    if not max_level:
        raise RuntimeError("カードマスタが未取得です。--init または --update-cards を先に実行してください。")

    # 初回収集では全件が新規になるため、取りこぼし警告の対象外とする。
    is_first_run = conn.execute(
        "SELECT COUNT(*) AS c FROM matches WHERE player_tag = ?",
        (player_tag,)).fetchone()["c"] == 0

    # ダッシュボードのヘッダ表示用にプロフィールを保存する。
    try:
        player = client.get_player(player_tag)
        repo.update_player_profile(conn, player_tag, player.get("name"),
                                   player.get("trophies"), player.get("bestTrophies"))
        conn.commit()
    except Exception as e:
        logging.warning("[%s] プロフィールの取得に失敗しました: %s", player_tag, e)

    battles = client.get_battlelog(player_tag)
    fetched = len(battles)
    new_count = 0
    skipped = 0

    for battle in battles:
        parsed = parse_battle(battle, player_tag, max_level, config)
        if parsed is None:
            skipped += 1
            continue
        match, my_cards, opp_cards = parsed
        if repo.insert_match(conn, match, my_cards, opp_cards):
            new_count += 1
            if match["is_countable"]:
                repo.touch_deck(conn, player_tag, match["my_deck_hash"],
                                [c["card_id"] for c in my_cards if c["is_support"] == 0],
                                match["battle_time"])
    conn.commit()

    warning = None
    # 取得できた全件が新規だった場合、その手前の対戦を取りこぼした可能性がある。
    if fetched > 0 and new_count == fetched and not is_first_run:
        warning = (f"取得した{fetched}件すべてが新規でした。"
                   "収集間隔の間に取りこぼしが発生した可能性があります。")
        logging.warning("[%s] %s", player_tag, warning)

    if skipped:
        logging.warning("[%s] 解析できなかった対戦: %d件", player_tag, skipped)

    logging.info("[%s] 収集完了: 取得 %d件 / 新規 %d件", player_tag, fetched, new_count)
    repo.log_collection(conn, "success", player_tag, fetched, new_count, warning, None)
    return fetched, new_count


def collect_battles(conn, client, config):
    """登録されている全プレイヤーの対戦を収集する。

    1人の失敗が他のプレイヤーの収集を止めないよう、例外は個別に処理する。
    """
    players = repo.list_players(conn)
    if not players:
        # 未登録なら .env のプレイヤーを所有者として登録する。
        repo.add_player(conn, config.player_tag, is_owner=True)
        players = repo.list_players(conn)

    total_new = 0
    failed = []
    for p in players:
        tag = p["player_tag"]
        try:
            _, new_count = collect_player(conn, client, config, tag)
            total_new += new_count
        except ApiError as e:
            logging.error("[%s] APIエラー: %s", tag, e)
            repo.log_collection(conn, "error", tag, error=str(e))
            failed.append(tag)

    logging.info("収集完了: %d人 / 新規 %d件（失敗 %d人）",
                 len(players), total_new, len(failed))
    if failed:
        raise ApiError("収集に失敗したプレイヤーがあります: " + ", ".join(failed))
    return total_new


def regroup(conn, config):
    """デッキのグループ化をやり直す。集計結果の安定のため毎回実行する。"""
    from src.analysis.decks import regroup_decks
    count = regroup_decks(conn, config.similarity_threshold)
    logging.info("デッキグループを再構築しました: %d グループ", count)


def reload_names(conn):
    """日本語名の対応表だけをDBへ反映する。"""
    name_map = load_name_map()
    updated = 0
    for card in repo.all_cards(conn):
        entry = name_map.get(str(card["card_id"]), {})
        name_ja = (entry.get("ja") or "").strip() or None
        if name_ja != card["name_ja"]:
            conn.execute("UPDATE cards SET name_ja = ? WHERE card_id = ?",
                         (name_ja, card["card_id"]))
            updated += 1
    conn.commit()
    logging.info("日本語名を反映しました: %d件を更新", updated)


def main(argv=None):
    parser = argparse.ArgumentParser(description="クラロワ対戦履歴の収集")
    parser.add_argument("--init", action="store_true",
                        help="DBを初期化し、カードマスタ・画像を取得して初回収集を行う")
    parser.add_argument("--update-cards", action="store_true", help="カードマスタを更新する")
    parser.add_argument("--update-card-stats", action="store_true",
                        help="カードの性能値をClash Royale Wikiから取得する")
    parser.add_argument("--reload-names", action="store_true", help="日本語名の対応表を反映する")
    parser.add_argument("--download-images", action="store_true", help="カード画像を取得する")
    parser.add_argument("--force-images", action="store_true", help="既存の画像も再取得する")
    parser.add_argument("--optimize-images", action="store_true", help="カード画像を最適化し直す")
    parser.add_argument("--add-player", metavar="TAG",
                        help="追跡するプレイヤーを追加する（例: --add-player \"#ABC12345\"）")
    parser.add_argument("--remove-player", metavar="TAG",
                        help="プレイヤーを追跡対象から外す（蓄積済みの対戦は消さない）")
    parser.add_argument("--list-players", action="store_true", help="登録済みプレイヤーを一覧表示する")
    parser.add_argument("--verbose", action="store_true", help="詳細なログを出力する")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    config = get_config()

    try:
        config.validate()
    except Exception as e:
        logging.error("設定に問題があります: %s", e)
        return 1

    config.ensure_directories()
    conn = repo.connect()
    repo.init_schema(conn)

    try:
        client = ClashRoyaleClient(config)

        if args.optimize_images:
            optimize_images(conn, force=True)
            return 0

        if args.list_players:
            players = repo.list_players(conn, active_only=False)
            if not players:
                logging.info("登録されているプレイヤーはいません。")
            for p in players:
                mark = "所有者" if p["is_owner"] else "  友人"
                state = "" if p["is_active"] else "（停止中）"
                logging.info("%s  %-12s %-16s %5d戦 %s",
                             mark, p["player_tag"], p["name"] or "-",
                             p["match_count"], state)
            return 0

        if args.add_player:
            tag = repo.add_player(conn, args.add_player)
            # タグが実在するか確認し、名前を取得する。
            try:
                player = client.get_player(tag)
            except ApiError as e:
                repo.remove_player(conn, tag)
                logging.error("プレイヤー %s を登録できません: %s", tag, e)
                return 1
            repo.update_player_profile(conn, tag, player.get("name"),
                                       player.get("trophies"), player.get("bestTrophies"))
            conn.commit()
            logging.info("プレイヤーを登録しました: %s（%s）", tag, player.get("name"))
            collect_player(conn, client, config, tag)
            repo.recount_decks(conn)
            regroup(conn, config)
            return 0

        if args.remove_player:
            if repo.remove_player(conn, args.remove_player):
                logging.info("追跡対象から外しました: %s（蓄積済みの対戦は残ります）",
                             args.remove_player)
                return 0
            logging.error("該当するプレイヤーが見つかりません: %s", args.remove_player)
            return 1

        if args.init:
            update_cards(conn, client)
            update_card_stats(conn)
            download_images(conn, client)
            optimize_images(conn)
            collect_battles(conn, client, config)
            repo.recount_decks(conn)
            regroup(conn, config)
            return 0

        if args.update_cards:
            update_cards(conn, client)
            update_card_stats(conn)
            download_images(conn, client, force=args.force_images)
            optimize_images(conn, force=args.force_images)
            return 0

        if args.update_card_stats:
            update_card_stats(conn)
            return 0

        if args.reload_names:
            reload_names(conn)
            return 0

        if args.download_images:
            download_images(conn, client, force=args.force_images)
            optimize_images(conn, force=args.force_images)
            return 0

        collect_battles(conn, client, config)
        repo.recount_decks(conn)
        regroup(conn, config)
        return 0

    except ApiError as e:
        logging.error("APIエラー: %s", e)
        repo.log_collection(conn, "error", error=str(e))
        return 1
    except Exception as e:
        logging.exception("想定外のエラーが発生しました")
        repo.log_collection(conn, "error", error=str(e))
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
