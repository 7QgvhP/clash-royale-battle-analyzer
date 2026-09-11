# -*- coding: utf-8 -*-
"""カードの性能値を Clash Royale Wiki（Fandom）から取得する。

公式APIはカードの名前・レアリティ・コスト・画像しか返さず、HP・ダメージ・射程と
いった性能値を提供していない。ゲーム本体のファイルには入っているが、そこからの
抽出は Supercell の利用規約が禁じている（§1.1 "obtain any information from the
Service or any Supercell game using any method not expressly permitted"）。

そのため、内容が CC BY-SA で再利用を許諾されており、かつ公開されたMediaWiki APIで
取得できる Clash Royale Wiki を情報源とする。出典表示が義務なので、画面には必ず
取得元ページへのリンクと取得日を表示すること。

wikitext 上では性能値が2か所に分かれている。

  1. 属性テーブル（id="unit-attributes-table"）
     コスト・攻撃速度・射程・移動速度など、レベルで変わらない値。
     列の顔ぶれがカード種別ごとに違うため、列を決め打ちせずラベルごと取り出す。

  2. #vardefine 変数
     レベルで変わる値。レベル11を基準に格納されており、wiki側も
     「基準値 × 1.1^(レベル-11)」で各レベルを算出している。
     `golem_hp_11` のように接頭辞が付くものは、そのカードが出す別ユニットを指す。
"""
import json
import re
import time
import urllib.parse
import urllib.request

API = "https://clashroyale.fandom.com/api.php"
PAGE_URL = "https://clashroyale.fandom.com/wiki/"
LICENSE = "CC BY-SA"
SOURCE_NAME = "Clash Royale Wiki"

# MediaWikiが1リクエストで受け付けるページ数の上限
BATCH_SIZE = 50
# 連続リクエストの間隔（秒）。相手のサーバーに負荷をかけないための間合い。
REQUEST_INTERVAL = 0.5
TIMEOUT = 40

# 問い合わせ元を名乗る。匿名の大量アクセスと区別できるようにしておく。
USER_AGENT = ("clash-royale-battle-analyzer/1.0.0 "
              "(personal battle-log analysis tool)")

# 性能値の基準レベル。wikiがこのレベルの値を持っている。
BASE_LEVEL = 11
# レベルが1上がるごとの倍率。wikiの各レベル表と同じ式を使うことで、
# 出典として示すページの数値と表示が一致する。
LEVEL_FACTOR = 1.1

# レベルで変化する値の種類。接頭辞を除いた末尾で判別する。
SCALING_STATS = ("hp", "dmg", "crown_dmg", "death", "spawn", "charge",
                 "dash", "heal", "shield", "crown")


def _request(titles):
    """複数ページの wikitext をまとめて取得する。"""
    params = urllib.parse.urlencode({
        "action": "query",
        "prop": "revisions",
        "rvprop": "content|ids|timestamp",
        "rvslots": "main",
        "format": "json",
        "redirects": "1",
        "titles": "|".join(titles),
    })
    req = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return json.loads(response.read())["query"]


def fetch_pages(names):
    """カードの英語名からページ内容を引く。{英語名: (wikitext, revid)} を返す。

    リダイレクトと表記ゆれはAPI側が解決してくれるので、その対応表を使って
    問い合わせたときの名前に戻す。見つからなかったページは値が None になる。
    """
    pages = {}
    for i in range(0, len(names), BATCH_SIZE):
        chunk = names[i:i + BATCH_SIZE]
        data = _request(chunk)
        # 転送・正規化された分を、こちらが指定した名前へ戻すための対応表
        alias = {m["to"]: m["from"]
                 for key in ("redirects", "normalized")
                 for m in data.get(key, [])}
        for page in data["pages"].values():
            title = page.get("title")
            name = alias.get(title, title)
            if "revisions" not in page:
                pages[name] = (None, None)
            else:
                rev = page["revisions"][0]
                pages[name] = (rev["slots"]["main"]["*"], rev.get("revid"))
        if i + BATCH_SIZE < len(names):
            time.sleep(REQUEST_INTERVAL)
    return pages


def _clean(value):
    """wiki記法を取り除いて、表示できる文字列にする。"""
    # [[:Category:Troop Cards|Troop]] や [[Elixir|エリクサー]] はラベル側を残す
    value = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", value)
    value = re.sub(r"\[\[([^\]]*)\]\]", r"\1", value)

    def template(match):
        """{{Rarity|Common}} は中身を残し、{{Icon|I=Elixir}} は丸ごと捨てる。

        名前付き引数（I=... のような形）を取るものは装飾目的のテンプレートで、
        表示したい値を持たない。位置引数だけのものは最後の引数が中身にあたる。
        """
        args = match.group(1).split("|")[1:]
        if not args or any("=" in a for a in args):
            return ""
        return args[-1]

    value = re.sub(r"\{\{([^{}]*)\}\}", template, value)
    # 入れ子になっていて上で処理しきれなかったものは落とす
    value = re.sub(r"\{\{[^}]*\}\}", "", value)
    value = re.sub(r"<br\s*/?>", " ", value)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).replace("'''", "").strip()


def parse_attributes(wikitext):
    """属性テーブルを [(ラベル, 値)] として取り出す。

    列の構成がカード種別ごとに違うため、ヘッダ行の見出しとデータ行の値を
    順番どおりに突き合わせる。wikiに列が増えてもそのまま通る。
    """
    # class と id の記述順はページによって前後するため、順序を問わずに探す
    table = re.search(r'\{\|[^\n]*id="unit-attributes-table"[^\n]*\n.*?\n\|\}',
                      wikitext, re.S)
    if not table:
        return []

    labels, values, in_body = [], [], False
    for line in table.group(0).splitlines()[1:]:
        line = line.strip()
        if line.startswith("|-"):
            in_body = True
            continue
        if line.startswith("|}"):
            break
        if line.startswith("!") and not in_body:
            # 「!scope="col"|Cost<br>{{Icon}}」「! scope="col" |Cost」「!Cost」を吸収する
            cell = line.lstrip("!")
            cell = re.sub(r'^\s*scope\s*=\s*"col"\s*', "", cell).lstrip("|")
            labels.append(_clean(cell))
        elif in_body and line.startswith("|"):
            values.extend(_clean(v) for v in line[1:].split("||"))
        elif in_body and line.startswith("{{"):
            # ヘッダのアイコンが次行に置かれている場合があり、値ではない
            continue

    # 見出しだけで中身が無い列は落とす
    return [(lab, val) for lab, val in zip(labels, values) if lab and val]


def parse_variables(wikitext):
    """#vardefine の数値を {変数名: 値} として取り出す。"""
    found = re.findall(
        r"\{\{#vardefine:\s*([A-Za-z0-9_]+)\s*\|\s*([0-9]+(?:\.[0-9]+)?)\s*\}\}",
        wikitext)
    out = {}
    for name, value in found:
        # Shield_11 のように大文字で書かれている箇所があるため揃える
        out[name.lower()] = float(value)
    return out


def _split_prefix(name):
    """変数名を（接頭辞, 種類）に割る。接頭辞はそのカードが出す別ユニットを指す。

    hp_11 -> ("", "hp") / golem_hp_11 -> ("golem", "hp")
    hp_base も基準はレベル11なので hp と同じ扱いにする。
    """
    stem = re.sub(r"_(?:11|base)$", "", name).rstrip("_")
    for stat in sorted(SCALING_STATS, key=len, reverse=True):
        if stem == stat:
            return "", stat
        if stem.endswith("_" + stat):
            return stem[:-(len(stat) + 1)].rstrip("_"), stat
    return None, None


def build_units(variables):
    """変数をユニット単位にまとめる。先頭が本体、以降がそのカードが出すユニット。"""
    units = {}
    for name, value in variables.items():
        if name.endswith(("_11", "_base")):
            prefix, stat = _split_prefix(name)
            if stat is None:
                continue
            units.setdefault(prefix, {})[stat] = value

    # 攻撃速度はレベルで変わらないため別枠。接頭辞の付き方は変数側に合わせる。
    for name, value in variables.items():
        if name.endswith("atk_speed"):
            prefix = name[:-len("atk_speed")].rstrip("_")
            units.setdefault(prefix, {})["atk_speed"] = value

    # HPもダメージも無いものはユニットではない。たとえば攻撃段階ごとの速度
    # （1_atk_speed / 2_atk_speed）が該当するため、ユニットとして並べない。
    ordered, leftovers = [], {}
    for prefix in sorted(units, key=lambda p: (p != "", p)):
        unit = units[prefix]
        if "hp" not in unit and "dmg" not in unit:
            leftovers.update({f"{prefix}_{k}" if prefix else k: v
                              for k, v in unit.items()})
            continue
        unit = dict(unit)
        unit["prefix"] = prefix or None
        ordered.append(unit)
    return ordered, leftovers


def build_stats(wikitext, page_name, revid=None):
    """1枚分の性能値をまとめた辞書を返す。性能値が無ければ None。"""
    if not wikitext:
        return None

    variables = parse_variables(wikitext)
    units, leftovers = build_units(variables)
    attributes = parse_attributes(wikitext)
    if not units and not attributes:
        return None

    # レベルによらない補助的な数値（持続時間・ヒット数など）
    extras = {name: value for name, value in variables.items()
              if not name.endswith(("_11", "_base")) and not name.endswith("atk_speed")}
    extras.update(leftovers)

    return {
        "units": units,
        "attributes": [{"label": lab, "value": val} for lab, val in attributes],
        "extras": extras,
        "source": {
            "name": SOURCE_NAME,
            "license": LICENSE,
            "page": page_name,
            "url": PAGE_URL + urllib.parse.quote(page_name.replace(" ", "_")),
            "revid": revid,
            "base_level": BASE_LEVEL,
        },
    }
