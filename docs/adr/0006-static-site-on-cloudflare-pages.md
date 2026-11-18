# 0006. 静的サイトを Cloudflare Pages に公開する

- ステータス: Accepted
- 日付: 2026-09-07（v1.2.0）

## 背景（Context）

分析結果を、PC がスリープしていても、他の人のスマートフォンからでも、いつでも見られるようにしたい。

## 決定内容（Decision）

計算し終えた画面を HTML として書き出し（`static_export.py`）、Cloudflare Pages に wrangler でアップロードする（`publish.py`）。公開 URL は `https://<プロジェクト名>.pages.dev/<推測困難な32文字>/` で、認証は設けない。

## 理由と検討した代替案（Consequences / Alternatives）

- サーバーの契約が不要で、費用もかからない。プログラムが動き続ける必要がない。
- URL を知っている人は誰でも閲覧できる。URL は `--rotate-secret` で作り直せる。
- 公開サイトは書き込みを伴う操作を持たない（閲覧者が操作できず、所有者だけが使える非対称な機能になるため）。
- 検討した代替案: 自宅の Wi-Fi 内だけで、ダッシュボードを LAN に公開する（`web.host = 0.0.0.0`。PC の起動が必要）。
