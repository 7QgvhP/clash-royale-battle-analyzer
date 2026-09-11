# -*- coding: utf-8 -*-
"""時系列の推移（勝率・トロフィー）と対戦履歴の取得。"""
from src.analysis.stats import from_row

# APIのバトル日時は "YYYYMMDDThhmmss.000Z" 形式。
# SQLiteの日付関数が扱えないため、部分文字列で日付キーを組み立てる。
DATE_KEY = "substr(m.battle_time, 1, 4) || '-' || substr(m.battle_time, 5, 2)" \
           " || '-' || substr(m.battle_time, 7, 2)"


def win_rate_trend(conn, filters, config, unit="day"):
    """日次または週次の勝率推移を返す。"""
    where, params = filters.where()
    # 週次は日付キーからユリウス日を求め、7日単位に丸める。
    if unit == "week":
        bucket = f"date(julianday({DATE_KEY}) - (CAST(strftime('%w', {DATE_KEY}) AS INTEGER)))"
    else:
        bucket = DATE_KEY

    rows = conn.execute(f"""
        SELECT {bucket} AS bucket,
               SUM(CASE WHEN m.result = 'win'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN m.result = 'draw' THEN 1 ELSE 0 END) AS draws
        FROM matches m WHERE {where}
        GROUP BY bucket ORDER BY bucket
    """, params).fetchall()

    points = []
    for r in rows:
        points.append(from_row(r, config, bucket=r["bucket"]))
    return points


def trophy_trend(conn, filters):
    """トロフィーの推移を返す。トロフィー情報のない対戦は除外する。"""
    where, params = filters.where()
    rows = conn.execute(f"""
        SELECT m.battle_time, m.starting_trophies, m.trophy_change
        FROM matches m
        WHERE {where} AND m.starting_trophies IS NOT NULL
        ORDER BY m.battle_time
    """, params).fetchall()

    points = []
    for r in rows:
        after = r["starting_trophies"] + (r["trophy_change"] or 0)
        points.append({"battle_time": r["battle_time"], "trophies": after})
    return points


def recent_matches(conn, filters, limit=50, offset=0):
    """対戦履歴の一覧を返す。両者のデッキも併せて取得する。"""
    where, params = filters.where()
    rows = conn.execute(f"""
        SELECT m.* FROM matches m
        WHERE {where}
        ORDER BY m.battle_time DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()

    from src.analysis.decks import representative_cards

    matches = []
    for r in rows:
        matches.append({
            "id": r["id"],
            "battle_time": r["battle_time"],
            "battle_type": r["battle_type"],
            "game_mode_name": r["game_mode_name"],
            "result": r["result"],
            "crowns": r["crowns"],
            "opponent_crowns": r["opponent_crowns"],
            "trophy_change": r["trophy_change"],
            "opponent_name": r["opponent_name"],
            "level_diff": r["level_diff"],
            "my_cards": representative_cards(conn, r["my_deck_hash"]),
            "opp_cards": representative_cards(conn, r["opp_deck_hash"]),
        })
    return matches


def match_count(conn, filters):
    """絞り込み条件に合致する対戦数を返す。"""
    where, params = filters.where()
    row = conn.execute(f"SELECT COUNT(*) AS c FROM matches m WHERE {where}", params).fetchone()
    return row["c"] or 0
