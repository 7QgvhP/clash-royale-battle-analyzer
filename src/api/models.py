# -*- coding: utf-8 -*-
"""APIレスポンスの解析。

バトルログのJSONを、DBへ保存できる形へ変換する。
"""
import hashlib
import json


def deck_hash(card_ids):
    """カードID列からデッキハッシュを作る。順序に依存しない。"""
    return "-".join(str(i) for i in sorted(card_ids))


def battle_key(battle_time, player_tag, opponent_tags):
    """対戦を一意に識別するキーを作る。重複登録の判定に用いる。"""
    seed = f"{battle_time}|{player_tag}|{'+'.join(sorted(opponent_tags))}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def normalize_level(level, max_level, game_max_level):
    """レアリティごとに基準の異なるレベルを、ゲーム内表示レベルへ変換する。

    ノーマルカードの max_level はゲーム内最大レベルと一致するため、
    その差分を加算することで全レアリティが同一スケールに揃う。

    注意: 同じ式を scripts/doctor.py の print_deck_levels() でも実装している。
    doctor.py は依存パッケージの導入前に動かせるよう標準ライブラリのみで
    書かれており、本モジュールを import できないため。
    式を変更する場合は doctor.py 側も必ず合わせること。
    """
    if level is None or max_level is None:
        return None
    return level + (game_max_level - max_level)


def _side_cards(side, game_max_level):
    """片側のカード情報を取り出す。タワートループも含める。"""
    rows = []
    for card in side.get("cards", []):
        rows.append({
            "card_id": card.get("id"),
            "level": card.get("level"),
            "normalized_level": normalize_level(
                card.get("level"), card.get("maxLevel"), game_max_level),
            "evolution_level": card.get("evolutionLevel", 0) or 0,
            "is_support": 0,
        })
    for card in side.get("supportCards", []):
        rows.append({
            "card_id": card.get("id"),
            "level": card.get("level"),
            "normalized_level": normalize_level(
                card.get("level"), card.get("maxLevel"), game_max_level),
            "evolution_level": 0,
            "is_support": 1,
        })
    return rows


def _average_level(cards):
    """通常カード8枚の平均正規化レベルを求める。タワートループは除く。"""
    values = [c["normalized_level"] for c in cards
              if c["is_support"] == 0 and c["normalized_level"] is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def parse_battle(battle, player_tag, game_max_level, config):
    """バトル1件を解析する。

    解析できない場合は None を返す。
    """
    team = battle.get("team") or []
    opponent = battle.get("opponent") or []
    if not team or not opponent:
        return None

    # 自分に該当するエントリを探す。見つからなければ先頭を採用する。
    normalized_tag = "#" + player_tag.lstrip("#").upper()
    me = next((t for t in team
               if (t.get("tag") or "").upper() == normalized_tag), team[0])
    foe = opponent[0]

    crowns = me.get("crowns")
    opp_crowns = foe.get("crowns")
    if crowns is None or opp_crowns is None:
        return None
    if crowns > opp_crowns:
        result = "win"
    elif crowns < opp_crowns:
        result = "loss"
    else:
        result = "draw"

    my_cards = _side_cards(me, game_max_level)
    opp_cards = _side_cards(foe, game_max_level)
    my_avg = _average_level(my_cards)
    opp_avg = _average_level(opp_cards)

    battle_type = battle.get("type")
    deck_selection = battle.get("deckSelection")
    # 集計対象は、対象モードかつ自分で組んだデッキの対戦に限る。
    is_countable = int(
        battle_type in config.target_battle_types
        and deck_selection in config.target_deck_selections
    )

    opponent_tags = [(o.get("tag") or "") for o in opponent]
    game_mode = battle.get("gameMode") or {}

    match = {
        "battle_key": battle_key(battle.get("battleTime"), normalized_tag, opponent_tags),
        "battle_time": battle.get("battleTime"),
        "player_tag": normalized_tag,
        "battle_type": battle_type,
        "game_mode_id": game_mode.get("id"),
        "game_mode_name": game_mode.get("name"),
        "arena_name": (battle.get("arena") or {}).get("name"),
        "deck_selection": deck_selection,
        "event_tag": battle.get("eventTag"),
        "is_ranked": int(battle_type == "pathOfLegend"),
        "is_countable": is_countable,
        "result": result,
        "crowns": crowns,
        "opponent_crowns": opp_crowns,
        "king_hp": me.get("kingTowerHitPoints"),
        "princess_hp": json.dumps(me.get("princessTowersHitPoints")),
        "opp_king_hp": foe.get("kingTowerHitPoints"),
        "opp_princess_hp": json.dumps(foe.get("princessTowersHitPoints")),
        # イベント戦では返らないためNULLになりうる。
        "starting_trophies": me.get("startingTrophies"),
        "trophy_change": me.get("trophyChange"),
        "opponent_tag": foe.get("tag"),
        "opponent_name": foe.get("name"),
        "opponent_starting_trophies": foe.get("startingTrophies"),
        "my_deck_hash": deck_hash([c["card_id"] for c in my_cards if c["is_support"] == 0]),
        "opp_deck_hash": deck_hash([c["card_id"] for c in opp_cards if c["is_support"] == 0]),
        "my_avg_level": my_avg,
        "opp_avg_level": opp_avg,
        "level_diff": round(my_avg - opp_avg, 3) if (my_avg is not None and opp_avg is not None) else None,
        "elixir_leaked": me.get("elixirLeaked"),
        "opp_elixir_leaked": foe.get("elixirLeaked"),
        "raw_json": json.dumps(battle, ensure_ascii=False),
    }
    return match, my_cards, opp_cards
