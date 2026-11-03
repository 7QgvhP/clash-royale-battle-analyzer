# -*- coding: utf-8 -*-
"""カードマスタリー（ゲーム内の「カードタスク」）のタスクセット数を Liquipedia から取得する。

公式APIはマスタリーのバッジに `maxLevel: 10` を一律で返すが、実際の上限はカードごとに
違う。Supercell の告知にあるとおり「すべてのカードが3セットを持つわけではない」ためで、
2セット（6タスク）しかないカードは、段階7で打ち止めになる。公式APIからはこの区別が
付かず、打ち止めのカードも「7/10」に見えてしまう。

  段階（level） ＝ 完了したタスク数 + 1（最初の「3勝する」の分）
  上限          ＝ タスクセット数 × 3 + 1

カードごとのタスクセットを表にして公開しているのは Liquipedia で、
`Template:Card Mastery/<英語名>` に1カード分の表が入っている。セットごとに
「colspan=3」の見出し行（Damage Dealer など）があるため、その数を数える。

Liquipedia のAPI利用規約（https://liquipedia.net/api-terms-of-use）に従い、
  - 用途と連絡先を名乗る User-Agent を付ける
  - gzip の応答を受け取れるようにする
  - リクエストは2秒に1回まで（action=parse は使わない）
を守る。内容は CC BY-SA 3.0 のため、画面に出典を表示すること。
"""
import logging
import re
import time

from src.api import mediawiki

API = "https://liquipedia.net/clashroyale/api.php"
PAGE_URL = "https://liquipedia.net/clashroyale/Card_Mastery"
SOURCE_NAME = "Liquipedia"
LICENSE = "CC BY-SA 3.0"

# 規約で求められている、用途と連絡先が分かる User-Agent
USER_AGENT = ("clash-royale-battle-analyzer/1.0 "
              "(https://github.com/7QgvhP/clash-royale-battle-analyzer)")
REQUEST_INTERVAL = 2.5      # 規約は「2秒に1回まで」。少し余裕を持たせる
BATCH_SIZE = 40             # 1リクエストで問い合わせるカード数
TIMEOUT = 40

# 1セットあたりのタスク数と、最初の「3勝する」の分
TASKS_PER_SET = 3
UNLOCK_STEPS = 1

# 公式APIの英語名と、Liquipedia のページ名が違うもの
TITLE_ALIASES = {
    "P.E.K.K.A": "P.E.K.K.A.",
    "Mini P.E.K.K.A": "Mini P.E.K.K.A.",
}


def _request(titles):
    """複数ページの wikitext をまとめて取得する。"""
    return mediawiki.query_pages(API, titles, USER_AGENT, TIMEOUT, formatversion=2)["pages"]


def _count_sets(text):
    """表の中のタスクセットの数を数える。セットごとに見出し行が1つある。"""
    return len(re.findall(r"colspan=3\s*\|([^\n|]+)", text))


def fetch_task_sets(name_list):
    """英語名の一覧に対して、{英語名: タスクセット数} を返す。

    ページが無いカード（新しすぎて未掲載など）は辞書に入れない。呼び出し側で
    「不明」として扱い、公式APIの値をそのまま使う。
    """
    out, missing = {}, []
    titles = {}
    for name in name_list:
        titles[f"Template:Card Mastery/{TITLE_ALIASES.get(name, name)}"] = name

    keys = list(titles)
    for start in range(0, len(keys), BATCH_SIZE):
        if start:
            time.sleep(REQUEST_INTERVAL)
        for page in _request(keys[start:start + BATCH_SIZE]):
            name = titles.get(page["title"])
            if name is None:
                continue
            text, _revid = mediawiki.page_content(page)
            sets = _count_sets(text) if text else 0
            if sets:
                out[name] = sets
            else:
                missing.append(name)

    if missing:
        logging.warning("マスタリーのタスク数を取得できなかったカード: %s", "、".join(missing))
    return out


def max_level(task_sets):
    """タスクセット数から、マスタリーの段階の上限を求める。"""
    return task_sets * TASKS_PER_SET + UNLOCK_STEPS


def fetch_mastery_caps(name_list):
    """{英語名: 段階の上限} と出典をまとめて返す。取得できなければ None。"""
    sets = fetch_task_sets(name_list)
    if not sets:
        return None
    return {
        "caps": {name: max_level(count) for name, count in sets.items()},
        "task_sets": sets,
        "source": {"name": SOURCE_NAME, "license": LICENSE, "url": PAGE_URL},
    }
