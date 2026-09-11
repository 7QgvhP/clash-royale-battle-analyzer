# -*- coding: utf-8 -*-
"""クラッシュロワイヤル公式APIのクライアント。

RoyaleAPIのプロキシ経由と直接アクセスの双方に対応し、
一過性の失敗に対しては指数バックオフで再試行する。
"""
import time
import urllib.parse

import requests

from src.config import USER_AGENT, get_config


class ApiError(Exception):
    """APIアクセスの失敗を表す例外。

    retryable が True の場合、時間をおいた再試行で回復しうる。
    """

    def __init__(self, message, status=None, reason=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.retryable = retryable


class ClashRoyaleClient:
    """公式APIへのリクエストを担う。"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": "Bearer " + self.config.token,
            "Accept": "application/json",
            # 未設定だとCloudflareに遮断される。必須。
            "User-Agent": USER_AGENT,
        })

    def _describe_error(self, response):
        """エラーレスポンスから ApiError を組み立てる。"""
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = {}

        reason = body.get("reason") or body.get("error_name") or ""

        if status == 403 and body.get("error_code") == 1010:
            return ApiError(
                "User-Agentがプロキシに遮断されました。リクエストヘッダの設定を確認してください。",
                status, reason, retryable=False)
        if status == 403 and "invalidip" in reason.lower().replace(".", ""):
            return ApiError(
                "APIキーの許可IPが一致しません。プロキシ経由の場合、トークンには "
                "45.79.218.79 を登録してください。",
                status, reason, retryable=False)
        if status == 403:
            return ApiError("APIトークンが無効です。.env の設定を確認してください。",
                            status, reason, retryable=False)
        if status == 404:
            return ApiError("対象が見つかりません。プレイヤータグを確認してください。"
                            "（'O' と '0' の取り違えに注意）",
                            status, reason, retryable=False)
        if status == 429:
            return ApiError("APIのレート制限に達しました。", status, reason, retryable=True)
        if status >= 500:
            return ApiError(f"APIサーバー側のエラーです（HTTP {status}）。",
                            status, reason, retryable=True)
        return ApiError(f"想定外の応答です（HTTP {status}）。", status, reason, retryable=False)

    def get(self, path):
        """GETリクエストを送り、JSONを返す。再試行は指数バックオフで行う。"""
        url = self.config.base_url + path
        last_error = None

        for attempt in range(self.config.max_retries):
            try:
                response = self.session.get(url, timeout=self.config.timeout_seconds)
            except requests.RequestException as e:
                last_error = ApiError(f"通信に失敗しました: {e}", retryable=True)
            else:
                if response.status_code == 200:
                    return response.json()
                last_error = self._describe_error(response)

            if not last_error.retryable:
                raise last_error
            if attempt < self.config.max_retries - 1:
                time.sleep(self.config.backoff_seconds * (2 ** attempt))

        raise last_error

    @staticmethod
    def _encode_tag(tag):
        """プレイヤータグをURL用にエンコードする（# は %23 になる）。"""
        return urllib.parse.quote("#" + tag.lstrip("#").upper())

    def get_player(self, tag):
        """プレイヤーのプロフィールを取得する。"""
        return self.get(f"/players/{self._encode_tag(tag)}")

    def get_battlelog(self, tag):
        """直近のバトルログを取得する。"""
        return self.get(f"/players/{self._encode_tag(tag)}/battlelog")

    def get_cards(self):
        """カードマスタを取得する。通常カードとタワートループを分けて返す。"""
        data = self.get("/cards")
        return data.get("items", []), data.get("supportItems", [])

    def download(self, url):
        """画像などのバイナリを取得する。認証ヘッダは不要。"""
        response = requests.get(url, timeout=self.config.timeout_seconds,
                                headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.content
