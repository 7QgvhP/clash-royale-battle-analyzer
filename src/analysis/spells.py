# -*- coding: utf-8 -*-
"""呪文で倒せるユニットの判定に使うデータを組み立てる。

呪文とレベルを選ぶと、そのレベルの前後2つ（L-2〜L+2）のユニットについて、
呪文のダメージで倒せるかを示す。計算そのものはブラウザ側で行うが、各レベルの
値はここで算出して埋め込む。JavaScript と Python では端数の丸め方が異なるため、
カードの性能ページと同じ scale() を通して、表示される数値を必ず一致させる。

呪文の「ダメージ」の意味はカードごとに違う。

  - 1回だけ当たる（ファイアボール、ロケット）      … dmg をそのまま使う
  - 複数回当たる（矢の雨×3、ポイズン×8）          … dmg × ヒット数
  - 樽・配達系（ローリングバーバリアン）           … spawn（着地時の範囲ダメージ）。
                                                     dmg は中から出るユニットの攻撃
  - 攻撃しない（ゴブリンバレル、クローン、鏡）     … 対象外

値の種類からは機械的に判別できないため、SPELLS に呪文ごとの定義を持たせる。
"""
import json

from src.analysis.cardstats import GAME_MAX_LEVEL, level_range, scale, unit_name

# 判定の対象にする呪文と、そのダメージの取り出し方。キーは英語カード名。
#   key          … ダメージとして使う値（既定 dmg）
#   prefix       … その値を持つユニットの接頭辞（既定は本体）
#   ground_only  … 地上にしか当たらない
#   building_key … 建物にだけ別のダメージが入る場合、その値を持つユニットの接頭辞
#   variants     … 条件によってダメージが変わる場合の、段階キーと呼び名
#   note         … 判定の前提として画面に添える注記
SPELLS = {
    "Fireball": {},
    "Rocket": {},
    "Zap": {},
    "Arrows": {},
    "Lightning": {"note": "HPの高い順に最大3体へ落ちる。"},
    "Freeze": {},
    "Giant Snowball": {},
    "Tornado": {},
    # 属性表の対象は「味方」だが、それは加速の効果の話で、ダメージは敵に入る
    "Rage": {},
    "The Log": {"ground_only": True},
    "Barbarian Barrel": {"key": "spawn", "ground_only": True},
    "Royal Delivery": {"key": "spawn"},
    "Poison": {"note": "8秒間、範囲内に留まり続けた場合の合計。途中で出れば減る。"},
    "Earthquake": {"ground_only": True, "building_key": "build",
                   "note": "3秒間、範囲内に留まり続けた場合の合計。建物には別の大きなダメージが入る。"},
    "Vines": {"note": "最大3体に絡みつく。"},
    "Goblin Curse": {"prefix": "curse",
                     "note": "6秒間、範囲内に留まり続けた場合の合計。"},
    "Void": {"variants": [("1", "1体に命中"), ("3", "2〜4体に命中"), ("5", "5体以上に命中")],
             "note": "命中した敵が多いほど1体あたりのダメージが下がる。"},
}

LEVELS = list(range(1, GAME_MAX_LEVEL + 1))

# 建物カードのうち、中からユニットが出てくるもの。wiki ではこれらだけ接頭辞の付き方が
# 逆で、接頭辞付き（tomb / hut / cage / drill）が建物本体、接頭辞なしの本体側が
# 出てくるユニットを指す。出てくるユニットの呼び名をここで補う。
SPAWNING_BUILDINGS = {
    "Tombstone": "スケルトン",
    "Goblin Hut": "槍ゴブリン",
    "Goblin Cage": "ゴブリンブローラー",
    "Goblin Drill": "ゴブリン",
    "Barbarian Hut": "バーバリアン",
}

# 派生ユニットのうち空中を飛ぶもの。派生ユニットの空中・地上は元のカードと一致しない
# ことがある（地上のダークネクロが出すコウモリは空中、空中のスケルトンバレルから
# 落ちるスケルトンは地上）。そのため元のカードからは引き継がず、ここで決める。
AIR_SUB_UNITS = {"bat", "pup", "hound"}


def _attr(stats, label):
    """属性表の値を1つ取り出す。"""
    for attr in stats.get("attributes", []):
        if attr["label"] == label:
            return attr["value"]
    return None


def _unit(stats, prefix):
    """接頭辞に対応するユニットを返す。"""
    for unit in stats.get("units", []):
        if unit.get("prefix") == prefix:
            return unit
    return None


def _per_level(base):
    """基準値からレベル1〜16の値を並べる。存在しないレベルも含めて持っておく。"""
    return {lv: scale(base, lv) for lv in LEVELS}


def _spell(card, stats, definition):
    """呪文1枚分の判定用データ。ダメージが取れなければ None。"""
    unit = _unit(stats, definition.get("prefix"))
    if unit is None:
        return None
    hits = int((stats.get("extras") or {}).get("dmg_hits") or 1)
    key = definition.get("key", "dmg")

    variants = []
    for stage, label in definition.get("variants", [(None, None)]):
        base = unit.get(f"{key}#{stage}" if stage else key)
        if base is None:
            continue
        variants.append({"label": label, "damage": _per_level(base)})
    if not variants:
        return None

    building = None
    if definition.get("building_key"):
        bunit = _unit(stats, definition["building_key"])
        if bunit and bunit.get("dmg") is not None:
            building = _per_level(bunit["dmg"])

    return {
        "card_id": card["card_id"],
        "name": card["name_ja"] or card["name_en"],
        "icon": card["icon_path"],
        "levels": level_range(card["max_level"]),
        "hits": hits,
        "ground_only": bool(definition.get("ground_only")),
        "variants": variants,
        "building_damage": building,
        "note": definition.get("note"),
    }


def _units(card, stats):
    """倒される側になるユニットを並べる。派生ユニット（ゴーレマイト等）も含める。"""
    kind = _attr(stats, "Type")
    if kind not in ("Troop", "Building"):
        return []
    card_air = kind == "Troop" and _attr(stats, "Transport") == "Air"
    spawned_name = SPAWNING_BUILDINGS.get(card["name_en"]) if kind == "Building" else None

    out = []
    for unit in stats.get("units", []):
        if unit.get("hp") is None:
            continue
        prefix = unit.get("prefix")
        if spawned_name:
            # 接頭辞付きが建物本体、本体側が出てくるユニット
            building = prefix is not None
            sub = None if building else spawned_name
            air = False
        else:
            building = kind == "Building"
            sub = unit_name(prefix)
            # 本体は元のカードの移動方法に従い、派生ユニットは表で決める
            air = card_air if prefix is None else prefix.rstrip("_").lower() in AIR_SUB_UNITS
        out.append({
            "card_id": card["card_id"],
            "name": card["name_ja"] or card["name_en"],
            "sub": sub,
            "icon": card["icon_path"],
            "levels": level_range(card["max_level"]),
            "building": building,
            "air": air,
            "hp": _per_level(unit["hp"]),
            "shield": _per_level(unit["shield"]) if unit.get("shield") else None,
        })
    return out


def calculator_data(conn):
    """呪文計算の画面に埋め込むデータを返す。"""
    rows = conn.execute(
        "SELECT c.card_id, c.name_en, c.name_ja, c.max_level, c.elixir_cost, c.icon_path,"
        " s.stats_json FROM cards c JOIN card_stats s ON s.card_id = c.card_id"
        " WHERE c.is_support = 0 ORDER BY c.elixir_cost, c.name_ja").fetchall()

    spells, units = [], []
    for card in rows:
        stats = json.loads(card["stats_json"])
        definition = SPELLS.get(card["name_en"])
        if definition is not None:
            spell = _spell(card, stats, definition)
            if spell:
                spells.append(spell)
        units.extend(_units(card, stats))
    return {"spells": spells, "units": units}
