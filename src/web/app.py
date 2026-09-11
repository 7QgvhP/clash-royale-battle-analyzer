# -*- coding: utf-8 -*-
"""ローカルWebダッシュボード。"""
import json
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, abort, render_template, request, send_from_directory

from src.analysis import cards as cards_analysis
from src.analysis import cardstats as cardstats_analysis
from src.analysis import decks as decks_analysis
from src.analysis import detail as detail_analysis
from src.analysis import levels as levels_analysis
from src.analysis import stats as stats_analysis
from src.analysis import trends as trends_analysis
from src.analysis.filters import Filters
from src.config import CARD_WEB_DIR, get_config
from src.db import repository as repo
from src.web import urls as urlmod

app = Flask(__name__)
config = get_config()

# 静的サイトの書き出し中は True。テンプレートのURL生成が相対パスに切り替わる。
STATIC_MODE = False

MODE_LABELS = {
    "PvP": "ラダー",
    "pathOfLegend": "ランク戦",
}

PERIOD_LABELS = {
    "all": "全期間",
    "7d": "過去7日",
    "30d": "過去30日",
    "90d": "過去90日",
}


def get_conn():
    """リクエストごとにDB接続を開く。"""
    return repo.connect()


def parse_battle_time(value):
    """APIの日時文字列をdatetimeへ変換する。"""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S.000Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@app.template_filter("jst")
def to_jst(value):
    """UTCの日時文字列をJST表記へ変換する。"""
    dt = parse_battle_time(value)
    if dt is None:
        return value or ""
    return (dt + timedelta(hours=9)).strftime("%m/%d %H:%M")


@app.template_filter("pct")
def to_percent(value, digits=1):
    """0〜1の割合をパーセント表記にする。"""
    if value is None:
        return "--"
    return f"{value * 100:.{digits}f}%"


@app.template_filter("signed")
def to_signed(value, digits=1):
    """符号付きのパーセント表記にする。"""
    if value is None:
        return "--"
    return f"{value * 100:+.{digits}f}"


def collection_status(conn, player_tag=None):
    """最終収集の状況を返す。ヘッダに常時表示する。"""
    row = repo.latest_collection(conn, player_tag)
    if row is None:
        return {"state": "none", "message": "収集履歴がありません"}

    run_at = datetime.strptime(row["run_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    minutes = int((datetime.now(timezone.utc) - run_at).total_seconds() // 60)
    if minutes < 60:
        ago = f"{minutes}分前"
    elif minutes < 60 * 24:
        ago = f"{minutes // 60}時間前"
    else:
        ago = f"{minutes // (60 * 24)}日前"

    return {
        "state": row["status"],
        "ago": ago,
        # 静的サイトでは書き出し時刻のまま固定されてしまうため、
        # 絶対時刻も渡してブラウザ側で経過時間を計算し直す。
        "run_at": run_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "warning": row["warning"],
        "error": row["error_message"],
        "message": row["error_message"] or row["warning"] or "正常",
    }


def base_context(conn, filters):
    """全画面共通のコンテキストを組み立てる。"""
    player = repo.get_player(conn, filters.player_tag)
    ctx = {
        "filters": filters,
        "query": filters.to_query_string(),
        "period_labels": PERIOD_LABELS,
        "mode_labels": MODE_LABELS,
        # デッキ一覧・収集状況は、表示中のプレイヤーのものに限る。
        "deck_groups": decks_analysis.list_deck_groups(conn, filters.player_tag),
        "status": collection_status(conn, filters.player_tag),
        "players": repo.list_players(conn),
        "player_name": player["name"] if player else None,
        "player_tag": filters.player_tag or "",
        "trophies": player["trophies"] if player else None,
        "min_matches": config.min_matches,
        # active はプレイヤー切替や絞り込みの遷移先を組み立てるために使う。
        # nav_active はタブの強調にだけ使う。詳細ページはどのタブにも
        # 属さないため None のままにし、誤ったタブを光らせない。
        "nav_active": None,
    }
    ctx.update(urlmod.helpers(filters, STATIC_MODE))
    return ctx


def screen(route, name, template):
    """画面用のルートを定義するデコレータ。

    6つの画面はいずれも「接続 → 絞り込みの解釈 → 共通コンテキスト →
    描画 → 接続の後始末」という同じ流れを持つ。その定型をここへ集約し、
    各画面には固有の集計だけを書けるようにする。

    装飾される関数は (conn, filters) を受け取り、テンプレートへ渡す
    追加のコンテキストを辞書で返す。
    """
    def decorator(view):
        @app.route(route, endpoint=view.__name__)
        @wraps(view)
        def wrapper():
            conn = get_conn()
            try:
                filters = Filters.from_request(request.args, repo.default_player_tag(conn))
                ctx = base_context(conn, filters)
                ctx["active"] = name
                ctx["nav_active"] = name
                ctx.update(view(conn, filters) or {})
                return render_template(template, **ctx)
            finally:
                conn.close()
        return wrapper
    return decorator


@app.route("/card-images/<path:filename>")
def card_image(filename):
    """ローカルに保存したカード画像を配信する。"""
    return send_from_directory(CARD_WEB_DIR, filename)


@screen("/", "summary", "summary.html")
def summary(conn, filters):
    """画面1: サマリー。"""
    unit = request.args.get("unit", "day")
    return {
        "overall": stats_analysis.overall(conn, filters, config),
        "unit": unit,
        "win_trend": trends_analysis.win_rate_trend(conn, filters, config, unit),
        "trophy_trend": trends_analysis.trophy_trend(conn, filters),
        "recent": trends_analysis.recent_matches(conn, filters, limit=10),
    }


@screen("/cards", "cards", "cards.html")
def weak_cards(conn, filters):
    """画面2: 苦手・得意カード。"""
    overall = stats_analysis.overall(conn, filters, config)
    rows, total = cards_analysis.opponent_card_stats(conn, filters, config, overall["rate"])
    return {
        "overall": overall,
        "rows": rows,
        "total_matches": total,
        "supports": cards_analysis.support_card_stats(conn, filters, config, overall["rate"]),
    }


@screen("/meta", "meta", "meta.html")
def meta_view(conn, filters):
    """画面3: 環境（出現率順）。"""
    overall = stats_analysis.overall(conn, filters, config)
    rows, total = cards_analysis.opponent_card_stats(conn, filters, config, overall["rate"])
    rows.sort(key=lambda x: -x["appearance_rate"])
    return {"overall": overall, "rows": rows, "total_matches": total}


@screen("/decks", "decks", "decks.html")
def deck_view(conn, filters):
    """画面4: 自デッキ別成績。"""
    return {
        "overall": stats_analysis.overall(conn, filters, config),
        "rows": decks_analysis.deck_group_stats(conn, filters, config),
        "config_threshold": config.similarity_threshold,
    }


@screen("/levels", "levels", "levels.html")
def level_view(conn, filters):
    """画面5: カードレベル分析。"""
    return {
        "overall": stats_analysis.overall(conn, filters, config),
        "buckets": levels_analysis.level_diff_stats(conn, filters, config),
        "summary": levels_analysis.level_summary(conn, filters),
        "correlation": levels_analysis.level_correlation(conn, filters),
        "bucket_step": config.level_bucket_step,
        "fit": levels_analysis.level_logistic_fit(conn, filters),
    }


@screen("/history", "history", "history.html")
def history_view(conn, filters):
    """画面6: 対戦履歴。"""
    page = max(1, int(request.args.get("page", 1)))
    # 静的サイトではページ数が組み合わせ分だけ増えるため、直近分のみを1ページに出す。
    per_page = config.publish_history_limit if STATIC_MODE else 25
    total = trends_analysis.match_count(conn, filters)
    return {
        "matches": trends_analysis.recent_matches(
            conn, filters, limit=per_page, offset=(page - 1) * per_page),
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@app.route("/match/<int:match_id>")
def match_view(match_id):
    """1試合の詳細。絞り込みに依存しないため @screen は使わない。"""
    conn = get_conn()
    try:
        detail = detail_analysis.match_detail(conn, match_id)
        if detail is None:
            abort(404)

        # 詳細ページは絞り込みを持たないが、ヘッダとナビは共通のものを使う。
        # 対戦した本人を選んだ状態の絞り込みを組み立てて渡す。
        filters = Filters(player_tag=detail["player_tag"])
        ctx = base_context(conn, filters)
        ctx.update({"active": "history", "nav_active": "history", "detail": detail})
        return render_template("match.html", **ctx)
    finally:
        conn.close()


@app.route("/card/<int:card_id>")
def card_view(card_id):
    """カード1枚の性能値。絞り込みに依存しないため @screen は使わない。"""
    conn = get_conn()
    try:
        detail = cardstats_analysis.card_detail(conn, card_id)
        if detail is None:
            abort(404)

        # 詳細ページ自体は絞り込みを持たないが、ヘッダとナビは共通のものを使う。
        filters = Filters(player_tag=repo.default_player_tag(conn))
        ctx = base_context(conn, filters)
        ctx.update({"active": "cards", "detail": detail})  # nav_active は None のまま
        return render_template("card.html", **ctx)
    finally:
        conn.close()


def find_port_owner(host, port):
    """指定ポートを待ち受けているプロセス名を返す。特定できなければ None。"""
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen "
             f"-ErrorAction SilentlyContinue | Select-Object -First 1; "
             f"if ($c) {{ (Get-Process -Id $c.OwningProcess).ProcessName }}"],
            capture_output=True, text=True, timeout=10)
        name = (result.stdout or "").strip()
        return name or None
    except Exception:
        return None


def is_port_free(host, port):
    """ポートが使用可能かを調べる。

    Windowsでは host と 0.0.0.0 への二重バインドが通ってしまう場合があり、
    起動できてもブラウザからは別のアプリに繋がることがある。そのため
    ワイルドカードでの待ち受けも含めて確認する。
    """
    import socket
    for target in (host, "0.0.0.0"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # 既に待ち受けているプロセスがあれば接続が成功する。
            s.settimeout(0.3)
            probe = "127.0.0.1" if target == "0.0.0.0" else target
            if s.connect_ex((probe, port)) == 0:
                return False
        finally:
            s.close()
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="対戦分析ダッシュボード")
    parser.add_argument("--port", type=int, default=config.web_port,
                        help=f"待ち受けポート（既定 {config.web_port}）")
    parser.add_argument("--host", default=config.web_host,
                        help=f"待ち受けホスト（既定 {config.web_host}）")
    args = parser.parse_args()

    if not is_port_free(args.host, args.port):
        owner = find_port_owner(args.host, args.port)
        print(f"ポート {args.port} は既に使用されています"
              + (f"（{owner}）" if owner else ""))
        print()
        print("対処のいずれかを選んでください:")
        print(f"  1. 別のポートで起動する   python -m src.web.app --port 8731")
        print(f"  2. 恒久的に変更する       config.yaml の web.port を書き換える")
        print(f"  3. 使用中のアプリを止める")
        return 1

    print(f"ダッシュボードを起動します: http://{args.host}:{args.port}")
    print("停止するには Ctrl+C を押してください。")
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
