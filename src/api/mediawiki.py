# -*- coding: utf-8 -*-
"""MediaWiki のAPIを呼ぶための共通処理。

このツールは、公式APIが返さない情報を2つのwikiから補っている。

  - Clash Royale Wiki（Fandom） … カードの性能値、レベルアップに必要な量
  - Liquipedia                  … マスタリーのタスクセット数

どちらも MediaWiki のAPIで、問い合わせの形（action=query で wikitext を引く）も
同じため、HTTPの呼び出しと応答の取り出しだけをここにまとめる。何をどう読み取るかは
それぞれの取得モジュール（cardstats / upgrades / mastery）に残す。

Liquipedia は利用規約で gzip 応答の受け取りを求めているため、常に gzip を許可して
受け取り、必要なら展開する。相手を名乗る User-Agent も、呼び出し側から必ず渡す。
"""
import gzip
import json
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 40


def get_json(api, params, user_agent, timeout=DEFAULT_TIMEOUT):
    """APIを呼び、応答のJSONを辞書で返す。"""
    url = api + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
    return json.loads(data)


def query_pages(api, titles, user_agent, timeout=DEFAULT_TIMEOUT, **extra):
    """複数ページの wikitext をまとめて引く。

    extra には、問い合わせごとに違う項目（formatversion、redirects など）を渡す。
    戻り値は API の query 部分そのもので、取り出し方は呼び出し側に任せる。
    """
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content|ids",
        "rvslots": "main",
        "format": "json",
        "titles": "|".join(titles),
    }
    params.update(extra)
    return get_json(api, params, user_agent, timeout)["query"]


def page_content(page):
    """ページ1件分の応答から (wikitext, 版ID) を取り出す。無ければ (None, None)。"""
    revisions = (page or {}).get("revisions") or []
    if not revisions:
        return None, None
    revision = revisions[0]
    return revision["slots"]["main"]["content"], revision.get("revid")
