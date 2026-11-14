# 設計判断記録（ADR）

重要な設計判断を、1判断1ファイルで記録する。旧要件定義書の「確定した設計判断の一覧」をもとに作った。

## ファイル命名規則

`NNNN-短い題名.md`（`NNNN` は4桁の連番。題名は英小文字とハイフン）

## ステータス

| ステータス | 意味 |
|---|---|
| Proposed | 提案中 |
| Accepted | 採用済み |
| Deprecated | 廃止（後継なし） |
| Superseded | 別の ADR で置き換えられた（置き換えた ADR へのリンクを書く） |

コードや履歴から逆算した判断は、ステータスに「推定（コードから逆算）」と付記する。

## 運用

- 既存の ADR は書き換えない。判断を変えるときは新しい ADR を追加し、古い ADR のステータスを Superseded にする。

## 一覧

| 番号 | 題名 | ステータス | 日付 |
|---|---|---|---|
| [0001](0001-record-architecture-decisions.md) | ADR で設計判断を記録する | Accepted | 2026-11-15 |
| [0002](0002-official-api-via-royaleapi-proxy.md) | 公式 API を RoyaleAPI のプロキシ経由で使う | Accepted | 2026-09-05 |
| [0003](0003-accumulate-in-local-sqlite.md) | 対戦履歴を定期的に収集し、ローカルの SQLite に蓄積する | Accepted | 2026-09-05 |
| [0004](0004-wilson-interval-and-min-matches.md) | 勝率に Wilson 信頼区間を付け、試合数の少ないものをグレー表示する | Accepted | 2026-09-05 |
| [0005](0005-group-decks-by-similarity.md) | 自デッキを類似度でグループ化する | Accepted | 2026-09-05 |
| [0006](0006-static-site-on-cloudflare-pages.md) | 静的サイトを Cloudflare Pages に公開する | Accepted | 2026-09-07 |
| [0007](0007-flask-and-chartjs.md) | Python ＋ Flask ＋ Chart.js のローカル Web ダッシュボードにする | Accepted | 2026-09-05 |

日付が 2026-09-05 のものは、旧要件定義書の作成日。それ以外は、その判断を含むリリースの日付（`CHANGELOG.md` より）。
