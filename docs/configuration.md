# 設定リファレンス

秘密情報の実際の値は書かない。雛形は `.env.example` を参照する。

## 環境変数

`.env` に書く。

| 名前 | 説明 | 型 | デフォルト値 | 必須 |
|---|---|---|---|---|
| `CR_API_TOKEN` | Supercell 公式 API のトークン（許可 IP は `45.79.218.79`。改行を入れず1行で書く） | 文字列 | なし | はい |
| `CR_PLAYER_TAG` | 自分のプレイヤータグ（`#` を付けたまま。O（オー）は使われず 0（ゼロ）） | 文字列 | なし | はい |
| `CR_USE_PROXY` | RoyaleAPI のプロキシ（`proxy.royaleapi.dev`）を経由するか。`false` なら `api.clashroyale.com` へ直接（許可 IP に自分の IP の登録が必要） | 真偽値 | `true` | いいえ |

## 設定ファイル

`config.yaml` に書く。

| 名前 | 説明 | 型 | デフォルト値 | 必須 |
|---|---|---|---|---|
| `analysis.min_matches` | 勝率をグレー表示（参考値扱い）にする試合数のしきい値 | 整数 | `20` | いいえ |
| `analysis.z_score` | 信頼区間の水準（95%）に対応する z スコア | 数値 | `1.96` | いいえ |
| `analysis.level_bucket_step` | レベル差を集計する刻み幅（0.125 の倍数） | 数値 | `0.25` | いいえ |
| `analysis.level_trend_window` | 未使用（v1.8.0 で傾向線を廃止。設定の互換のため残している） | 数値 | `0.5` | いいえ |
| `analysis.exclude_draws` | 引き分けを勝率の母数から除外するか | 真偽値 | `false` | いいえ |
| `analysis.target_battle_types` | 集計対象のバトル種別（`PvP` = ラダー、`pathOfLegend` = ランク戦）。ほかは記録だけ | 文字列の配列 | `[PvP, pathOfLegend]` | いいえ |
| `analysis.target_deck_selections` | 集計対象のデッキ選択方式（`collection` 以外は除外） | 文字列の配列 | `[collection]` | いいえ |
| `deck_grouping.similarity_threshold` | 8枚中この枚数以上が一致するデッキを同じグループとみなす | 整数 | `6` | いいえ |
| `collector.max_retries` | API リクエストの最大リトライ回数 | 整数 | `3` | いいえ |
| `collector.backoff_seconds` | リトライ時の初期待機秒数（指数バックオフ） | 数値 | `2` | いいえ |
| `collector.timeout_seconds` | リクエストのタイムアウト秒数 | 数値 | `20` | いいえ |
| `web.host` | ダッシュボードの待ち受けアドレス（`0.0.0.0` で LAN に公開） | 文字列 | `127.0.0.1` | いいえ |
| `web.port` | ダッシュボードのポート（起動時の `--port` で上書きできる） | 整数 | `8730` | いいえ |
| `publish.enabled` | 静的サイトを Cloudflare Pages へ公開するか | 真偽値 | `true` | いいえ |
| `publish.project_name` | Cloudflare Pages のプロジェクト名 | 文字列 | `cr-analyzer` | いいえ |
| `publish.branch` | Cloudflare Pages の本番ブランチ名（食い違うとプレビュー配信になる） | 文字列 | `production` | いいえ |
| `publish.history_limit` | 公開サイトの対戦履歴に載せる件数 | 整数 | `100` | いいえ |

「デフォルト値」はリポジトリの `config.yaml` の値。

### 設定を変えるとき

`config.yaml` で以下を調整できる。

- `min_matches` — 参考値扱いにする試合数のしきい値（既定20）
- `similarity_threshold` — 同一デッキとみなす一致枚数（既定6）
- `target_battle_types` — 集計対象のモード（既定はラダーとランク戦）
- `exclude_draws` — 引き分けを勝率の母数から除くか

> **引き分けについて**
> 現在のクラロワは、延長戦で決着がつかない場合タイブレーカーに入り、
> タワーのHPが減り続けて先に折れた側が負けとなる。両者のタワーHPが
> 完全に一致した場合のみ引き分けが成立するが、実質的にはほぼ起こらない
> （蓄積した153戦で0件）。そのためサマリー画面は通常「勝-敗」だけを表示し、
> **引き分けが1件でも記録されたときだけ「勝-敗-分」に切り替わる**。
> 引き分けは既定では勝率の母数から除かれる（`exclude_draws`）ため、
> 表示されている場合は対戦数と「勝＋敗」が一致しない点に注意する。
- `web.port` — ダッシュボードのポート（既定8730）
- `publish.enabled` / `publish.project_name` — 公開の有効化とプロジェクト名
- `publish.history_limit` — 公開サイトに載せる対戦履歴の件数（既定100）
- `publish.branch` — Cloudflare Pages の本番ブランチ名（既定 production）。wrangler は git リポジトリ内だとローカルのブランチ名を配信先として扱うため、食い違うとプレビュー配信になり公開URLに反映されない
- `level_bucket_step` — レベル差を集計する刻み幅（既定0.25、最小0.125）
- `level_trend_window` — 傾向線をならす範囲。v1.8.0 で傾向線を廃止したため**現在は未使用**

## コマンドラインオプション

| コマンド | オプション | 説明 | 型 | デフォルト値 | 必須 |
|---|---|---|---|---|---|
| `python -m src.collector.collect` | （なし） | 対戦を収集する | — | — | — |
| `python -m src.collector.collect` | `--init` | 初期化と初回収集 | — | — | いいえ |
| `python -m src.collector.collect` | `--update-cards` | カードマスタを更新する | — | — | いいえ |
| `python -m src.collector.collect` | `--update-card-stats` | カードの性能値を更新する | — | — | いいえ |
| `python -m src.collector.collect` | `--reload-names` | 日本語名の対応表を反映する | — | — | いいえ |
| `python -m src.collector.collect` | `--download-images` | カード画像を取得する | — | — | いいえ |
| `python -m src.collector.collect` | `--force-images` | 既存の画像も再取得する | — | — | いいえ |
| `python -m src.collector.collect` | `--optimize-images` | カード画像を最適化し直す | — | — | いいえ |
| `python -m src.collector.collect` | `--add-player TAG` | 追跡するプレイヤーを追加する | — | — | いいえ |
| `python -m src.collector.collect` | `--remove-player TAG` | プレイヤーを追跡から外す | — | — | いいえ |
| `python -m src.collector.collect` | `--list-players` | 登録済みのプレイヤーを一覧表示する | — | — | いいえ |
| `python -m src.collector.collect` | `--verbose` | 詳細なログを出力する | — | — | いいえ |
| `python -m src.web.app` | `--port` | ポート（`config.yaml` の `web.port` を上書き） | — | — | いいえ |
| `python -m src.web.app` | `--host` | 待ち受けアドレス（`web.host` を上書き） | — | — | いいえ |
| `python -m src.exporter.publish` | `--skip-collect` | 収集を行わない | — | — | いいえ |
| `python -m src.exporter.publish` | `--skip-upload` | アップロードを行わない | — | — | いいえ |
| `python -m src.exporter.publish` | `--verbose` | 詳細なログを出力する | — | — | いいえ |
| `python -m src.exporter.static_export` | `--rotate-secret` | 公開 URL の推測困難な部分を作り直す | — | — | いいえ |
| `python -m src.exporter.static_export` | `--clean` | 出力先を消してから書き出す | — | — | いいえ |
| `python scripts/doctor.py` | （なし） | 設定を診断する | — | — | — |
| `python scripts/doctor.py` | `--list-cards` | カードマスタの一覧を表示する（ゲーム内表記との照合用） | — | — | いいえ |
| `python scripts/doctor.py` | `--missing-names` | 日本語名が未登録のカードを表示する | — | — | いいえ |
| `python scripts/doctor.py` | `--check-levels` | 現在のデッキのレベル正規化を検証する | — | — | いいえ |
| `python scripts/backup.py` | `--keep` | 保持する世代数（既定 10） | — | — | いいえ |
| `scripts/register_task.ps1` | `-IntervalMinutes` | 収集の間隔（分。既定 60） | — | — | いいえ |
| `scripts/register_task.ps1` | `-DailyAt` | 毎日の実行時刻（指定すると `-IntervalMinutes` は使わない） | — | — | いいえ |
| `scripts/register_task.ps1` | `-TaskName` | タスク名（既定 `ClashRoyaleBattleAnalyzer`） | — | — | いいえ |
| `scripts/register_task.ps1` | `-NoWake` | スリープを解除して実行しない（既定では、スリープ中も収集するため解除して実行する） | — | — | いいえ |
| `scripts/register_task.ps1` | `-Publish` | 収集に加えて公開まで行う（`publish` を実行する） | — | — | いいえ |
