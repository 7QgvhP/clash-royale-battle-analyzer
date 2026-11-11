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

  3. レベル別の表（id="unit-statistics-table"）
     セルの中身はたいてい 2 の変数を参照する式なので、ふだんは読む必要がない。
     ただし一部のページには、式ではなく数値が直接書かれた列がある。バランス調整の
     とき、表の数値だけが直されて変数が古いまま残ることがあるため、直書きの列は
     基準レベルの行から読み取り、変数より優先する。
"""
import logging
import re
import time
import urllib.parse

from src.api import mediawiki

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

# 段階別の値を表すときの区切り。dmg#2 で「2段階目のダメージ」を意味する。
STAGE_SEP = "#"

# レベル別の性能値の表のid
STATS_TABLE_ID = "unit-statistics-table"

# 表の列見出しと性能値の項目との対応は、カードごとに
# src/data/card_stats_columns.json で与える。対応表に書く値は次の3通り。
#   "dmg" / "drill.hp"   その項目の基準値を、表の数値で置き換える
#   "atk_speed_from_dps" 秒間ダメージの列として扱い、ダメージから攻撃速度を逆算する
#   null                 その列は使わない
SPEED_FROM_DPS = "atk_speed_from_dps"

# レベルを並べただけの列は性能値ではないので、対応表に書かなくても読み飛ばす。
# ミラーとクローンの「コピー後のレベル」の列もこれに当たる。
LEVEL_COLUMN = re.compile(r"Level$", re.I)

# 見出しに埋め込まれた画像
FILE_LINK = re.compile(r"\[\[(?:File|Image):[^\]]*\]\]", re.I)


def _request(titles):
    """複数ページの wikitext をまとめて取得する。"""
    return mediawiki.get_json(API, {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content|ids|timestamp",
        "rvslots": "main",
        "format": "json",
        "redirects": "1",
        "titles": "|".join(titles),
    }, USER_AGENT, TIMEOUT)["query"]


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


def _table_body(wikitext, table_id):
    """指定したidの表の中身を返す。見つからなければ None。"""
    # class と id の記述順はページによって前後するため、順序を問わずに探す
    pattern = r'\{\|[^\n]*id="%s"[^\n]*\n(.*?)\n\|\}' % re.escape(table_id)
    match = re.search(pattern, wikitext, re.S)
    return match.group(1) if match else None


def _split_cells(line, sep):
    """表の1行をセルに割る。セルの前に付く書式指定は落とす。"""
    cells = []
    for cell in line[1:].split(sep):
        # scope="col" style="width: 12%;" |Level のような指定を取り除く
        while True:
            stripped = re.sub(
                r'^\s*(?:scope|style|colspan|rowspan|align|class)\s*=\s*"[^"]*"\s*',
                "", cell)
            if stripped == cell:
                break
            cell = stripped
        cells.append(cell.lstrip("|").strip())
    return cells


def _table_rows(body):
    """表を [(行の種類, [セル])] に割る。種類は見出し行が "head"、データ行が "body"。

    ページによって、セルを `|6||133` と1行に並べる書き方と、1セル1行に書く
    書き方が混在する。見出しのアイコンが次の行に置かれていることもあるため、
    記号で始まらない行は、直前のセルの続きとして扱う。
    """
    rows, current = [], None
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("|-"):
            current = None
            continue
        if line.startswith("!"):
            kind, sep = "head", "!!"
        elif line.startswith("|"):
            kind, sep = "body", "||"
        else:
            if current and current[1]:
                current[1][-1] += " " + line
            continue
        cells = _split_cells(line, sep)
        if current is None or current[0] != kind:
            current = (kind, cells)
            rows.append(current)
        else:
            current[1].extend(cells)
    return rows


def _number(text):
    """セルが数値そのものなら float で返す。式や単位付きなら None。"""
    text = (text or "").replace(",", "").strip()
    return float(text) if re.fullmatch(r"\d+(?:\.\d+)?", text) else None


def parse_level_values(wikitext, level=BASE_LEVEL):
    """レベル別の表から、数値が直接書かれたセルを {列見出し: 値} で返す。

    式（{{#expr:}} や {{Dps}}）のセルは変数から換算できるので対象にしない。
    レベルを並べただけの列も、性能値ではないので除く。
    """
    body = _table_body(wikitext, STATS_TABLE_ID)
    if not body:
        return {}

    labels = []
    for kind, cells in _table_rows(body):
        if kind == "head":
            # 見出しに置かれた画像（ミラーのレア度アイコンなど）は見出し名ではない
            labels = [_clean(FILE_LINK.sub("", c)) for c in cells]
            continue
        if not cells or _number(cells[0]) != level:
            continue
        found = {}
        for label, cell in zip(labels, cells):
            value = _number(cell)
            if value is None or not label or LEVEL_COLUMN.search(label):
                continue
            found[label] = value
        return found
    return {}


def _find_unit(units, prefix):
    """接頭辞からユニットを探す。空文字なら本体。"""
    for unit in units:
        if (unit.get("prefix") or "") == prefix:
            return unit
    return None


def apply_level_values(units, values, columns):
    """表に直書きされた数値で、変数から作った基準値を上書きする。

    columns は {列見出し: 対象の項目} の対応表。戻り値は
    （上書きした内容の一覧, 対応表に無かった列見出しの一覧）。
    """
    columns = columns or {}
    changed, unmapped, speeds = [], [], []

    def overwrite(unit, key, value, label, target):
        if unit.get(key) != value:
            changed.append((label, target, unit.get(key), value))
            unit[key] = value

    for label, value in values.items():
        if label not in columns:
            unmapped.append(label)
            continue
        target = columns[label]
        if not target:
            continue
        prefix, _, key = target.rpartition(".")
        unit = _find_unit(units, prefix)
        if unit is None:
            # 変数がまったく無く、表にしか数値が無いカードは、ここで作る
            unit = {"prefix": prefix or None}
            units.append(unit)
        if key == SPEED_FROM_DPS:
            # ダメージ側の上書きを先に済ませる必要があるため、後回しにする
            speeds.append((unit, value, label, target))
            continue
        overwrite(unit, key, value, label, target)

    for unit, dps, label, target in speeds:
        # 攻撃速度 = ダメージ ÷ 秒間ダメージ。どちらも表の数値なので、
        # 変数側の古い攻撃速度ではなく、表の表示と合う値になる。
        damage = unit.get("dmg")
        if damage and dps:
            overwrite(unit, "atk_speed", round(damage / dps, 1), label, "atk_speed")

    return changed, unmapped


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


def base_stat(key):
    """段階付きのキーから、もとの種類だけを取り出す。dmg#2 -> dmg"""
    return key.split(STAGE_SEP)[0]


def build_units(variables):
    """変数をユニット単位にまとめる。先頭が本体、以降がそのカードが出すユニット。

    接頭辞が数字のものは別のユニットではなく、本体の「段階別の値」を指す。
    インフェルノタワーの 1_dmg_11 / 2_dmg_11 / 3_dmg_11 は時間経過で上がる
    ダメージであり、ボイドの 1/3/5 は命中した敵の数による違いである。
    いずれも1体のユニットの話なので、本体に dmg#1 のような形で束ねる。
    """
    units = {}

    def put(prefix, stat, value):
        if prefix and prefix.isdigit():
            units.setdefault("", {})[f"{stat}{STAGE_SEP}{prefix}"] = value
        else:
            units.setdefault(prefix, {})[stat] = value

    for name, value in variables.items():
        if name.endswith(("_11", "_base")):
            prefix, stat = _split_prefix(name)
            if stat is not None:
                put(prefix, stat, value)

    # 攻撃速度はレベルで変わらないため別枠。接頭辞の付き方は変数側に合わせる。
    for name, value in variables.items():
        if name.endswith("atk_speed"):
            put(name[:-len("atk_speed")].rstrip("_"), "atk_speed", value)

    # HPもダメージも無いものはユニットではない
    ordered, leftovers = [], {}
    for prefix in sorted(units, key=lambda p: (p != "", p)):
        unit = units[prefix]
        if not any(base_stat(k) in ("hp", "dmg") for k in unit):
            leftovers.update({f"{prefix}_{k}" if prefix else k: v
                              for k, v in unit.items()})
            continue
        unit = dict(unit)
        unit["prefix"] = prefix or None
        ordered.append(unit)
    return ordered, leftovers


def _hit_speed(attributes):
    """属性表の攻撃速度（Hit Speed）を秒数で返す。無ければ None。"""
    for label, value in attributes:
        if label == "Hit Speed":
            match = re.match(r"([0-9]+(?:\.[0-9]+)?)", value)
            if match:
                return float(match.group(1))
    return None


def build_stats(wikitext, page_name, revid=None, columns=None):
    """1枚分の性能値をまとめた辞書を返す。性能値が無ければ None。

    columns は、そのカードの「レベル表の列見出し → 性能値の項目」の対応表
    （src/data/card_stats_columns.json）。表に数値が直接書かれている列は、
    変数が古いまま残っていることがあるため、表の値を優先する。
    """
    if not wikitext:
        return None

    variables = parse_variables(wikitext)
    units, leftovers = build_units(variables)
    attributes = parse_attributes(wikitext)

    changed, unmapped = apply_level_values(
        units, parse_level_values(wikitext), columns)
    for label, target, before, after in changed:
        logging.info("%s: %s を表の値にしました（%s → %s、列「%s」）",
                     page_name, target, before, after, label)
    if unmapped:
        logging.warning(
            "%s: レベル表に数値が直接書かれた列があり、対応表に未登録です: %s",
            page_name, "、".join(unmapped))

    # 攻撃速度の変数が無いカードは、属性表の値を使う。秒間ダメージの計算に要る。
    if units and not any(base_stat(k) == "atk_speed" for u in units for k in u):
        speed = _hit_speed(attributes)
        if speed:
            units[0]["atk_speed"] = speed

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
