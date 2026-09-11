# -*- coding: utf-8 -*-
"""収集から公開までを一括で行う。

タスクスケジューラからはこのコマンドを呼ぶ。

    収集 → 静的サイトの書き出し → アップロード

アップロードは Cloudflare Pages の wrangler を使う。未設定の場合は
書き出しまでを行い、アップロードは省略する。
"""
import argparse
import logging
import subprocess
import sys

from src.api.client import ApiError, ClashRoyaleClient
from src.collector import collect as collector
from src.config import ROOT, get_config
from src.db import repository as repo
from src.exporter import static_export


def upload(project_name, dist_dir):
    """wrangler で Cloudflare Pages へアップロードする。"""
    # npx 経由で呼ぶことで、wrangler の事前インストールを不要にする。
    command = [
        "npx", "--yes", "wrangler@latest", "pages", "deploy", str(dist_dir),
        "--project-name", project_name, "--commit-dirty=true",
    ]
    logging.info("アップロードを開始します: %s", project_name)
    result = subprocess.run(command, cwd=str(ROOT), shell=True,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=900)
    output = (result.stdout or "") + (result.stderr or "")
    for line in output.splitlines():
        if line.strip():
            logging.info("  %s", line.rstrip())

    if result.returncode != 0:
        raise RuntimeError(f"アップロードに失敗しました（終了コード {result.returncode}）")
    logging.info("アップロード完了")


def main(argv=None):
    parser = argparse.ArgumentParser(description="収集から公開まで一括実行")
    parser.add_argument("--skip-collect", action="store_true", help="収集を行わない")
    parser.add_argument("--skip-upload", action="store_true", help="アップロードを行わない")
    parser.add_argument("--verbose", action="store_true", help="詳細なログを出力する")
    args = parser.parse_args(argv)

    collector.setup_logging(args.verbose)
    config = get_config()

    try:
        config.validate()
    except Exception as e:
        logging.error("設定に問題があります: %s", e)
        return 1

    config.ensure_directories()
    conn = repo.connect()
    repo.init_schema(conn)

    try:
        if not args.skip_collect:
            client = ClashRoyaleClient(config)
            collector.collect_battles(conn, client, config)
            repo.recount_decks(conn)
            collector.regroup(conn, config)

        dist_dir = static_export.export(conn)
        if dist_dir is None:
            return 1

        if args.skip_upload:
            logging.info("アップロードは省略しました。")
            return 0

        project = config.publish_project
        if not config.publish_enabled or not project:
            logging.info("公開設定が無効です。書き出しのみ行いました: %s", dist_dir)
            logging.info("公開する場合は config.yaml の publish.enabled と project_name を設定してください。")
            return 0

        # 秘密ディレクトリを含む dist 全体を上げる。URLは
        # https://<project>.pages.dev/<secret>/ になる。
        upload(project, static_export.DIST_DIR)
        secret = repo.get_meta(conn, "static_secret")
        logging.info("公開URL: https://%s.pages.dev/%s/", project, secret)
        return 0

    except ApiError as e:
        logging.error("APIエラー: %s", e)
        return 1
    except Exception as e:
        logging.exception("公開処理に失敗しました: %s", e)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
