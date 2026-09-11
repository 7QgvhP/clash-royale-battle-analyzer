# -*- coding: utf-8 -*-
"""相手カード別の勝率集計。"""
from src.analysis.stats import from_row


def opponent_card_stats(conn, filters, config, overall_rate=None):
    """相手デッキに含まれていたカードごとの勝率と出現率を返す。

    「そのカードと対戦した試合」を単位として集計する。ある試合の相手デッキ
    8枚それぞれに1件ずつ計上されるため、合計は総試合数の8倍になる。
    """
    where, params = filters.where()

    total_row = conn.execute(
        f"SELECT COUNT(*) AS c FROM matches m WHERE {where}", params).fetchone()
    total_matches = total_row["c"] or 0

    rows = conn.execute(f"""
        SELECT
            c.card_id, c.name_en, c.name_ja, c.rarity, c.elixir_cost,
            c.icon_path, c.evo_icon_path,
            SUM(CASE WHEN m.result = 'win'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN m.result = 'draw' THEN 1 ELSE 0 END) AS draws,
            SUM(CASE WHEN mc.evolution_level > 0 THEN 1 ELSE 0 END) AS evo_count
        FROM match_cards mc
        JOIN matches m ON m.id = mc.match_id
        JOIN cards   c ON c.card_id = mc.card_id
        WHERE mc.side = 'opponent' AND mc.is_support = 0 AND {where}
        GROUP BY c.card_id
    """, params).fetchall()

    results = []
    for r in rows:
        appeared = (r["wins"] or 0) + (r["losses"] or 0) + (r["draws"] or 0)
        stat = from_row(
            r, config,
            card_id=r["card_id"],
            name=r["name_ja"] or r["name_en"],
            name_en=r["name_en"],
            rarity=r["rarity"],
            elixir_cost=r["elixir_cost"],
            icon_path=r["icon_path"],
            evo_icon_path=r["evo_icon_path"],
            evo_count=r["evo_count"] or 0,
            appearance_rate=appeared / total_matches if total_matches else 0.0,
        )
        # 勝率デルタ: 全体勝率からの乖離。負が大きいほど苦手。
        if stat["rate"] is not None and overall_rate is not None:
            stat["delta"] = stat["rate"] - overall_rate
        else:
            stat["delta"] = None
        results.append(stat)

    # 苦手な順に並べる。素の勝率で並べると1戦0勝のカードが「勝率0%」として
    # 上位を独占し、実際の傾向が埋もれる。そこで信頼区間の上限の昇順で並べる。
    # 上限は「良く見積もってもこの程度」を意味し、試合数が少ないほど大きくなる
    # ため、証拠の乏しいカードが自動的に後ろへ下がる。
    results.sort(key=lambda x: (
        x["high"] is None,
        x["high"] if x["high"] is not None else 1.0,
        -x["total"],
    ))
    return results, total_matches


def support_card_stats(conn, filters, config, overall_rate=None):
    """相手のタワートループ別の勝率を返す。"""
    where, params = filters.where()
    rows = conn.execute(f"""
        SELECT
            c.card_id, c.name_en, c.name_ja, c.icon_path,
            SUM(CASE WHEN m.result = 'win'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN m.result = 'draw' THEN 1 ELSE 0 END) AS draws
        FROM match_cards mc
        JOIN matches m ON m.id = mc.match_id
        JOIN cards   c ON c.card_id = mc.card_id
        WHERE mc.side = 'opponent' AND mc.is_support = 1 AND {where}
        GROUP BY c.card_id
    """, params).fetchall()

    results = []
    for r in rows:
        stat = from_row(
            r, config,
            card_id=r["card_id"],
            name=r["name_ja"] or r["name_en"],
            icon_path=r["icon_path"],
        )
        stat["delta"] = (stat["rate"] - overall_rate
                         if stat["rate"] is not None and overall_rate is not None else None)
        results.append(stat)
    results.sort(key=lambda x: -x["matches"])
    return results
