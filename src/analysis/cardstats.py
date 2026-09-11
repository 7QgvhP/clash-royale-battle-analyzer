# -*- coding: utf-8 -*-
"""カード性能値の表示用整形。

保存されている値はレベル11基準なので、表示するレベルに合わせて換算する。
換算式は情報源である Clash Royale Wiki の各レベル表と同じ

    そのレベルの値 = 基準値 × 1.1^(レベル - 11)

を使う。こうしておくと、画面から辿れるwikiページの数値と表示が一致し、
利用者が出典を照合できる。wiki側の注記どおり丸めの差で ±1 程度ずれることがある。

射程・移動速度・展開時間などレベルで変わらない値は属性としてそのまま出す。
"""
import re

from src.api.cardstats import BASE_LEVEL, LEVEL_FACTOR

# ゲーム内で表示されるレベルの上限
GAME_MAX_LEVEL = 16

# レベルで変化する項目。ここに無い項目はレベル非依存として素通しする。
SCALED = ("hp", "dmg", "crown_dmg", "death", "spawn", "charge", "dash",
          "heal", "shield", "crown")

# ユニットの数値項目の表示名
STAT_LABELS = {
    "hp": "HP",
    "dmg": "ダメージ",
    "crown_dmg": "タワーへのダメージ",
    "death": "死亡時ダメージ",
    "spawn": "生成ユニットのダメージ",
    "crown": "タワーへのダメージ",
    "charge": "チャージ攻撃のダメージ",
    "dash": "突進のダメージ",
    "heal": "回復量",
    "shield": "シールドHP",
    "atk_speed": "攻撃速度",
}

# 属性テーブルの列名の表示名。wikiに新しい列が増えても、
# ここに無いものは英語のまま出すので表示自体は壊れない。
ATTR_LABELS = {
    "Cost": "コスト",
    "Type": "種別",
    "Rarity": "レアリティ",
    "Target": "攻撃対象",
    "Deploy Time": "展開時間",
    "Range": "射程",
    "Speed": "移動速度",
    "Transport": "移動方法",
    "Hit Speed": "攻撃速度",
    "First Hit Speed": "初撃までの時間",
    "Count": "体数",
    "Projectile Speed": "弾速",
    "Splash Radius": "範囲ダメージ半径",
    "Radius": "効果半径",
    "Lifetime": "存在時間",
    "Spawn Speed": "生成間隔",
    "Duration": "効果時間",
    "Stun Duration": "スタン時間",
    "Projectile Range": "弾の射程",
    "Projectile Width": "弾の幅",
    "Projectile Radius": "弾の半径",
    "Slowdown": "減速率",
    "Slow Duration": "減速時間",
    "Width": "幅",
    "Death Damage Splash Radius": "死亡時ダメージの半径",
    "Production Speed": "生産間隔",
    "Spawn Delay": "生成までの時間",
    "Spawn Range": "生成範囲",
    "Freeze Duration": "凍結時間",
    "Curse Duration": "呪いの持続時間",
    "Invisibility Time": "透明化の時間",
    "Damage Charge": "チャージダメージ",
    "Axe Time": "斧の時間",
    "Boost": "強化倍率",
    "Clone Hitpoints": "クローンのHP",
    "Clone Shield Hitpoints": "クローンのシールドHP",
    "Parry Damage": "受け流しダメージ",
    "Parry Cooldown": "受け流しの再使用時間",
}

# 値の表記をゲーム内の言い回しへ寄せる。キーは小文字で引く。
VALUE_LABELS = {
    "ground": "地上",
    "air": "空中",
    "air & ground": "空中・地上",
    "buildings": "建物のみ",
    "friendly troops": "味方ユニット",
    "troop": "ユニット",
    "building": "建物",
    "spell": "呪文",
    "common": "ノーマル",
    "rare": "レア",
    "epic": "スーパーレア",
    "legendary": "ウルトラレア",
    "champion": "チャンピオン",
    "melee": "近接",
}

# 値の中に現れる英単語。移動速度や射程は「Medium (60)」のような複合になるため、
# 単語ごとに置き換える。
WORD_LABELS = {
    "Very Slow": "とても遅い", "Slow": "遅い", "Medium": "普通",
    "Very Fast": "とても速い", "Fast": "速い",
    "Short": "短", "Long": "長",
    "Melee": "近接", "Ground": "地上", "Air": "空中", "Buildings": "建物のみ",
}

# カードが出す別ユニットの表示名。ここに無いものは元の綴りのまま出す。
UNIT_LABELS = {
    "golem": "ゴーレム本体", "mite": "ゴーレマイト", "skel": "スケルトン",
    "spear": "槍ゴブリン", "hut": "小屋", "hound": "ラヴァハウンド",
    "pup": "ラヴァパップ", "bat": "コウモリ", "rider": "乗り手",
    "guard": "ガーディアン", "monster": "モンスター", "bush": "茂み",
    "rocket": "ロケット", "giant": "ジャイアント", "hog": "ホグ",
    "ram": "ラム", "tomb": "墓", "drill": "ドリル", "cage": "檻",
    "boy": "少年", "girl": "少女", "blob": "スライム", "curse": "呪い",
    "build": "建物", "fire": "炎", "charge": "突進", "stab": "刺突",
    "rage": "ブースト時", "sk": "スケルトン",
}


def scale(value, level):
    """基準レベルの値を、指定レベルの値へ換算する。"""
    if value is None:
        return None
    return round(value * (LEVEL_FACTOR ** (level - BASE_LEVEL)))


def level_range(max_level):
    """そのカードでゲーム内に存在するレベルを、小さい順に返す。

    APIの maxLevel はレアリティごとの段数で、ゲーム内の表示レベルは
    上限16から逆算した値になる。ウルトラレアなら 9〜16 のようになる。
    """
    if not max_level:
        return list(range(1, GAME_MAX_LEVEL + 1))
    lowest = GAME_MAX_LEVEL - max_level + 1
    return list(range(lowest, GAME_MAX_LEVEL + 1))


def unit_name(prefix):
    """ユニットの表示名。本体は None を返し、呼び出し側で見出しを省く。"""
    if not prefix:
        return None
    key = prefix.rstrip("_").lower()
    return UNIT_LABELS.get(key, prefix.rstrip("_"))


def _dps(damage, atk_speed):
    """秒間ダメージ。攻撃速度が無い、または0なら出さない。"""
    if not damage or not atk_speed:
        return None
    return round(damage / atk_speed)


def unit_rows(unit, level):
    """1ユニット分の、指定レベルでの数値を並べる。"""
    rows = []
    for key in SCALED:
        if unit.get(key) is None:
            continue
        rows.append({"label": STAT_LABELS.get(key, key), "value": scale(unit[key], level)})
    dps = _dps(scale(unit.get("dmg"), level), unit.get("atk_speed"))
    if dps is not None:
        rows.append({"label": "秒間ダメージ", "value": dps})
    return rows


def level_table(unit, levels):
    """ユニットのレベル別の数値表を組み立てる。

    列はそのユニットが実際に持っている項目だけにする。全カード共通の列を
    並べると、大半が空欄の表になって読み取りづらい。
    """
    keys = [k for k in SCALED if unit.get(k) is not None]
    columns = [STAT_LABELS.get(k, k) for k in keys]
    has_dps = unit.get("dmg") is not None and unit.get("atk_speed")
    if has_dps:
        columns.append("秒間ダメージ")

    rows = []
    for level in levels:
        # キー名を values にすると、テンプレート側で辞書の values() が
        # 優先されてしまうため cells とする
        cells = [scale(unit[k], level) for k in keys]
        if has_dps:
            cells.append(_dps(scale(unit["dmg"], level), unit["atk_speed"]))
        rows.append({"level": level, "cells": cells})
    return {"columns": columns, "rows": rows}


def translate_value(value):
    """属性の値を日本語に寄せる。対応が無い部分は原文のまま残す。"""
    if value is None:
        return None
    text = str(value).strip()
    whole = VALUE_LABELS.get(text.lower())
    if whole:
        return whole
    # 「1.2 sec」「30 sec」を秒表記へ
    text = re.sub(r"(\d)\s*sec\b", r"\1秒", text)
    # 「Medium (60)」「Melee: Short (0.75)」のような複合は単語ごとに置き換える。
    # 長い綴りから先に当てないと Very Fast が Fast に食われる。
    for word in sorted(WORD_LABELS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(word)}\b", WORD_LABELS[word], text)
    return text


def translate_attributes(attributes):
    """属性の列名と値を日本語に寄せる。対応が無いものはそのまま残す。"""
    return [{"label": ATTR_LABELS.get(a["label"], a["label"]),
             "value": translate_value(a["value"])}
            for a in attributes]


def card_detail(conn, card_id, level=BASE_LEVEL):
    """カード1枚分の表示用データを組み立てる。カードが無ければ None。"""
    from src.db import repository as repo

    card = conn.execute(
        "SELECT card_id, name_en, name_ja, rarity, max_level, elixir_cost,"
        " is_support, icon_path, evo_icon_path"
        " FROM cards WHERE card_id = ?", (card_id,)).fetchone()
    if card is None:
        return None

    stats = repo.get_card_stats(conn, card_id)
    levels = level_range(card["max_level"])
    # 基準レベルがそのカードに存在しない場合（段数の少ないカード）は下限に寄せる
    shown = level if level in levels else levels[0]

    units = []
    if stats:
        for unit in stats.get("units", []):
            units.append({
                "name": unit_name(unit.get("prefix")),
                "atk_speed": unit.get("atk_speed"),
                "rows": unit_rows(unit, shown),
                "table": level_table(unit, levels),
            })

    return {
        "card": {
            "card_id": card["card_id"],
            "name": card["name_ja"] or card["name_en"],
            "name_en": card["name_en"],
            "rarity": translate_value(card["rarity"]),
            "elixir_cost": card["elixir_cost"],
            "icon_path": card["icon_path"],
            "evo_icon_path": card["evo_icon_path"],
        },
        "level": shown,
        "levels": levels,
        "units": units,
        "attributes": translate_attributes(stats.get("attributes", [])) if stats else [],
        "source": (stats or {}).get("source"),
        "updated_at": (stats or {}).get("updated_at"),
        "has_stats": bool(stats),
    }
