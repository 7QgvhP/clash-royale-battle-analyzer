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

from src.api.cardstats import BASE_LEVEL, LEVEL_FACTOR, STAGE_SEP, base_stat

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
    # wiki の見出しは Spawn Damage。出現・着地した瞬間に周囲へ与える範囲ダメージで、
    # ローリングバーバリアンの樽やメガナイトの着地がこれにあたる。
    "spawn": "出現時の範囲ダメージ",
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

# 段階別の値をつなぐ区切り。ゲーム内の「35-120-422」という表記に合わせる。
STAGE_JOIN = "-"

# 段階の呼び名。数字の接頭辞は通常「時間経過でダメージが上がる段階」を指すが、
# カードによって意味が違うため、そこだけ英語カード名で上書きする。
# 既定は「N段階目」。
STAGE_LABELS = {
    # ボイドの 1/3/5 は段階ではなく、命中した敵の数による違い
    "Void": {"1": "1体に命中", "3": "2〜4体に命中", "5": "5体以上に命中"},
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


def stage_label(stage, card_name_en=None):
    """段階の呼び名を返す。"""
    return STAGE_LABELS.get(card_name_en or "", {}).get(stage, f"{stage}段階目")


def stat_label(key, card_name_en=None):
    """数値項目の表示名。段階付きのキーは括弧で段階を添える。"""
    base, _, stage = key.partition(STAGE_SEP)
    label = STAT_LABELS.get(base, base)
    return f"{label}（{stage_label(stage, card_name_en)}）" if stage else label


def _order(key):
    """表示順。種類の並び順が先、同じ種類なら段階の小さい順。"""
    base, _, stage = key.partition(STAGE_SEP)
    index = SCALED.index(base) if base in SCALED else len(SCALED)
    return (index, int(stage) if stage.isdigit() else 0)


def scaled_keys(unit):
    """そのユニットが持つ、レベルで変わる項目のキーを表示順に返す。"""
    return sorted((k for k in unit if base_stat(k) in SCALED), key=_order)


def _dps(damage, atk_speed):
    """秒間ダメージ。攻撃速度が無い、または0なら出さない。"""
    if not damage or not atk_speed:
        return None
    return round(damage / atk_speed)


def _speed_keys(unit):
    """そのユニットが持つ攻撃速度のキーを表示順に返す。"""
    return sorted((k for k in unit if base_stat(k) == "atk_speed"), key=_order)


def dps_pairs(unit):
    """秒間ダメージを出せる（ダメージ, 攻撃速度）の組を返す。

    段階の付き方はカードで異なる。インフェルノタワーはダメージ側が段階を持ち、
    リトルプリンスは攻撃速度側だけが段階を持つ。どちらの場合も段階ごとの
    秒間ダメージが出るように組み合わせる。
    """
    speeds = _speed_keys(unit)
    if not speeds:
        return []

    pairs = []
    for dmg_key in (k for k in scaled_keys(unit) if base_stat(k) == "dmg"):
        _, _, stage = dmg_key.partition(STAGE_SEP)
        if stage:
            # 同じ段階の速度があればそれを使い、無ければ共通の速度を使う
            same = f"atk_speed{STAGE_SEP}{stage}"
            pairs.append((dmg_key, same if same in unit else speeds[0]))
        else:
            # ダメージは一定で速度だけが段階で変わる場合、段階の数だけ出す
            pairs.extend((dmg_key, sk) for sk in speeds)
    return pairs


def dps_label(dmg_key, speed_key, card_name_en=None):
    """秒間ダメージの表示名。段階はダメージ側を優先し、無ければ速度側を使う。"""
    _, _, stage = dmg_key.partition(STAGE_SEP)
    if not stage:
        _, _, stage = speed_key.partition(STAGE_SEP)
    label = "秒間ダメージ"
    return f"{label}（{stage_label(stage, card_name_en)}）" if stage else label


def progressive(card_name_en=None):
    """数字の接頭辞が「時間経過で上がる段階」を意味するかどうか。

    意味が違うカードだけ STAGE_LABELS に登録してあるので、そこに無ければ
    通常の段階とみなす。段階であれば、ゲーム内と同じ 35-120-422 の形で
    1行にまとめて表示できる。
    """
    return (card_name_en or "") not in STAGE_LABELS


def _groups(keys, card_name_en=None):
    """表示のまとまりを [(種類, [キー])] で返す。

    段階が時間経過を表すカードでは、同じ種類の段階別の値を1つにまとめる。
    ゲーム内も「35-120-422」と続けて書くため、そちらに合わせる。
    意味が違うカード（ボイド）は値が減っていくので、まとめず段階ごとに出す。
    """
    order, bucket = [], {}
    for key in keys:
        base = base_stat(key)
        if base not in bucket:
            order.append(base)
            bucket[base] = []
        bucket[base].append(key)

    join = progressive(card_name_en)
    out = []
    for base in order:
        group = bucket[base]
        if join and len(group) > 1:
            out.append((base, group))
        else:
            out.extend((base, [k]) for k in group)
    return out


def _joined(values):
    """段階別の値をゲーム内と同じ並びにする。"""
    return STAGE_JOIN.join("--" if v is None else str(v) for v in values)


def unit_rows(unit, level, card_name_en=None):
    """1ユニット分の、指定レベルでの数値を並べる。"""
    rows = []
    for base, keys in _groups(scaled_keys(unit), card_name_en):
        if len(keys) > 1:
            rows.append({"label": STAT_LABELS.get(base, base),
                         "value": _joined([scale(unit[k], level) for k in keys])})
        else:
            rows.append({"label": stat_label(keys[0], card_name_en),
                         "value": scale(unit[keys[0]], level)})

    pairs = dps_pairs(unit)
    if progressive(card_name_en) and len(pairs) > 1:
        rows.append({"label": "秒間ダメージ",
                     "value": _joined([_dps(scale(unit[d], level), unit[sp])
                                       for d, sp in pairs])})
    else:
        for dmg_key, speed_key in pairs:
            rows.append({"label": dps_label(dmg_key, speed_key, card_name_en),
                         "value": _dps(scale(unit[dmg_key], level), unit[speed_key])})
    return rows


def fixed_rows(unit, card_name_en=None):
    """レベルで変わらない値。攻撃速度が段階ごとに違うカードにも対応する。"""
    speeds = _speed_keys(unit)
    if progressive(card_name_en) and len(speeds) > 1:
        return [{"label": "攻撃速度", "value": _joined([unit[k] for k in speeds])}]

    rows = []
    for key in speeds:
        _, _, stage = key.partition(STAGE_SEP)
        label = "攻撃速度"
        if stage:
            label += f"（{stage_label(stage, card_name_en)}）"
        rows.append({"label": label, "value": unit[key]})
    return rows


def level_table(unit, levels, card_name_en=None):
    """ユニットのレベル別の数値表を組み立てる。

    列はそのユニットが実際に持っている項目だけにする。全カード共通の列を
    並べると、大半が空欄の表になって読み取りづらい。段階のあるカードは
    数値カードと同じく1列にまとめる。
    """
    groups = _groups(scaled_keys(unit), card_name_en)
    pairs = dps_pairs(unit)
    join_dps = progressive(card_name_en) and len(pairs) > 1

    columns = [STAT_LABELS.get(base, base) if len(keys) > 1
               else stat_label(keys[0], card_name_en)
               for base, keys in groups]
    if join_dps:
        columns.append("秒間ダメージ")
    else:
        columns += [dps_label(d, sp, card_name_en) for d, sp in pairs]

    rows = []
    for level in levels:
        # キー名を values にすると、テンプレート側で辞書の values() が
        # 優先されてしまうため cells とする
        cells = [_joined([scale(unit[k], level) for k in keys]) if len(keys) > 1
                 else scale(unit[keys[0]], level)
                 for _, keys in groups]
        dps_values = [_dps(scale(unit[d], level), unit[sp]) for d, sp in pairs]
        cells += [_joined(dps_values)] if join_dps else dps_values
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
                "rows": unit_rows(unit, shown, card["name_en"]),
                "fixed": fixed_rows(unit, card["name_en"]),
                "table": level_table(unit, levels, card["name_en"]),
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
