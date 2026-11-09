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

from src.db import repository as repo

# マスタリーのタスクセットが解放されるゲーム内レベル。
# タスクは3つで1セットになっていて、カードのレベルが上がるにつれて順に解放される。
# 未解放のセットは、そのカードを使っても進まない。
MASTERY_UNLOCK_LEVELS = (7, 10, 14)
TASKS_PER_SET = 3
# 段階は「完了したタスク数 + 1」。最初の1は、3勝してマスタリーを解放した分。
MASTERY_BASE = 1

# 解放レベルの出典。公式APIはこの情報を持たない。
MASTERY_UNLOCK_SOURCE = {
    "name": "Clash Royale Wiki（Card Mastery）",
    "license": "CC BY-SA",
    "url": "https://clashroyale.fandom.com/wiki/Card_Mastery",
}


def mastery_caps(conn):
    """カードごとのマスタリーの段階の上限を返す。未取得なら None。

    公式APIは一律で 10 を返すが、タスクセットが2つしかないカードは段階7で
    打ち止めになる。実際の上限は Liquipedia 由来の値を使う（収集時に保存）。
    """
    saved = repo.get_meta(conn, "mastery_caps")
    return json.loads(saved) if saved else None


def upgrade_table(conn):
    """レベルアップに必要な枚数・ゴールドの表を返す。未取得なら None。"""
    saved = repo.get_meta(conn, "upgrade_table")
    return json.loads(saved) if saved else None


def _required(table, kind, rarity, level):
    """ゲーム内レベル level に到達するために要る量。表に無ければ None。"""
    if not table:
        return None
    return (table.get(kind) or {}).get(rarity, {}).get(str(level))


def _reachable(table, rarity, level, count, game_max):
    """今の所持枚数だけで到達できるレベルと、上げられる段数を返す。

    レベルを1つ上げるたびに、その分の枚数を使う。使った残りで次も上げられるなら
    続けて上げる、という数え方をする（ゲーム内で枚数を使い切る順序と同じ）。
    必要量が分からない場合は、今のレベルのまま返す。
    """
    if level is None:
        return None, 0
    remain, reached = count, level
    while reached < game_max:
        need = _required(table, "cards", rarity, reached + 1)
        if need is None or remain < need:
            break
        remain -= need
        reached += 1
    return reached, reached - level


def _usage_counts(conn, player_tag):
    """このツールが持っている対戦履歴での、カードごとの使用回数を返す。"""
    return {r["card_id"]: r["n"] for r in conn.execute(
        "SELECT mc.card_id, COUNT(*) AS n FROM match_cards mc"
        " JOIN matches m ON m.id = mc.match_id"
        " WHERE mc.side = 'me' AND m.player_tag = ? GROUP BY mc.card_id",
        (player_tag,))}


def _mastery_unlock(level, mastery_max):
    """今のレベルで挑める段階の上限を返す。

    公式APIは「どのセットが解放されているか」を返さない。解放はカードの
    レベルだけで決まるため、持っているレベルから計算する。
    レベルか上限が分からない場合は None を返す。
    """
    if level is None or not mastery_max:
        return None
    total_sets = (mastery_max - MASTERY_BASE) // TASKS_PER_SET
    open_sets = min(total_sets, sum(1 for need in MASTERY_UNLOCK_LEVELS if level >= need))
    return open_sets * TASKS_PER_SET + MASTERY_BASE


def _card_row(card, have, badge, used, table, caps, game_max):
    """カード1枚分の育成状況を組み立てる。

    card … カードマスタの行、have … 所持状況（未入手なら None）、
    badge … マスタリーのバッジ（記録が無ければ None）。
    """
    rarity = (card["rarity"] or "").lower()
    # APIのレベルはレアリティごとの通し番号。ゲーム内の表記に直す。
    level = None
    if have and have["level"] is not None and have["max_level"]:
        level = have["level"] + (game_max - have["max_level"])

    count = have["card_count"] if have else 0
    next_level = level + 1 if level and level < game_max else None
    need = _required(table, "cards", rarity, next_level) if next_level else None
    short = max(0, need - count) if need is not None else None
    # 今の枚数だけで、続けて何レベルまで上げられるか
    reach, steps = _reachable(table, rarity, level, count, game_max)

    # マスタリーの上限は、分かっていればタスクセット由来の値を使う。無ければAPIの値。
    mastery_max = caps.get(card["name_en"]) or (badge["max_level"] if badge else None)
    # そのうち、いまのレベルで実際に挑める範囲
    mastery_open = _mastery_unlock(level, mastery_max)

    return {
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
        "short": short,
        "reach_level": reach,
        "reach_steps": steps,
        # 不足が無いものはレベルを上げられる。必要量が分からないものは None。
        "ready": (short == 0) if short is not None else None,
        "star_level": have["star_level"] if have else None,
        "evolution_level": have["evolution_level"] if have else 0,
        "mastery_level": badge["level"] if badge else None,
        "mastery_max": mastery_max,
        # いまのレベルで挑める上限（未解放のセットは含めない）
        "mastery_open_max": mastery_open,
        # 上限に達していれば、これ以上進められない（公式APIでは判別できない）
        "mastery_done": bool(badge and mastery_max and badge["level"] >= mastery_max),
        "mastery_progress": badge["progress"] if badge else None,
        "mastery_target": badge["target"] if badge else None,
        "used": used,
    }


def card_progress(conn, player_tag):
    """プレイヤーのカードごとの育成状況を返す。

    並びは「あと少しで上がる順」。画面では見出しを押して並べ替えられるが、
    最初に開いたときに知りたいのは「いま上げられるカード」のため。
    所持していないカードも、未入手として最後に並べる。
    """
    table = upgrade_table(conn)
    caps = (mastery_caps(conn) or {}).get("caps") or {}
    game_max = repo.game_max_level(conn) or 16

    cards = conn.execute(
        "SELECT card_id, name_en, name_ja, rarity, max_level, elixir_cost, icon_path"
        " FROM cards WHERE is_support = 0").fetchall()
    owned = {r["card_id"]: r for r in repo.player_cards(conn, player_tag)}
    mastery = {r["card_id"]: r for r in repo.player_mastery(conn, player_tag)
               if r["card_id"] is not None}
    used = _usage_counts(conn, player_tag)

    rows = [_card_row(card, owned.get(card["card_id"]), mastery.get(card["card_id"]),
                      used.get(card["card_id"], 0), table, caps, game_max)
            for card in cards]
    return sorted(rows, key=_soon)


def _soon(row):
    """あと少しで上がる順の並び。未入手・最大レベルは後ろへ送る。"""
    if not row["owned"] or row["maxed"] or row["short"] is None:
        return (2, 0, -row["used"])
    # 上げられるものを先頭に、次いで不足の少ない順。同じなら よく使う順。
    return (0 if row["short"] == 0 else 1, row["short"], -row["used"])


def summary(conn, player_tag, rows):
    """育成状況の要約（画面の上に出す指標）を返す。"""
    owned = [r for r in rows if r["owned"]]
    levels = [r["level"] for r in owned if r["level"]]
    return {
        "owned": len(owned),
        "total": len(rows),
        "average_level": round(sum(levels) / len(levels), 2) if levels else None,
        "maxed": sum(1 for r in owned if r["maxed"]),
        "ready": sum(1 for r in owned if r["ready"]),
        "steps": sum(r["reach_steps"] for r in owned),
        "mastery_done": sum(1 for r in rows if r["mastery_done"]),
        "mastery_known": sum(1 for r in rows if r["mastery_level"] is not None),
        "updated_at": repo.player_cards_updated_at(conn, player_tag),
    }
