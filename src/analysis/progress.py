# -*- coding: utf-8 -*-
"""カードの育成状況（レベル・所持枚数・必要量・マスタリー）の集計。

公式APIは「今のレベル」と「持っている枚数」を返すが、「次のレベルに上げるのに
何枚要るか」は返さない。必要量は Clash Royale Wiki から取り込んで meta に
保存してあり（収集時に更新）、ここで突き合わせる。

レベルの表記には2種類ある。

  - APIの level … レアリティごとの通し番号（コモンの1 ＝ レジェンダリーの1 ではない）
  - ゲーム内の表記 … すべてのカードで共通（最大16）

必要量の表はゲーム内の表記で並んでいるため、ここでも同じ表記に揃えて扱う。
"""
import json

# 画面に出す並び順の種類。キーはURLの値、値は画面のラベル。
SORT_LABELS = {
    "soon": "あと少し順",
    "steps": "上げられる段数順",
    "level": "レベルの低い順",
    "used": "よく使う順",
    "mastery": "マスタリーの進み順",
}
DEFAULT_SORT = "soon"


def upgrade_table(conn):
    """レベルアップに必要な枚数・ゴールドの表を返す。未取得なら None。"""
    saved = repo_get_meta(conn, "upgrade_table")
    return json.loads(saved) if saved else None


def repo_get_meta(conn, key):
    """meta テーブルの値を1つ返す（repository への依存を1か所に閉じる）。"""
    from src.db import repository as repo
    return repo.get_meta(conn, key)


def _required(table, kind, rarity, level):
    """ゲーム内レベル level に到達するために要る量。表に無ければ None。"""
    if not table:
        return None
    return (table.get(kind) or {}).get(rarity, {}).get(str(level))


def _reachable(table, rarity, level, count, game_max):
    """今の所持枚数だけで到達できるレベルと、そこまでに要るゴールドを返す。

    レベルを1つ上げるたびに、その分の枚数を使う。使った残りで次も上げられるなら
    続けて上げる、という数え方をする（ゲーム内で枚数を使い切る順序と同じ）。
    必要量が分からない場合は、今のレベルのまま返す。
    """
    if level is None:
        return None, 0, 0
    remain, reached, gold = count, level, 0
    while reached < game_max:
        need = _required(table, "cards", rarity, reached + 1)
        if need is None or remain < need:
            break
        remain -= need
        gold += _required(table, "gold", rarity, reached + 1) or 0
        reached += 1
    return reached, reached - level, gold


def card_progress(conn, player_tag, sort=DEFAULT_SORT):
    """プレイヤーのカードごとの育成状況を返す。

    所持していないカードも、未入手として最後に並べる。
    """
    from src.db import repository as repo

    table = upgrade_table(conn)
    game_max = repo.game_max_level(conn) or 16

    cards = conn.execute(
        "SELECT card_id, name_en, name_ja, rarity, max_level, elixir_cost, icon_path"
        " FROM cards WHERE is_support = 0").fetchall()
    owned = {r["card_id"]: r for r in repo.player_cards(conn, player_tag)}
    mastery = {r["card_id"]: r for r in repo.player_mastery(conn, player_tag)
               if r["card_id"] is not None}

    # 並べ替えの「よく使う順」に使う、このツールが持っている使用回数
    used = {r["card_id"]: r["n"] for r in conn.execute(
        "SELECT mc.card_id, COUNT(*) AS n FROM match_cards mc"
        " JOIN matches m ON m.id = mc.match_id"
        " WHERE mc.side = 'me' AND m.player_tag = ? GROUP BY mc.card_id",
        (player_tag,))}

    rows = []
    for card in cards:
        have = owned.get(card["card_id"])
        rarity = (card["rarity"] or "").lower()
        # ゲーム内の表記に直す。max_level はレアリティごとの上限。
        level = None
        if have and have["level"] is not None and have["max_level"]:
            level = have["level"] + (game_max - have["max_level"])

        count = have["card_count"] if have else 0
        next_level = level + 1 if level and level < game_max else None
        need = _required(table, "cards", rarity, next_level) if next_level else None
        gold = _required(table, "gold", rarity, next_level) if next_level else None
        short = max(0, need - count) if need is not None else None
        # 今の枚数だけで、続けて何レベルまで上げられるか
        reach, steps, reach_gold = _reachable(table, rarity, level, count, game_max)

        badge = mastery.get(card["card_id"])
        rows.append({
            "card_id": card["card_id"],
            "name": card["name_ja"] or card["name_en"],
            "name_en": card["name_en"],
            "rarity": rarity,
            "elixir_cost": card["elixir_cost"],
            "icon_path": card["icon_path"],
            "owned": have is not None,
            "level": level,
            "max_level": game_max,
            "maxed": level == game_max if level else False,
            "count": count,
            "next_level": next_level,
            "need": need,
            "gold": gold,
            "short": short,
            "reach_level": reach,
            "reach_steps": steps,
            "reach_gold": reach_gold,
            # 不足が無いものは「上げられる」。必要量が分からないものは None。
            "ready": (short == 0) if short is not None else None,
            "star_level": have["star_level"] if have else None,
            "evolution_level": have["evolution_level"] if have else 0,
            "mastery_level": badge["level"] if badge else None,
            "mastery_max": badge["max_level"] if badge else None,
            "mastery_progress": badge["progress"] if badge else None,
            "mastery_target": badge["target"] if badge else None,
            "used": used.get(card["card_id"], 0),
        })

    return _sorted(rows, sort)


def _sorted(rows, sort):
    """指定された並び順に並べ替える。未入手・最大レベルは常に後ろへ送る。"""
    def soon(r):
        # 上げられるものを先頭に、次いで不足の少ない順。
        if not r["owned"] or r["maxed"] or r["short"] is None:
            return (2, 0, -r["used"])
        return (0 if r["short"] == 0 else 1, r["short"], -r["used"])

    def steps(r):
        # 上げられる段数の多い順。同じ段数ならよく使う順。
        if not r["owned"]:
            return (1, 0, 0)
        return (0, -r["reach_steps"], -r["used"])

    def level(r):
        return (2, 0, 0) if not r["owned"] else (0, r["level"] or 0, -r["used"])

    def used(r):
        return (-r["used"], r["name"])

    def mastery(r):
        if r["mastery_level"] is None:
            return (1, 0, 0)
        # 段階が高い順。段階の中での進み具合は公式APIから分からないため、
        # 同じ段階の中はよく使う順にする。
        return (0, -r["mastery_level"], -r["used"])

    key = {"soon": soon, "steps": steps, "level": level, "used": used,
           "mastery": mastery}.get(sort, soon)
    return sorted(rows, key=key)


def summary(conn, player_tag, rows):
    """育成状況の要約（画面の上に出す指標）を返す。"""
    from src.db import repository as repo

    owned = [r for r in rows if r["owned"]]
    levels = [r["level"] for r in owned if r["level"]]
    return {
        "owned": len(owned),
        "total": len(rows),
        "average_level": round(sum(levels) / len(levels), 2) if levels else None,
        "maxed": sum(1 for r in owned if r["maxed"]),
        "ready": sum(1 for r in owned if r["ready"]),
        "steps": sum(r["reach_steps"] for r in owned),
        "mastery_done": sum(1 for r in rows
                            if r["mastery_level"] and r["mastery_level"] == r["mastery_max"]),
        "mastery_known": sum(1 for r in rows if r["mastery_level"] is not None),
        "updated_at": repo.player_cards_updated_at(conn, player_tag),
    }
