# -*- coding: utf-8 -*-
"""SQLiteへのアクセス層。"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.config import DB_PATH

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

MATCH_COLUMNS = [
    "battle_key", "battle_time", "player_tag", "battle_type", "game_mode_id",
    "game_mode_name", "arena_name", "deck_selection", "event_tag", "is_ranked",
    "is_countable", "result", "crowns", "opponent_crowns", "king_hp",
    "princess_hp", "opp_king_hp", "opp_princess_hp", "starting_trophies",
    "trophy_change", "opponent_tag", "opponent_name",
    "opponent_starting_trophies", "my_deck_hash", "opp_deck_hash",
    "my_avg_level", "opp_avg_level", "level_diff", "elixir_leaked",
    "opp_elixir_leaked", "raw_json",
]


def connect(db_path=None):
    """DB接続を返す。行は辞書風にアクセスできる。"""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn):
    """テーブルを作成し、必要ならマイグレーションを適用する。

    schema.sql は CREATE TABLE IF NOT EXISTS のため、既存テーブルの
    形は変えられない。列や主キーの変更はマイグレーション側で行う。
    """
    from src.db import migrations

    # 既存DBは先に列を揃える。schema.sql には新しい列を前提とした
    # インデックス定義が含まれるため、順序を逆にすると失敗する。
    migrations.run(conn)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    migrations.set_version(conn, migrations.CURRENT_VERSION)


# --- プレイヤー -----------------------------------------------------------

def add_player(conn, player_tag, name=None, is_owner=False):
    """追跡対象のプレイヤーを登録する。既に居れば有効化のみ行う。"""
    tag = "#" + player_tag.lstrip("#").upper()
    conn.execute(
        "INSERT INTO players (player_tag, name, is_owner, is_active) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(player_tag) DO UPDATE SET is_active = 1,"
        "   name = COALESCE(excluded.name, players.name)",
        (tag, name, int(is_owner)))
    conn.commit()
    return tag


def remove_player(conn, player_tag):
    """プレイヤーを追跡対象から外す。蓄積済みの対戦は削除しない。"""
    tag = "#" + player_tag.lstrip("#").upper()
    cur = conn.execute("UPDATE players SET is_active = 0 WHERE player_tag = ?", (tag,))
    conn.commit()
    return cur.rowcount > 0


def update_player_profile(conn, player_tag, name, trophies, best_trophies):
    """収集時に取得したプロフィールを反映する。"""
    conn.execute(
        "UPDATE players SET name = ?, trophies = ?, best_trophies = ?,"
        " last_collected_at = datetime('now') WHERE player_tag = ?",
        (name, trophies, best_trophies, player_tag))


def list_players(conn, active_only=True):
    """登録済みプレイヤーの一覧を返す。所有者を先頭に並べる。"""
    where = "WHERE is_active = 1" if active_only else ""
    return conn.execute(f"""
        SELECT p.*,
               (SELECT COUNT(*) FROM matches m WHERE m.player_tag = p.player_tag) AS match_count
        FROM players p {where}
        ORDER BY p.is_owner DESC, p.added_at
    """).fetchall()


def get_player(conn, player_tag):
    if not player_tag:
        return None
    return conn.execute("SELECT * FROM players WHERE player_tag = ?",
                        ("#" + player_tag.lstrip("#").upper(),)).fetchone()


def default_player_tag(conn):
    """既定で表示するプレイヤーのタグを返す。"""
    row = conn.execute(
        "SELECT player_tag FROM players WHERE is_active = 1"
        " ORDER BY is_owner DESC, added_at LIMIT 1").fetchone()
    return row["player_tag"] if row else None


# --- メタ情報 -------------------------------------------------------------

def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, str(value)))


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


# --- カードマスタ ---------------------------------------------------------

def upsert_cards(conn, items, support_items, name_map):
    """カードマスタを登録・更新する。

    name_map はカードIDの文字列をキーに {"en": ..., "ja": ...} を持つ辞書。
    日本語名が無いカードは name_ja を NULL のままにする。
    """
    unknown = []
    for is_support, cards in ((0, items), (1, support_items)):
        for c in cards:
            entry = name_map.get(str(c["id"]), {})
            name_ja = (entry.get("ja") or "").strip() or None
            if name_ja is None:
                unknown.append((c["id"], c["name"]))
            icons = c.get("iconUrls") or {}
            conn.execute(
                "INSERT INTO cards (card_id, name_en, name_ja, rarity, max_level,"
                " elixir_cost, is_support, icon_url, evo_icon_url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(card_id) DO UPDATE SET"
                "   name_en = excluded.name_en,"
                "   name_ja = excluded.name_ja,"
                "   rarity = excluded.rarity,"
                "   max_level = excluded.max_level,"
                "   elixir_cost = excluded.elixir_cost,"
                "   is_support = excluded.is_support,"
                "   icon_url = excluded.icon_url,"
                "   evo_icon_url = excluded.evo_icon_url",
                (c["id"], c["name"], name_ja, c.get("rarity"), c.get("maxLevel"),
                 c.get("elixirCost"), is_support,
                 icons.get("medium"), icons.get("evolutionMedium")))
    conn.commit()
    return unknown


def game_max_level(conn):
    """カードマスタからゲーム内の最大レベルを導出する。

    ノーマルカードの max_level がゲーム内最大レベルに一致するため、
    全カードの max_level の最大値を採用する。
    """
    row = conn.execute("SELECT MAX(max_level) AS m FROM cards").fetchone()
    return row["m"] if row and row["m"] else None


def all_cards(conn):
    return conn.execute("SELECT * FROM cards ORDER BY card_id").fetchall()


def upsert_card_stats(conn, card_id, stats):
    """カード1枚分の性能値を保存する。

    項目の顔ぶれがカード種別ごとに違うためJSONのまま持つ。
    取得日時は更新のたびに入れ替え、画面に「いつ時点の値か」を出せるようにする。
    """
    source = stats.get("source", {})
    conn.execute(
        "INSERT INTO card_stats (card_id, stats_json, source, source_url, updated_at)"
        " VALUES (?, ?, ?, ?, datetime('now'))"
        " ON CONFLICT(card_id) DO UPDATE SET"
        "   stats_json = excluded.stats_json,"
        "   source = excluded.source,"
        "   source_url = excluded.source_url,"
        "   updated_at = excluded.updated_at",
        (card_id, json.dumps(stats, ensure_ascii=False),
         source.get("name"), source.get("url")))


def get_card_stats(conn, card_id):
    """カード1枚分の性能値を返す。未取得なら None。"""
    row = conn.execute(
        "SELECT stats_json, source, source_url, updated_at"
        " FROM card_stats WHERE card_id = ?", (card_id,)).fetchone()
    if row is None:
        return None
    stats = json.loads(row["stats_json"])
    stats["updated_at"] = row["updated_at"]
    return stats


def card_stats_count(conn):
    """性能値を保持しているカードの枚数。"""
    return conn.execute("SELECT COUNT(*) AS c FROM card_stats").fetchone()["c"]


def set_icon_paths(conn, card_id, icon_path, evo_icon_path):
    conn.execute("UPDATE cards SET icon_path = ?, evo_icon_path = ? WHERE card_id = ?",
                 (icon_path, evo_icon_path, card_id))


# --- 対戦 -----------------------------------------------------------------

def insert_match(conn, match, my_cards, opp_cards):
    """対戦を登録する。既に登録済みなら False を返す。

    存在チェックとINSERTを2文に分けると、収集が同時に走ったときに
    両方がチェックを通過してUNIQUE制約違反になる。INSERT OR IGNORE により
    判定と登録を単一の文で行い、この競合を避ける。
    """
    placeholders = ", ".join("?" for _ in MATCH_COLUMNS)
    cur = conn.execute(
        f"INSERT OR IGNORE INTO matches ({', '.join(MATCH_COLUMNS)}) VALUES ({placeholders})",
        [match[c] for c in MATCH_COLUMNS])

    # 既に登録済みの対戦なら、UNIQUE制約により何も挿入されない。
    if cur.rowcount == 0:
        return False
    match_id = cur.lastrowid

    for side, cards in (("me", my_cards), ("opponent", opp_cards)):
        for c in cards:
            conn.execute(
                "INSERT OR IGNORE INTO match_cards"
                " (match_id, side, card_id, level, normalized_level, evolution_level, is_support)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (match_id, side, c["card_id"], c["level"], c["normalized_level"],
                 c["evolution_level"], c["is_support"]))
    return True


def touch_deck(conn, player_tag, deck_hash_value, card_ids, battle_time):
    """使用デッキの出現情報を更新する。デッキはプレイヤーごとに管理する。"""
    conn.execute(
        "INSERT INTO decks (player_tag, deck_hash, card_ids, first_seen, last_seen, match_count)"
        " VALUES (?, ?, ?, ?, ?, 1)"
        " ON CONFLICT(player_tag, deck_hash) DO UPDATE SET"
        "   first_seen  = MIN(decks.first_seen, excluded.first_seen),"
        "   last_seen   = MAX(decks.last_seen, excluded.last_seen),"
        "   match_count = decks.match_count + 1",
        (player_tag, deck_hash_value, json.dumps(sorted(card_ids)), battle_time, battle_time))


def recount_decks(conn):
    """デッキの使用回数と初出・最終使用日時を実データから再計算する。"""
    conn.execute("""
        UPDATE decks SET
            match_count = COALESCE((SELECT COUNT(*) FROM matches m
                                    WHERE m.my_deck_hash = decks.deck_hash
                                      AND m.player_tag = decks.player_tag), 0),
            first_seen  = (SELECT MIN(m.battle_time) FROM matches m
                           WHERE m.my_deck_hash = decks.deck_hash
                             AND m.player_tag = decks.player_tag),
            last_seen   = (SELECT MAX(m.battle_time) FROM matches m
                           WHERE m.my_deck_hash = decks.deck_hash
                             AND m.player_tag = decks.player_tag)
    """)
    conn.commit()


# --- 収集ログ -------------------------------------------------------------

def log_collection(conn, status, player_tag=None, fetched=None, new=None,
                   warning=None, error=None):
    conn.execute(
        "INSERT INTO collection_log"
        " (player_tag, run_at, status, fetched_count, new_count, warning, error_message)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (player_tag, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         status, fetched, new, warning, error))
    conn.commit()


def latest_collection(conn, player_tag=None):
    """最後の収集結果を返す。プレイヤーを指定すればそのプレイヤー分に絞る。"""
    if player_tag:
        return conn.execute(
            "SELECT * FROM collection_log WHERE player_tag = ?"
            " ORDER BY id DESC LIMIT 1", (player_tag,)).fetchone()
    return conn.execute("SELECT * FROM collection_log ORDER BY id DESC LIMIT 1").fetchone()
