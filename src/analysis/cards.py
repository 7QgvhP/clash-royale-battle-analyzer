# -*- coding: utf-8 -*-
"""相手カード別の勝率集計。"""
from src.analysis.stats import from_row

# 「勝率 × 対戦数」のマトリクスの段と列。
# 段は上ほど勝率が低く（苦手が先）、列は右ほど対戦数が多い。
MATRIX_ROWS = (("bad", "苦手"), ("even", "互角"), ("good", "得意"))
MATRIX_COLS = (("few", "たまに当たる"), ("mid", "ときどき当たる"), ("many", "よく当たる"))

# 全体勝率からこの幅に収まるカードは「互角」とみなす
EVEN_BAND = 0.03


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


def _matrix_thresholds(totals):
    """対戦数を3つに分ける境目を、3分位で求める。

    環境は期間によって変わり、何戦なら「よく当たる」かも一緒に動く。
    固定の戦数で区切ると、期間を変えたときに片側へ寄ってしまうため、
    その時点のカードの分布から境目を決める。
    """
    ordered = sorted(totals)
    return ordered[len(ordered) // 3], ordered[len(ordered) * 2 // 3]


def _matrix_row(delta, band):
    """勝率デルタから、段（苦手・互角・得意）を決める。"""
    if delta < -band:
        return "bad"
    return "good" if delta > band else "even"


def _matrix_col(total, first, second):
    """対戦数から、列（たまに・ときどき・よく当たる）を決める。"""
    if total < first:
        return "few"
    return "mid" if total < second else "many"


def card_matrix(rows, band=EVEN_BAND):
    """相手カードを「勝率 × 対戦数」の3×3に振り分ける。

    この2軸は散布図が本来の形だが、カード画像を点にすると重なって読めず、
    一度取り消している（v1.10.1）。位置を段階に丸めてマスへ入れると、
    重なりが原理的に起きず、全カードを画像のまま並べられる。

    マスの中は勝率の低い順に詰めるため、いちばん苦手なカードが左上に来る。
    同率のときは対戦数の多いほう（根拠の確かなほう）を先に置く。
    カードが少なすぎて列を作れない場合は None を返す。
    """
    cards = [r for r in rows if r["rate"] is not None and r["delta"] is not None]
    if len(cards) < len(MATRIX_COLS):
        return None

    first, second = _matrix_thresholds([c["total"] for c in cards])
    buckets = {(row, col): [] for row, _ in MATRIX_ROWS for col, _ in MATRIX_COLS}
    for card in cards:
        key = (_matrix_row(card["delta"], band), _matrix_col(card["total"], first, second))
        buckets[key].append(card)

    for cell in buckets.values():
        cell.sort(key=lambda c: (c["rate"], -c["total"]))

    # 列の見出しに出す対戦数の幅は、実際に入ったカードから作る。
    columns = []
    for col, label in MATRIX_COLS:
        totals = [c["total"] for row, _ in MATRIX_ROWS for c in buckets[(row, col)]]
        columns.append({
            "key": col,
            "label": label,
            "range": f"{min(totals)}〜{max(totals)}戦" if totals else "—",
        })

    return {
        "columns": columns,
        "rows": [{
            "key": row,
            "label": row_label,
            "cells": [{"key": col, "label": col_label, "cards": buckets[(row, col)]}
                      for col, col_label in MATRIX_COLS],
        } for row, row_label in MATRIX_ROWS],
        "total": len(cards),
        "band": band,
    }
