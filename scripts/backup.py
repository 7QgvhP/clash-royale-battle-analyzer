# -*- coding: utf-8 -*-
"""データベースのバックアップ。

対戦履歴はAPIから再取得できないため、失うと復旧できない。
定期的に実行することを推奨する。
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import DB_PATH  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKUP_DIR = ROOT / "data" / "backups"


def backup(keep=10):
    """DBをバックアップし、古いものを整理する。"""
    if not DB_PATH.exists():
        print(f"データベースがありません: {DB_PATH}")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"battles_{stamp}.db"

    # sqlite3のバックアップAPIを使う。収集中でも安全にコピーできる。
    source = sqlite3.connect(str(DB_PATH))
    target = sqlite3.connect(str(dest))
    try:
        with target:
            source.backup(target)
    finally:
        source.close()
        target.close()

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"バックアップを作成しました: {dest.name}（{size_mb:.2f} MB）")

    # 古いバックアップを削除する
    backups = sorted(BACKUP_DIR.glob("battles_*.db"))
    removed = 0
    while len(backups) > keep:
        oldest = backups.pop(0)
        oldest.unlink()
        removed += 1
    if removed:
        print(f"古いバックアップを削除しました: {removed}件（最新{keep}件を保持）")
    return 0


def main():
    parser = argparse.ArgumentParser(description="対戦履歴DBのバックアップ")
    parser.add_argument("--keep", type=int, default=10, help="保持する世代数（既定10）")
    args = parser.parse_args()
    return backup(args.keep)


if __name__ == "__main__":
    sys.exit(main())
