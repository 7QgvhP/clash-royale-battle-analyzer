# -*- coding: utf-8 -*-
"""勝率と信頼区間の算出。"""
import math


def wilson_interval(wins, total, z=1.96):
    """Wilson score interval を返す。

    単純な wins/total は試合数が少ないときに極端な値を取るため、
    区間の中心と誤差幅を併せて返す。total が 0 の場合は None を返す。
    """
    if not total:
        return None
    p = wins / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {
        "center": center,
        "margin": margin,
        "low": max(0.0, center - margin),
        "high": min(1.0, center + margin),
    }


def win_rate(wins, losses, draws=0, exclude_draws=True, z=1.96, min_matches=20):
    """勝率と信頼区間をまとめた辞書を返す。

    exclude_draws が True の場合、引き分けを母数から除く。
    """
    total = wins + losses if exclude_draws else wins + losses + draws
    matches = wins + losses + draws

    if total == 0:
        return {
            "wins": wins, "losses": losses, "draws": draws,
            "matches": matches, "total": 0,
            "rate": None, "margin": None, "low": None, "high": None,
            "reliable": False,
        }

    interval = wilson_interval(wins, total, z)
    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "matches": matches,
        "total": total,
        "rate": wins / total,
        "margin": interval["margin"],
        "low": interval["low"],
        "high": interval["high"],
        # 試合数が不足しているものは参考値として区別する。
        "reliable": total >= min_matches,
    }


def from_row(row, config, **extra):
    """勝敗数を持つ行から勝率統計を組み立てる。

    集計クエリの結果は wins / losses / draws を持つため、それを
    win_rate へ渡す処理が各所で繰り返される。設定の展開をここへ
    集約することで、設定項目が増えても修正箇所を1つに保てる。
    extra には表示用の項目（カード名など）を渡す。
    """
    stat = win_rate(row["wins"] or 0, row["losses"] or 0, row["draws"] or 0,
                    config.exclude_draws, config.z_score, config.min_matches)
    stat.update(extra)
    return stat


def overall(conn, filters, config):
    """全体成績を返す。"""
    where, params = filters.where()
    row = conn.execute(f"""
        SELECT
            SUM(CASE WHEN result = 'win'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN result = 'draw' THEN 1 ELSE 0 END) AS draws
        FROM matches m WHERE {where}
    """, params).fetchone()

    return from_row(row, config)
