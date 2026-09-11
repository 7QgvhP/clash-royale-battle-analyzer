# -*- coding: utf-8 -*-
"""1試合ぶんの詳細データ。

対戦履歴の一覧では出しきれない、カード1枚ごとのレベル・タワーの残りHP・
エリクサーの漏れ量などをまとめて取り出す。
"""
import json

# プリンセスタワーは左右に1本ずつある。APIは生き残った塔のHPだけを返すため、
# 返ってきた個数から破壊された本数を逆算する。
PRINCESS_TOWER_COUNT = 2


def _parse_hp_list(value):
    """プリンセスタワーの残りHPを配列として取り出す。"""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if parsed is None:
        return []
    if isinstance(parsed, list):
        return [v for v in parsed if v is not None]
    return [parsed]


def _side_cards(conn, match_id, side):
    """片側のカードを、表示に必要な情報を添えて返す。"""
    rows = conn.execute("""
        SELECT mc.card_id, mc.level, mc.normalized_level, mc.evolution_level,
               mc.is_support, c.name_en, c.name_ja, c.rarity, c.elixir_cost,
               c.icon_path, c.evo_icon_path
        FROM match_cards mc
        JOIN cards c ON c.card_id = mc.card_id
        WHERE mc.match_id = ? AND mc.side = ?
    """, (match_id, side)).fetchall()

    cards, supports = [], []
    for r in rows:
        evolved = (r["evolution_level"] or 0) > 0
        item = {
            "card_id": r["card_id"],
            "name": r["name_ja"] or r["name_en"],
            "name_en": r["name_en"],
            "rarity": r["rarity"],
            "elixir_cost": r["elixir_cost"],
            "level": r["normalized_level"],
            "raw_level": r["level"],
            "evolved": evolved,
            # 進化を装備している場合は進化版の絵柄で見せる
            "icon_path": (r["evo_icon_path"] if evolved and r["evo_icon_path"]
                          else r["icon_path"]),
        }
        (supports if r["is_support"] else cards).append(item)

    # コストの安い順に並べると、デッキの見え方が毎回そろう
    cards.sort(key=lambda c: (c["elixir_cost"] is None, c["elixir_cost"] or 0, c["name"]))
    supports.sort(key=lambda c: c["name"])
    return cards, supports


def _side(conn, match, side, prefix):
    """片側ぶんの表示用データを組み立てる。"""
    cards, supports = _side_cards(conn, match["id"], side)
    princess = _parse_hp_list(match[f"{prefix}princess_hp"])
    levels = [c["level"] for c in cards if c["level"] is not None]

    return {
        "name": "自分" if side == "me" else (match["opponent_name"] or "相手"),
        "tag": match["player_tag"] if side == "me" else match["opponent_tag"],
        "crowns": match["crowns"] if side == "me" else match["opponent_crowns"],
        "king_hp": match[f"{prefix}king_hp"],
        "princess_hp": princess,
        # 返ってきた本数から、落とされた本数を求める
        "princess_lost": max(0, PRINCESS_TOWER_COUNT - len(princess)),
        "elixir_leaked": match["elixir_leaked"] if side == "me" else match["opp_elixir_leaked"],
        "avg_level": match["my_avg_level"] if side == "me" else match["opp_avg_level"],
        "min_level": min(levels) if levels else None,
        "max_level": max(levels) if levels else None,
        "cards": cards,
        "supports": supports,
        "starting_trophies": (match["starting_trophies"] if side == "me"
                              else match["opponent_starting_trophies"]),
    }


def match_detail(conn, match_id):
    """指定した対戦の詳細を返す。見つからなければ None。"""
    match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if match is None:
        return None

    return {
        "id": match["id"],
        "battle_time": match["battle_time"],
        "battle_type": match["battle_type"],
        "game_mode_name": match["game_mode_name"],
        "arena_name": match["arena_name"],
        "deck_selection": match["deck_selection"],
        "is_countable": match["is_countable"],
        "result": match["result"],
        "trophy_change": match["trophy_change"],
        "level_diff": match["level_diff"],
        "player_tag": match["player_tag"],
        "me": _side(conn, match, "me", ""),
        "opponent": _side(conn, match, "opponent", "opp_"),
    }


def listed_match_ids(conn, limit_per_player):
    """詳細ページを用意する対戦のIDを返す。

    静的サイトでは1試合につき1ファイルを書き出すため、対戦が増えるほど
    ファイル数が膨らむ。一覧から辿れる範囲（プレイヤーごとの直近ぶん）に
    限ることで、上限に達しないようにする。
    """
    ids = []
    for player in conn.execute("SELECT player_tag FROM players WHERE is_active = 1"):
        rows = conn.execute(
            "SELECT id FROM matches WHERE player_tag = ?"
            " ORDER BY battle_time DESC LIMIT ?",
            (player["player_tag"], limit_per_player)).fetchall()
        ids.extend(r["id"] for r in rows)
    return ids
