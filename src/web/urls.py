# -*- coding: utf-8 -*-
"""画面URLの組み立て。

サーバー稼働時はクエリ文字列（/cards?period=7d）を使うが、静的サイトでは
クエリ文字列が使えないため、絞り込みの組み合わせごとにディレクトリを分ける。

    <secret>/<combo>/cards.html

両方のモードで同じテンプレートを使えるよう、URLの生成をここに集約する。
"""
from flask import url_for

# 画面の定義。ここが唯一の定義元となる。
#   画面キー: (Flaskのエンドポイント名, ルートパス, 静的サイトでのファイル名)
# 静的サイトの書き出しもこの表を参照するため、画面を増やすときは
# ここに1行足すだけでよい。
SCREENS = {
    "summary": ("summary", "/", "summary.html"),
    "cards": ("weak_cards", "/cards", "cards.html"),
    "decks": ("deck_view", "/decks", "decks.html"),
    "levels": ("level_view", "/levels", "levels.html"),
    "history": ("history_view", "/history", "history.html"),
}

# 同じ絞り込みの中で追加生成する派生ページ。画面キー → 派生名の一覧。
SCREEN_VARIANTS = {
    "summary": ["week", "n10", "n50"],
}


def static_filename(screen, variant=None):
    """静的サイトでのファイル名を返す。"""
    filename = SCREENS[screen][2]
    return filename.replace(".html", f"-{variant}.html") if variant else filename


def _slug(value, fallback="all"):
    """URLに使える文字列へ整える。"""
    if value in (None, ""):
        return fallback
    return str(value).lstrip("#").replace("/", "-")


def combo_key(player_tag, period, mode, deck_group_id):
    """絞り込みの組み合わせを表すディレクトリ名を返す。"""
    return "{}_{}_{}_{}".format(
        _slug(player_tag, "noplayer"),
        _slug(period, "all"),
        _slug(mode, "any"),
        _slug(deck_group_id, "all"),
    )


def build(screen, filters, static_mode, overrides=None, variant=None):
    """画面へのURLを返す。

    overrides で絞り込みの一部だけを差し替えられる（例: 期間だけ変更）。
    variant は同一絞り込み内の派生ページ（例: 週次のサマリー）を指す。
    """
    overrides = overrides or {}
    player = overrides.get("player", filters.player_tag)
    period = overrides.get("period", filters.period)
    if "mode" in overrides:
        mode = overrides["mode"]
    else:
        mode = filters.modes[0] if filters.modes else None
    deck = overrides.get("deck", filters.deck_group_id)

    endpoint = SCREENS[screen][0]

    if not static_mode:
        params = {"period": period}
        if player:
            params["player"] = player
        if mode:
            params["modes"] = mode
        if deck is not None:
            params["deck"] = deck
        if variant:
            params["unit"] = variant
        return url_for(endpoint, **params)

    # 静的サイトでは、同じ階層の別ディレクトリを相対パスで指す。
    return f"../{combo_key(player, period, mode, deck)}/{static_filename(screen, variant)}"


def filter_params(filters):
    """サーバー稼働時に、絞り込みをクエリ文字列へ渡すための辞書を返す。"""
    params = {"period": filters.period}
    if filters.player_tag:
        params["player"] = filters.player_tag
    if filters.modes:
        params["modes"] = filters.modes[0]
    if filters.deck_group_id is not None:
        params["deck"] = filters.deck_group_id
    return params


def _carry(filters):
    """共通ページへのリンクに付ける、呼び出し元の絞り込みを表すクエリ文字列。

    呪文・カード性能・カード詳細は、絞り込みごとには作らず1ファイルだけ
    書き出す。そのため、リンクの行き先は既定のプレイヤー向けになっている。
    どのプレイヤーから来たかをここで引き渡し、ページ側（base.html の
    スクリプト）でナビの行き先を直す。
    """
    if filters is None or not filters.player_tag:
        return ""
    mode = filters.modes[0] if filters.modes else None
    return "?from=" + combo_key(filters.player_tag, filters.period, mode,
                                filters.deck_group_id)


def match_url(match_id, static_mode):
    """対戦詳細ページへのURLを返す。

    詳細は絞り込みに依存しないため、組み合わせごとには作らず
    <secret>/matches/<id>.html に1つだけ置く。組み合わせのディレクトリと
    同じ深さなので、CSSや画像への相対パスはそのまま通る。
    """
    if not static_mode:
        return url_for("match_view", match_id=match_id)
    return f"../matches/{match_id}.html"


def card_url(card_id, static_mode, filters=None):
    """カード詳細ページへのURLを返す。

    性能値は絞り込みに依存しないため、組み合わせごとには作らず
    <secret>/card/<id>.html に1つだけ置く。画像を入れる cards/ とは
    別の名前にして衝突を避ける。見ているプレイヤーは引き継ぐ。
    """
    if not static_mode:
        return url_for("card_view", card_id=card_id, **filter_params(filters))             if filters else url_for("card_view", card_id=card_id)
    return f"../card/{card_id}.html{_carry(filters)}"


def spells_url(static_mode, filters=None):
    """呪文で倒せるユニットの画面へのURLを返す。

    絞り込みに依存しないため、組み合わせごとには作らず
    <secret>/spells/index.html に1つだけ置く。見ているプレイヤーは引き継ぐ。
    """
    if not static_mode:
        return url_for("spells_view", **filter_params(filters)) if filters             else url_for("spells_view")
    return f"../spells/index.html{_carry(filters)}"


def card_list_url(static_mode, filters=None):
    """カード性能の一覧へのURLを返す。

    絞り込みに依存しないため、組み合わせごとには作らず
    <secret>/card-list/index.html に1つだけ置く。見ているプレイヤーは引き継ぐ。
    """
    if not static_mode:
        return url_for("card_list_view", **filter_params(filters)) if filters             else url_for("card_list_view")
    return f"../card-list/index.html{_carry(filters)}"


def asset_url(path, static_mode):
    """CSSや画像へのURLを返す。"""
    if not static_mode:
        if path.startswith("cards/"):
            return url_for("card_image", filename=path[len("cards/"):])
        return url_for("static", filename=path)
    return f"../{path}"


def helpers(filters, static_mode):
    """テンプレートへ渡すURL生成関数をまとめて返す。"""
    def page_url(screen, variant=None, **overrides):
        return build(screen, filters, static_mode, overrides, variant)

    def asset(path):
        return asset_url(path, static_mode)

    def match(match_id):
        return match_url(match_id, static_mode)

    def card(card_id):
        return card_url(card_id, static_mode, filters)

    def spells():
        return spells_url(static_mode, filters)

    def card_list():
        return card_list_url(static_mode, filters)

    return {"page_url": page_url, "asset_url": asset, "match_url": match,
            "card_url": card, "spells_url": spells, "card_list_url": card_list,
            "static_mode": static_mode}
