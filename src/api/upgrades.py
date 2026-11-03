# -*- coding: utf-8 -*-
"""カードのレベルアップに必要な枚数・ゴールドを Clash Royale Wiki から取得する。

公式APIは所持枚数（count）と現在のレベルは返すが、「次のレベルに上げるのに
何枚必要か」は返さない。この値はゲーム側の固定データのため、性能値と同じく
Clash Royale Wiki（CC BY-SA）の「Cards」ページを情報源とする。

ページには、レアリティ別・レベル別の表が2つ並んでいる。

  - Number of Cards Required for Upgrade … 必要枚数
  - Gold Required for Upgrade            … 必要ゴールド

いずれも「その行のレベルに**到達する**ために要る量」である。レアリティの開始
レベル（コモン1・レア3・エピック6・レジェンダリー9・チャンピオン12）の行には
カード1枚だけが入っており、これはカード自体を手に入れるための1枚を指す。
したがって「次のレベルに必要な量」は、現在のレベル+1 の行を読めばよい。
"""
import json
import re
import urllib.parse
import urllib.request

from src.api.cardstats import API, LICENSE, PAGE_URL, SOURCE_NAME, TIMEOUT, USER_AGENT

# 表を載せているページ
PAGE_TITLE = "Cards"

# wikitext 側の表の区切り。<section begin="Upgrade" cards=""/> のように囲われている。
SECTIONS = {"cards": "Number of Cards Required for Upgrade",
            "gold": "Gold Required for Upgrade"}

# 表の列の並び（見出しの {{Rarity|...}} と同じ順）
RARITIES = ["common", "rare", "epic", "legendary", "champion"]


def _wikitext(title):
    """ページの wikitext を取得する。"""
    url = API + "?" + urllib.parse.urlencode({
        "action": "query", "prop": "revisions", "rvprop": "content|ids",
        "rvslots": "main", "titles": title, "format": "json", "formatversion": 2})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        page = json.load(response)["query"]["pages"][0]
    revisions = page.get("revisions") or []
    if not revisions:
        return None, None
    return revisions[0]["slots"]["main"]["content"], revisions[0].get("revid")


def _parse_table(text, heading):
    """見出しに続く表を {レアリティ: {レベル: 値}} として読み取る。

    行は「|レベル||コモン||レア||…」の形。改行で列を分ける書き方も混在するため、
    どちらでも読めるように、行全体からセルを取り出してから組み立てる。
    """
    start = text.find(heading)
    if start < 0:
        return None
    end = text.find("|}", start)
    if end < 0:
        return None

    out = {r: {} for r in RARITIES}
    for row in text[start:end].split("|-"):
        # セルは || 区切り、または行頭の | で1つずつ書かれる
        cells = [c.strip() for c in re.split(r"\|\||\n\s*\|", row) if c.strip()]
        cells = [re.sub(r"^\|", "", c).strip() for c in cells]
        if len(cells) < len(RARITIES) + 1:
            continue
        if not cells[0].isdigit():       # 合計の行など
            continue
        level = int(cells[0])
        for rarity, cell in zip(RARITIES, cells[1:len(RARITIES) + 1]):
            value = cell.replace(",", "").replace(" ", "")
            if value.isdigit():
                out[rarity][level] = int(value)
    return out if any(out.values()) else None


def fetch_upgrade_table():
    """必要枚数・必要ゴールドの表を返す。取得できなければ None。"""
    text, revid = _wikitext(PAGE_TITLE)
    if not text:
        return None

    tables = {}
    for key, heading in SECTIONS.items():
        parsed = _parse_table(text, heading)
        if parsed is None:
            return None
        tables[key] = parsed

    return {
        "cards": tables["cards"],
        "gold": tables["gold"],
        "source": {"name": SOURCE_NAME, "license": LICENSE, "page": PAGE_TITLE,
                   "url": PAGE_URL + PAGE_TITLE, "revid": revid},
    }
