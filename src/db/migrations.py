# -*- coding: utf-8 -*-
"""データベースのマイグレーション。

対戦履歴はAPIから再取得できないため、既存データを保ったまま
スキーマを更新する。実行前にバックアップを取ることを推奨する。
"""
import logging

# 現在のスキーマ版。schema.sql を変更したら上げる。
CURRENT_VERSION = 2


def get_version(conn):
    """保存されているスキーマ版を返す。未記録なら推定する。"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if row is None:
        return 0

    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row:
        return int(row["value"])

    # 版が未記録の場合は、実際の列の有無で判断する。テーブルの存在では
    # 判定しない。移行が途中で失敗すると一部のテーブルだけが作られ、
    # 未完了の状態を「移行済み」と誤認するため。
    return 2 if _has_column(conn, "decks", "player_tag") else 1


def set_version(conn, version):
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)"
                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(version),))
    conn.commit()


def _has_column(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def migrate_1_to_2(conn):
    """単一プレイヤー構成をマルチプレイヤー構成へ移行する。

    既存データは .env に設定されたプレイヤーのものとして扱う。
    """
    from src.config import get_config
    owner_tag = get_config().player_tag

    # 既存の対戦から実際のタグを拾えるなら、そちらを優先する。
    row = conn.execute(
        "SELECT player_tag, COUNT(*) AS c FROM matches"
        " GROUP BY player_tag ORDER BY c DESC LIMIT 1").fetchone()
    if row and row["player_tag"]:
        owner_tag = row["player_tag"]

    logging.info("マイグレーション: 既存データを %s のものとして移行します", owner_tag)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            player_tag        TEXT PRIMARY KEY,
            name              TEXT,
            trophies          INTEGER,
            best_trophies     INTEGER,
            is_owner          INTEGER NOT NULL DEFAULT 0,
            is_active         INTEGER NOT NULL DEFAULT 1,
            added_at          TEXT NOT NULL DEFAULT (datetime('now')),
            last_collected_at TEXT
        )
    """)

    name = conn.execute("SELECT value FROM meta WHERE key='player_name'").fetchone()
    trophies = conn.execute("SELECT value FROM meta WHERE key='trophies'").fetchone()
    conn.execute(
        "INSERT OR IGNORE INTO players (player_tag, name, trophies, is_owner)"
        " VALUES (?, ?, ?, 1)",
        (owner_tag, name["value"] if name else None,
         int(trophies["value"]) if trophies and trophies["value"] else None))

    # decks は主キーを (player_tag, deck_hash) に変えるため作り直す。
    if not _has_column(conn, "decks", "player_tag"):
        conn.execute("ALTER TABLE decks RENAME TO decks_old")
        conn.execute("""
            CREATE TABLE decks (
                player_tag  TEXT    NOT NULL,
                deck_hash   TEXT    NOT NULL,
                card_ids    TEXT    NOT NULL,
                group_id    INTEGER,
                first_seen  TEXT,
                last_seen   TEXT,
                match_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (player_tag, deck_hash)
            )
        """)
        conn.execute(
            "INSERT INTO decks (player_tag, deck_hash, card_ids, group_id,"
            " first_seen, last_seen, match_count)"
            " SELECT ?, deck_hash, card_ids, group_id, first_seen, last_seen, match_count"
            " FROM decks_old", (owner_tag,))
        conn.execute("DROP TABLE decks_old")

    if not _has_column(conn, "deck_groups", "player_tag"):
        conn.execute("ALTER TABLE deck_groups ADD COLUMN player_tag TEXT")
        conn.execute("UPDATE deck_groups SET player_tag = ?", (owner_tag,))

    if not _has_column(conn, "collection_log", "player_tag"):
        conn.execute("ALTER TABLE collection_log ADD COLUMN player_tag TEXT")
        conn.execute("UPDATE collection_log SET player_tag = ?", (owner_tag,))

    conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_player"
                 " ON matches (player_tag, battle_time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decks_player ON decks (player_tag)")
    conn.commit()

    moved = conn.execute("SELECT COUNT(*) AS c FROM matches").fetchone()["c"]
    logging.info("マイグレーション完了: 対戦 %d件を保持しました", moved)


MIGRATIONS = {
    2: migrate_1_to_2,
}


def run(conn):
    """既存DBに必要なマイグレーションを順に適用する。

    新規DBに対しては何もしない。schema.sql が最新の形でテーブルを作るため。
    版の記録は schema.sql 適用後に呼び出し側が行う。
    """
    if not _table_exists(conn, "matches"):
        return 0

    version = get_version(conn)
    if version >= CURRENT_VERSION:
        return version

    for target in range(version + 1, CURRENT_VERSION + 1):
        migration = MIGRATIONS.get(target)
        if migration:
            logging.info("スキーマを v%d から v%d へ移行します", target - 1, target)
            migration(conn)
        set_version(conn, target)
    return CURRENT_VERSION
