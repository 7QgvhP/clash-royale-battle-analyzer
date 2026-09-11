# -*- coding: utf-8 -*-
"""カードレベル差と勝敗の相関分析。"""
import math

from src.analysis.stats import from_row

# 固定の帯（-2.0以下 など）は実データの分布と合わず、両端が常に空になっていた。
# 実際に出現した範囲だけを一定の刻みで並べることで、相関が読み取れるようにする。
# 刻み幅は config.yaml の level_bucket_step で調整する。


def bucket_key(level_diff, step):
    """レベル差を指定の刻みの代表値へ丸める。"""
    if level_diff is None:
        return None
    return round(round(level_diff / step) * step, 4)


def bucket_label(key, step):
    """区分の表示名。0 付近は符号を付けない。

    刻みが細かいときは小数第2位まで出さないと区別がつかない。
    """
    digits = 2 if step < 0.25 else 1
    if abs(key) < 1e-9:
        return "±0"
    return f"{key:+.{digits}f}"


def level_diff_stats(conn, filters, config):
    """レベル差の区分ごとの勝率を、レベル差の小さい順に返す。

    データが存在する区分だけを返すため、空の点が並ぶことはない。
    """
    where, params = filters.where()
    rows = conn.execute(
        f"SELECT level_diff, result FROM matches m"
        f" WHERE {where} AND level_diff IS NOT NULL", params).fetchall()

    step = config.level_bucket_step
    tally = {}
    for r in rows:
        key = bucket_key(r["level_diff"], step)
        counts = tally.setdefault(key, {"wins": 0, "losses": 0, "draws": 0})
        counts[{"win": "wins", "loss": "losses", "draw": "draws"}[r["result"]]] += 1

    return [from_row(tally[key], config, key=key, label=bucket_label(key, step))
            for key in sorted(tally)]


def _sigmoid(z):
    """オーバーフローを避けた形のロジスティック関数。"""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


# 当てはめに必要な最低限の試合数。これを下回るとカーブが不安定になる。
FIT_MIN_MATCHES = 20
# カーブを描く点の数。実データの範囲を等分する。
CURVE_POINTS = 41


def level_logistic_fit(conn, filters):
    """レベル差から勝率を予測するロジスティック回帰を当てはめる。

        P(勝ち) = 1 / (1 + exp(-(a + b × レベル差)))

    勝敗は2値、レベル差は連続値なので、この形が素直に対応する。
    直線で当てはめると勝率が0〜100%の外へ出てしまうため使えない。

    ニュートン法で係数を求め、係数の分散共分散から信頼帯も返す。
    引き分けは勝ちとも負けとも言えないため除く。
    """
    where, params = filters.where()
    rows = conn.execute(
        f"SELECT level_diff, result FROM matches m"
        f" WHERE {where} AND level_diff IS NOT NULL AND result IN ('win', 'loss')",
        params).fetchall()

    n = len(rows)
    xs = [r["level_diff"] for r in rows]
    ys = [1.0 if r["result"] == "win" else 0.0 for r in rows]
    wins = sum(ys)

    # 試合数が少ない、または全勝・全敗だと当てはめが発散する
    if n < FIT_MIN_MATCHES or wins == 0 or wins == n or min(xs) == max(xs):
        return None

    a = b = 0.0
    h00 = h01 = h11 = det = 0.0
    for _ in range(50):
        g0 = g1 = 0.0
        h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            p = _sigmoid(a + b * x)
            residual = y - p
            w = p * (1 - p)
            g0 += residual
            g1 += residual * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            return None
        step_a = (h11 * g0 - h01 * g1) / det
        step_b = (h00 * g1 - h01 * g0) / det
        a += step_a
        b += step_b
        if abs(step_a) < 1e-10 and abs(step_b) < 1e-10:
            break

    # 逆ヘッセ行列が係数の分散共分散にあたる
    var_a = h11 / det
    var_b = h00 / det
    cov_ab = -h01 / det
    se_b = math.sqrt(var_b) if var_b > 0 else None

    # 当てはまりの良さ（McFadden の擬似決定係数）
    base = wins / n
    ll = sum(y * math.log(max(_sigmoid(a + b * x), 1e-12))
             + (1 - y) * math.log(max(1 - _sigmoid(a + b * x), 1e-12))
             for x, y in zip(xs, ys))
    ll0 = sum(y * math.log(base) + (1 - y) * math.log(1 - base) for y in ys)
    pseudo_r2 = 1 - ll / ll0 if ll0 else None

    # 実データのある範囲だけを描く。範囲外は根拠が無く、外挿になるため。
    lo, hi = min(xs), max(xs)
    curve = []
    for i in range(CURVE_POINTS):
        x = lo + (hi - lo) * i / (CURVE_POINTS - 1)
        eta = a + b * x
        var_eta = var_a + x * x * var_b + 2 * x * cov_ab
        margin = 1.96 * math.sqrt(var_eta) if var_eta > 0 else 0.0
        curve.append({
            "x": round(x, 4),
            "y": _sigmoid(eta),
            "low": _sigmoid(eta - margin),
            "high": _sigmoid(eta + margin),
        })

    z = b / se_b if se_b else None
    return {
        "a": a,
        "b": b,
        "se_b": se_b,
        "z": z,
        "significant": bool(z is not None and abs(z) > 1.96),
        "n": n,
        "pseudo_r2": pseudo_r2,
        # レベル差が無いときの勝率。実力の目安になる。
        "rate_at_zero": _sigmoid(a),
        # 勝率50%になるレベル差。どこまでの不利なら五分に戦えるか。
        "even_diff": (-a / b) if b else None,
        # レベル差0付近での効き。1レベルあたりの勝率変化（S字の傾きが最大の付近）。
        "slope_per_level": b * _sigmoid(a) * (1 - _sigmoid(a)),
        "x_min": lo,
        "x_max": hi,
        "curve": curve,
    }


def level_correlation(conn, filters):
    """レベル差と勝敗の相関係数を返す。

    勝ちを1・負けを0とした値とレベル差のピアソン相関。
    +1 に近いほど「レベルが高いほど勝つ」関係が強いことを示す。
    引き分けは勝ちとも負けとも言えないため除く。
    """
    where, params = filters.where()
    rows = conn.execute(
        f"SELECT level_diff, result FROM matches m"
        f" WHERE {where} AND level_diff IS NOT NULL AND result IN ('win', 'loss')",
        params).fetchall()

    n = len(rows)
    if n < 2:
        return None

    xs = [r["level_diff"] for r in rows]
    ys = [1.0 if r["result"] == "win" else 0.0 for r in rows]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None

    r = cov / math.sqrt(var_x * var_y)
    if abs(r) >= 0.5:
        strength = "強い"
    elif abs(r) >= 0.3:
        strength = "中程度の"
    elif abs(r) >= 0.1:
        strength = "弱い"
    else:
        strength = "ほとんど無い"
    return {"r": round(r, 3), "n": n, "strength": strength}


def level_summary(conn, filters):
    """平均レベルとレベル差の概況を返す。"""
    where, params = filters.where()
    row = conn.execute(f"""
        SELECT
            AVG(my_avg_level)  AS my_avg,
            AVG(opp_avg_level) AS opp_avg,
            AVG(level_diff)    AS diff_avg,
            SUM(CASE WHEN level_diff < -0.5 THEN 1 ELSE 0 END) AS behind,
            SUM(CASE WHEN level_diff >  0.5 THEN 1 ELSE 0 END) AS ahead,
            COUNT(*) AS total
        FROM matches m WHERE {where} AND level_diff IS NOT NULL
    """, params).fetchone()

    if not row or not row["total"]:
        return None
    return {
        "my_avg": round(row["my_avg"], 2),
        "opp_avg": round(row["opp_avg"], 2),
        "diff_avg": round(row["diff_avg"], 2),
        "behind": row["behind"],
        "ahead": row["ahead"],
        "total": row["total"],
    }
