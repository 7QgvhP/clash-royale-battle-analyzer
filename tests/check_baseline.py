# -*- coding: utf-8 -*-
"""集計値がリファクタ前後で変わっていないことを確認する。

このプロジェクトには自動テストが無く、分析ロジックを触ると数値が
静かに変わる危険がある。tests/baseline.json と突き合わせて検出する。

    python -m tests.check_baseline          # 比較する
    python -m tests.check_baseline --update # 基準値を更新する
"""
import argparse
import json
import sys
from pathlib import Path

from src.analysis import cards, decks, levels, stats, trends
from src.analysis.filters import Filters
from src.config import get_config
from src.db import repository as repo

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"

PERIODS = ["all", "7d", "30d"]
MODES = [None, "PvP"]


def snapshot():
    """現在のコードで全組み合わせの集計値を求める。"""
    config = get_config()
    conn = repo.connect()
    try:
        result = {}
        for player in repo.list_players(conn):
            tag = player["player_tag"]
            for period in PERIODS:
                for mode in MODES:
                    f = Filters(period=period, modes=[mode] if mode else [], player_tag=tag)
                    overall = stats.overall(conn, f, config)
                    rows, total = cards.opponent_card_stats(conn, f, config, overall["rate"])
                    result[f"{tag}_{period}_{mode}"] = {
                        "overall": {k: overall[k] for k in
                                    ("wins", "losses", "draws", "rate", "margin", "reliable")},
                        "total_matches": total,
                        "cards": [[r["card_id"], r["total"], r["rate"], r["delta"],
                                   r["appearance_rate"]] for r in rows],
                        "decks": [[d["group_id"], d["total"], d["rate"], d["avg_level"]]
                                  for d in decks.deck_group_stats(conn, f, config)],
                        "levels": [[b["key"], b["total"], b["rate"]]
                                   for b in levels.level_diff_stats(conn, f, config)],
                        "trend": [[t["bucket"], t["wins"], t["losses"]]
                                  for t in trends.win_rate_trend(conn, f, config)],
                    }
        return result
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="集計値の回帰確認")
    parser.add_argument("--update", action="store_true", help="基準値を現在の値で上書きする")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    current = snapshot()

    if args.update or not BASELINE_PATH.exists():
        # 改行はLFで固定する。既定のままだとWindowsでCRLFになり、
        # 中身が同じでも差分が全行（約1万行）になってしまう。
        BASELINE_PATH.write_text(
            json.dumps(current, ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8", newline="\n")
        print(f"基準値を保存しました: {len(current)}組")
        return 0

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    # 対戦が増えていると当然値は変わる。比較できるのは基準値作成時と
    # 同じ対戦数のときだけなので、その旨を明示する。
    diffs = []
    for key in sorted(set(baseline) | set(current)):
        if key not in baseline:
            diffs.append(f"  [新規] {key}")
        elif key not in current:
            diffs.append(f"  [消失] {key}")
        elif baseline[key] != current[key]:
            for field in baseline[key]:
                if baseline[key][field] != current[key].get(field):
                    diffs.append(f"  [差異] {key} -> {field}")

    if not diffs:
        print(f"一致しました: {len(current)}組すべての集計値が基準値と同じです")
        return 0

    print(f"差異が {len(diffs)} 件あります:")
    for d in diffs[:40]:
        print(d)
    if len(diffs) > 40:
        print(f"  ... 他 {len(diffs) - 40} 件")
    print()
    print("収集によって対戦数が増えた場合も差異として出ます。")
    print("意図した変更であれば --update で基準値を更新してください。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
