# -*- coding: utf-8 -*-
"""自デッキの類似度グループ化と、デッキ別成績の集計。"""
import json

from src.analysis.stats import from_row


def regroup_decks(conn, threshold, player_tag=None):
    """使用デッキを類似度でグループ化する。

    逐次的に割り当てると処理順序で結果が変わるため、実行のたびに
    全デッキを対象として最初から作り直す。使用回数の多いデッキを
    代表として選ぶことで、主力デッキが基準になるようにする。

    グループ化はプレイヤーごとに独立して行う。player_tag を省略すると
    登録されている全プレイヤーを対象にする。
    """
    if player_tag is None:
        tags = [r["player_tag"] for r in
                conn.execute("SELECT DISTINCT player_tag FROM decks").fetchall()]
    else:
        tags = [player_tag]

    total_groups = 0
    for tag in tags:
        decks = conn.execute(
            "SELECT deck_hash, card_ids, match_count FROM decks WHERE player_tag = ?"
            " ORDER BY match_count DESC, deck_hash", (tag,)).fetchall()

        # 代表デッキが同じグループは、group_id をそのまま引き継ぐ。
        # 毎回作り直すと ID が変わり、デッキで絞り込んだURLが日々変わってしまう。
        previous = {r["representative_hash"]: r["group_id"] for r in
                    conn.execute("SELECT group_id, representative_hash FROM deck_groups"
                                 " WHERE player_tag = ?", (tag,))}

        conn.execute("UPDATE decks SET group_id = NULL WHERE player_tag = ?", (tag,))

        assigned = {}
        kept = set()
        for deck in decks:
            if deck["deck_hash"] in assigned:
                continue
            cards = set(json.loads(deck["card_ids"]))

            group_id = previous.get(deck["deck_hash"])
            if group_id is None:
                cur = conn.execute(
                    "INSERT INTO deck_groups (player_tag, representative_hash)"
                    " VALUES (?, ?)", (tag, deck["deck_hash"]))
                group_id = cur.lastrowid
            kept.add(group_id)

            for other in decks:
                if other["deck_hash"] in assigned:
                    continue
                overlap = len(cards & set(json.loads(other["card_ids"])))
                if overlap >= threshold:
                    assigned[other["deck_hash"]] = group_id

        for deck_hash_value, group_id in assigned.items():
            conn.execute("UPDATE decks SET group_id = ? WHERE player_tag = ? AND deck_hash = ?",
                         (group_id, tag, deck_hash_value))

        # 代表でなくなったグループを片付ける。残すと存在しない絞り込みが
        # 一覧に出続け、静的サイトにも不要なページが増える。
        if kept:
            placeholders = ", ".join("?" for _ in kept)
            conn.execute(f"DELETE FROM deck_groups WHERE player_tag = ?"
                         f" AND group_id NOT IN ({placeholders})", [tag, *kept])
        else:
            conn.execute("DELETE FROM deck_groups WHERE player_tag = ?", (tag,))

        total_groups += len(kept)

    conn.commit()
    return total_groups


def representative_cards(conn, deck_hash_value):
    """デッキハッシュから、表示用のカード情報を並べて返す。"""
    if not deck_hash_value:
        return []
    ids = [int(i) for i in deck_hash_value.split("-") if i]
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT card_id, name_en, name_ja, elixir_cost, icon_path"
        f" FROM cards WHERE card_id IN ({placeholders})", ids).fetchall()
    by_id = {r["card_id"]: r for r in rows}

    cards = []
    for i in ids:
        row = by_id.get(i)
        cards.append({
            "card_id": i,
            "name": (row["name_ja"] or row["name_en"]) if row else str(i),
            "icon_path": row["icon_path"] if row else None,
            "elixir_cost": row["elixir_cost"] if row else None,
        })
    # コストの安い順に並べると、デッキの見た目が安定する。
    cards.sort(key=lambda c: (c["elixir_cost"] is None, c["elixir_cost"] or 0, c["name"]))
    return cards


def deck_label(cards):
    """デッキの呼び名をカード構成から組み立てる。

    デッキに手動で名前を付ける仕組みは持たない。閲覧者は操作できず、
    所有者だけが使える非対称な機能になるため。コストの高い（＝特徴的な）
    カードを並べることで、名前が無くても見分けがつくようにする。
    """
    if not cards:
        return "（デッキ不明）"
    key = sorted(cards, key=lambda c: -(c["elixir_cost"] or 0))[:3]
    return "・".join(c["name"] for c in key) + " ほか"


def deck_group_stats(conn, filters, config):
    """デッキグループごとの成績を返す。"""
    where, params = filters.where()
    rows = conn.execute(f"""
        SELECT
            g.group_id, g.representative_hash,
            SUM(CASE WHEN m.result = 'win'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN m.result = 'draw' THEN 1 ELSE 0 END) AS draws,
            AVG(m.my_avg_level) AS avg_level,
            MAX(m.battle_time) AS last_used
        FROM matches m
        JOIN decks d       ON d.deck_hash = m.my_deck_hash AND d.player_tag = m.player_tag
        JOIN deck_groups g ON g.group_id = d.group_id
        WHERE {where}
        GROUP BY g.group_id
    """, params).fetchall()

    results = []
    for r in rows:
        cards = representative_cards(conn, r["representative_hash"])
        stat = from_row(
            r, config,
            group_id=r["group_id"],
            label=deck_label(cards),
            avg_level=round(r["avg_level"], 2) if r["avg_level"] is not None else None,
            last_used=r["last_used"],
            cards=cards,
        )
        results.append(stat)
    results.sort(key=lambda x: -x["matches"])
    return results


def list_deck_groups(conn, player_tag=None):
    """フィルタ用のデッキグループ一覧を返す。"""
    where, params = ("WHERE g.player_tag = ?", [player_tag]) if player_tag else ("", [])
    rows = conn.execute(f"""
        SELECT g.group_id, g.representative_hash,
               COALESCE(SUM(d.match_count), 0) AS match_count
        FROM deck_groups g
        LEFT JOIN decks d ON d.group_id = g.group_id
        {where}
        GROUP BY g.group_id
        ORDER BY match_count DESC
    """, params).fetchall()

    groups = []
    for r in rows:
        cards = representative_cards(conn, r["representative_hash"])
        groups.append({
            "group_id": r["group_id"],
            "label": deck_label(cards),
            "match_count": r["match_count"],
            "cards": cards,
        })
    return groups

