# -*- coding: utf-8 -*-
"""集計時の絞り込み条件。"""
from datetime import datetime, timedelta, timezone


class Filters:
    """期間・モード・自デッキによる絞り込み条件を保持する。

    SQLの WHERE 句とパラメータを組み立てる責務を持つ。
    """

    PERIODS = {
        "all": None,
        "7d": 7,
        "30d": 30,
        "90d": 90,
    }

    def __init__(self, period="all", modes=None, deck_group_id=None,
                 player_tag=None, countable_only=True):
        self.period = period if period in self.PERIODS else "all"
        # 空リストは「絞り込みなし」として扱う。
        self.modes = list(modes) if modes else []
        self.deck_group_id = deck_group_id
        # 集計は必ず1人に閉じる。未指定だと複数プレイヤーの対戦が混ざる。
        self.player_tag = player_tag
        self.countable_only = countable_only

    @property
    def since(self):
        """期間指定の開始日時をAPI形式（YYYYMMDDThhmmss.000Z）で返す。"""
        days = self.PERIODS.get(self.period)
        if days is None:
            return None
        start = datetime.now(timezone.utc) - timedelta(days=days)
        return start.strftime("%Y%m%dT%H%M%S.000Z")

    def where(self, alias="m"):
        """WHERE句の条件文字列とパラメータを返す。"""
        clauses = []
        params = []

        if self.player_tag:
            clauses.append(f"{alias}.player_tag = ?")
            params.append(self.player_tag)

        if self.countable_only:
            clauses.append(f"{alias}.is_countable = 1")

        since = self.since
        if since:
            clauses.append(f"{alias}.battle_time >= ?")
            params.append(since)

        if self.modes:
            placeholders = ", ".join("?" for _ in self.modes)
            clauses.append(f"{alias}.battle_type IN ({placeholders})")
            params.extend(self.modes)

        if self.deck_group_id is not None:
            clauses.append(
                f"{alias}.my_deck_hash IN (SELECT deck_hash FROM decks WHERE group_id = ?)")
            params.append(self.deck_group_id)

        if not clauses:
            return "1 = 1", []
        return " AND ".join(clauses), params

    def to_query_string(self):
        """URLクエリ用の辞書を返す。"""
        q = {"period": self.period}
        if self.modes:
            q["modes"] = ",".join(self.modes)
        if self.deck_group_id is not None:
            q["deck"] = str(self.deck_group_id)
        if self.player_tag:
            q["player"] = self.player_tag
        return q

    @classmethod
    def from_request(cls, args, default_player_tag=None):
        """FlaskのリクエストパラメータからFiltersを組み立てる。"""
        modes = [m for m in (args.get("modes") or "").split(",") if m]
        deck = args.get("deck")
        deck_group_id = int(deck) if deck and deck.isdigit() else None
        player = (args.get("player") or "").strip() or default_player_tag
        if player:
            player = "#" + player.lstrip("#").upper()
        return cls(period=args.get("period", "all"), modes=modes,
                   deck_group_id=deck_group_id, player_tag=player)
