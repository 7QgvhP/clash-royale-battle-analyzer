-- clash-royale-battle-analyzer データベース定義

-- 追跡対象のプレイヤー
CREATE TABLE IF NOT EXISTS players (
    player_tag        TEXT PRIMARY KEY,
    name              TEXT,
    trophies          INTEGER,
    best_trophies     INTEGER,
    is_owner          INTEGER NOT NULL DEFAULT 0,
    is_active         INTEGER NOT NULL DEFAULT 1,
    added_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_collected_at TEXT
);

-- 対戦
CREATE TABLE IF NOT EXISTS matches (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_key                 TEXT    NOT NULL UNIQUE,
    battle_time                TEXT    NOT NULL,
    player_tag                 TEXT    NOT NULL,
    battle_type                TEXT,
    game_mode_id               INTEGER,
    game_mode_name             TEXT,
    arena_name                 TEXT,
    deck_selection             TEXT,
    event_tag                  TEXT,
    is_ranked                  INTEGER NOT NULL DEFAULT 0,
    is_countable               INTEGER NOT NULL DEFAULT 0,
    result                     TEXT    NOT NULL,
    crowns                     INTEGER,
    opponent_crowns            INTEGER,
    king_hp                    INTEGER,
    princess_hp                TEXT,
    opp_king_hp                INTEGER,
    opp_princess_hp            TEXT,
    starting_trophies          INTEGER,
    trophy_change              INTEGER,
    opponent_tag               TEXT,
    opponent_name              TEXT,
    opponent_starting_trophies INTEGER,
    my_deck_hash               TEXT,
    opp_deck_hash              TEXT,
    my_avg_level               REAL,
    opp_avg_level              REAL,
    level_diff                 REAL,
    elixir_leaked              REAL,
    opp_elixir_leaked          REAL,
    raw_json                   TEXT    NOT NULL,
    created_at                 TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_matches_time      ON matches (battle_time);
CREATE INDEX IF NOT EXISTS idx_matches_countable ON matches (is_countable, battle_time);
CREATE INDEX IF NOT EXISTS idx_matches_my_deck   ON matches (my_deck_hash);

-- 対戦に登場したカード
CREATE TABLE IF NOT EXISTS match_cards (
    match_id         INTEGER NOT NULL,
    side             TEXT    NOT NULL,
    card_id          INTEGER NOT NULL,
    level            INTEGER,
    normalized_level INTEGER,
    evolution_level  INTEGER NOT NULL DEFAULT 0,
    is_support       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, side, card_id),
    FOREIGN KEY (match_id) REFERENCES matches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_match_cards_lookup ON match_cards (side, card_id);

-- カードマスタ
CREATE TABLE IF NOT EXISTS cards (
    card_id       INTEGER PRIMARY KEY,
    name_en       TEXT NOT NULL,
    name_ja       TEXT,
    rarity        TEXT,
    max_level     INTEGER,
    elixir_cost   INTEGER,
    is_support    INTEGER NOT NULL DEFAULT 0,
    icon_url      TEXT,
    evo_icon_url  TEXT,
    icon_path     TEXT,
    evo_icon_path TEXT
);

-- 自分の使用デッキ
CREATE TABLE IF NOT EXISTS decks (
    player_tag  TEXT    NOT NULL,
    deck_hash   TEXT    NOT NULL,
    card_ids    TEXT    NOT NULL,
    group_id    INTEGER,
    first_seen  TEXT,
    last_seen   TEXT,
    match_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_tag, deck_hash)
);

-- デッキグループ（類似デッキのまとまり）
CREATE TABLE IF NOT EXISTS deck_groups (
    group_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    player_tag          TEXT NOT NULL,
    representative_hash TEXT,
    -- display_name は v1.3.1 で廃止。デッキの呼び名はカード構成から自動生成する。
    -- 既存DBとの互換のため列は残すが、参照も更新もしない。
    display_name        TEXT,
    archetype           TEXT
);

-- 収集ログ
CREATE TABLE IF NOT EXISTS collection_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    player_tag    TEXT,
    run_at        TEXT NOT NULL,
    status        TEXT NOT NULL,
    fetched_count INTEGER,
    new_count     INTEGER,
    warning       TEXT,
    error_message TEXT
);

-- 設定・メタ情報
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_matches_player ON matches (player_tag, battle_time);
CREATE INDEX IF NOT EXISTS idx_decks_player   ON decks (player_tag);
