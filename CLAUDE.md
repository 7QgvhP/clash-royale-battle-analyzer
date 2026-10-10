# clash-royale-battle-analyzer

共通ルール（コミットの書式、バージョン、タグ、CHANGELOG）は、ここには書きません。このファイルは、このリポジトリ固有の事実だけを書きます。

## 概要
クラッシュロワイヤルの対戦履歴を自動で蓄積し、勝率・苦手カード・デッキ相性を分析するローカルツールです。収集した結果は、ローカルのダッシュボードと、公開用の静的サイトで見られます。

## 構成と技術
- Python / Flask / SQLite
- `src/api/`: 公式 API の呼び出し
- `src/collector/`: 対戦の収集（`python -m src.collector.collect`）
- `src/db/`: SQLite の保存処理
- `src/analysis/`: 集計・分析
- `src/web/`: ダッシュボード（Flask。`templates/`、`static/`）
- `src/exporter/`: 静的サイトの書き出しと公開
- `scripts/`: 診断（`doctor.py`）、バックアップ、タスクスケジューラへの登録・解除（`.ps1`）
- `docs/requirements.md`: 要件定義書
- `config.yaml`: 設定。`.env`: 秘密情報（雛形は `.env.example`）

## ビルド・テストの手順
自動テストはありません。分析ロジックを変更したときは、集計値が変わっていないことを、次で確認します。
```bash
python -m tests.check_baseline          # tests/baseline.json と比較する
python -m tests.check_baseline --update # 基準値を更新する（集計の仕様を変えたときだけ）
```
- `check_baseline` は、設定と、収集済みのデータベースを読みます。データベースは Git 管理外なので、データのある手元の環境でしか実行できません。自動対応の専用クローンでは実行できないので、完了報告に「確認できていない点」として書いてください。
- ※ 自動対応でコマンドを実行するには、dev-hub の `tools\claude-auto\config.ps1` の `$ExtraTools` で許可が必要です。

## バージョンの記録場所
ソースコードには、バージョンの定数がありません。リリースのときに、次をすべて同じコミットで更新します。
- `README.md` の冒頭の「**バージョン**: vX.Y.Z」
- `docs/requirements.md` の冒頭の「**バージョン**: vX.Y.Z」
- `CHANGELOG.md` の見出し（`## [X.Y.Z] - YYYY-MM-DD`）

## 注意事項
- `.env`（API トークン、プレイヤータグ）、`.wrangler/`、`data/` の収集データは、Git 管理外です。コミットしないでください。
- 変更内容は `CHANGELOG.md` だけに書きます。`docs/requirements.md` には、更新履歴を書きません。
- `CHANGELOG.md` の箇条書きは `-` で、文体は「だ・である」です。
