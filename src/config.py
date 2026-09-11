# -*- coding: utf-8 -*-
"""設定の読み込み。

秘密情報は .env から、動作パラメータは config.yaml から読み込む。
"""
from pathlib import Path

import yaml
from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "battles.db"
LOG_DIR = DATA_DIR / "logs"
CARD_IMAGE_DIR = DATA_DIR / "card_images"
# 表示サイズに合わせて縮小・WebP化したもの。実際の配信にはこちらを使う。
CARD_WEB_DIR = DATA_DIR / "card_images_web"
CARD_NAMES_PATH = ROOT / "src" / "data" / "card_names_ja.json"

PROXY_BASE = "https://proxy.royaleapi.dev/v1"
DIRECT_BASE = "https://api.clashroyale.com/v1"
PROXY_IP = "45.79.218.79"

# Cloudflareが既定のUser-Agentを遮断するため、クライアントを明示する。
# 詳細は docs/requirements.md の 2.4 を参照。
USER_AGENT = "clash-royale-battle-analyzer/1.0.0"


class ConfigError(Exception):
    """設定の不備を表す例外。"""


class Config:
    """.env と config.yaml をまとめて保持する。

    .env の解析は scripts/doctor.py にも独自実装がある（依存パッケージの
    導入前に診断できるようにするため）。項目を追加した場合は両方に反映すること。
    """

    def __init__(self):
        load_dotenv(ENV_PATH, encoding="utf-8-sig")

        self.token = (os.getenv("CR_API_TOKEN") or "").strip()
        raw_tag = (os.getenv("CR_PLAYER_TAG") or "").strip()
        self.player_tag = "#" + raw_tag.lstrip("#").upper()
        self.use_proxy = (os.getenv("CR_USE_PROXY") or "true").strip().lower() != "false"
        self.base_url = PROXY_BASE if self.use_proxy else DIRECT_BASE

        with CONFIG_PATH.open(encoding="utf-8") as f:
            self.raw = yaml.safe_load(f) or {}

        analysis = self.raw.get("analysis", {})
        self.min_matches = int(analysis.get("min_matches", 20))
        self.z_score = float(analysis.get("z_score", 1.96))
        self.exclude_draws = bool(analysis.get("exclude_draws", True))
        self.level_bucket_step = float(analysis.get("level_bucket_step", 0.25))
        self.level_trend_window = float(analysis.get("level_trend_window", 0.5))
        self.target_battle_types = list(analysis.get("target_battle_types", ["PvP", "pathOfLegend"]))
        self.target_deck_selections = list(analysis.get("target_deck_selections", ["collection"]))

        grouping = self.raw.get("deck_grouping", {})
        self.similarity_threshold = int(grouping.get("similarity_threshold", 6))

        collector = self.raw.get("collector", {})
        self.max_retries = int(collector.get("max_retries", 3))
        self.backoff_seconds = float(collector.get("backoff_seconds", 2))
        self.timeout_seconds = float(collector.get("timeout_seconds", 20))

        publish = self.raw.get("publish", {})
        self.publish_enabled = bool(publish.get("enabled", False))
        self.publish_project = str(publish.get("project_name", "") or "")
        self.publish_history_limit = int(publish.get("history_limit", 100))

        web = self.raw.get("web", {})
        self.web_host = str(web.get("host", "127.0.0.1"))
        self.web_port = int(web.get("port", 5000))

    def validate(self):
        """必須項目の妥当性を検証する。問題があれば ConfigError を送出する。"""
        if not self.token:
            raise ConfigError("CR_API_TOKEN が未設定です。.env を確認してください。")
        if len(self.token) < 100:
            raise ConfigError("CR_API_TOKEN が短すぎます。コピー漏れの可能性があります。")

        body = self.player_tag.lstrip("#")
        if not body:
            raise ConfigError("CR_PLAYER_TAG が未設定です。.env を確認してください。")
        invalid = set(body) - set("0289PYLQGRJCUV")
        if invalid:
            hint = ""
            if "O" in invalid:
                hint = " 'O'（オー）は使われません。'0'（ゼロ）の誤りと思われます。"
            raise ConfigError(
                f"CR_PLAYER_TAG に使われない文字が含まれます: {', '.join(sorted(invalid))}.{hint}"
            )

    def ensure_directories(self):
        """データ出力先のディレクトリを用意する。"""
        for d in (DATA_DIR, LOG_DIR, CARD_IMAGE_DIR, CARD_WEB_DIR):
            d.mkdir(parents=True, exist_ok=True)


_config = None


def get_config():
    """設定のシングルトンを返す。"""
    global _config
    if _config is None:
        _config = Config()
    return _config
