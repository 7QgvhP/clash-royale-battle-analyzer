# clash-royale-battle-analyzer

コミットの書式、バージョン、タグ、CHANGELOG の規約（全プロジェクト共通）は、ここには書かない。このファイルは、このリポジトリ固有の事実だけを書く。

## 概要
クラッシュロワイヤルの対戦履歴を自動で蓄積し、勝率・苦手カード・デッキ相性を分析するローカルツール。結果は、ローカルのダッシュボードと、Cloudflare Pages に公開する静的サイトで見られる。

## 技術スタックと主要ディレクトリ
- Python / Flask / Chart.js / SQLite。依存は `requirements.txt`。
- `src/api/`（API・Wiki の取得）、`src/collector/`（収集）、`src/db/`（保存）、`src/analysis/`（集計・分析）、`src/web/`（ダッシュボード）、`src/exporter/`（静的サイトの書き出しと公開）、`src/data/`（日本語名・性能値の対応表）
- `scripts/`: 診断（`doctor.py`）、バックアップ、タスクスケジューラへの登録・解除（`.ps1`）
- `config.yaml`: 設定。`.env`: 秘密情報（雛形は `.env.example`）
- 詳細は [docs/architecture.md](docs/architecture.md)

## コマンド
```bash
python -m tests.check_baseline          # 集計値の回帰確認（収集済みのデータベースが必要）
python -m src.collector.collect --help  # 収集のオプション
python -m src.web.app                   # ダッシュボード（http://127.0.0.1:8730）
```
- ビルド: なし。自動テスト: なし。lint: なし。
- `check_baseline` は、データのある手元の環境でしか実行できない。自動対応の専用クローンでは実行できないので、完了報告に「確認できていない点」として書く。
- ※ 自動対応でコマンドを実行するには、dev-hub の `tools\claude-auto\config.ps1` の `$ExtraTools` で許可が必要。

## コーディング規約
- コメント・docstring・メッセージは日本語。
- 分析ロジックを変えたときは、`check_baseline` で集計値の変化を確かめる。
- `CHANGELOG.md` の箇条書きは `-` で、文体は「だ・である」。変更内容は `CHANGELOG.md` だけに書き、`docs/spec.md` には更新履歴を書かない。

## バージョンの記録場所
ソースコードには、バージョンの定数がない。リリースのときに、次をすべて同じコミットで更新する。
- `README.md` の冒頭の「バージョン」の行
- `CHANGELOG.md` の見出し（`## [X.Y.Z] - YYYY-MM-DD`）

GitHub Releases は作らない（配布物がないため、タグだけでリリースとする）。

## ドキュメント更新ルール
今後の開発で、次の変更を行う際は、同じ作業の中で該当ドキュメントも更新すること。
- 機能の追加・変更・削除 → `docs/spec.md`、`docs/usage.md`、`CHANGELOG.md`
- 構成や設計の変更 → `docs/architecture.md`
- 設定項目の追加・変更 → `docs/configuration.md`
- 技術選定や設計方針を変える判断 → 新しい ADR を `docs/adr/` に追加する（既存の ADR は書き換えず、ステータスを Superseded にして、新しい ADR から参照する）
- バージョンを上げるとき → `CHANGELOG.md` に新しいバージョンの節（`## [X.Y.Z] - YYYY-MM-DD`）を追加し、「バージョンの記録場所」のファイルをすべて同じコミットで更新する

## 注意事項
- `.env`（API トークン、プレイヤータグ）、`.wrangler/`、`data/` の収集データは、Git 管理外。コミットしない。
- 公開サイトは、毎日23時の定期タスク（`ClashRoyaleBattleAnalyzer`）が、開発用クローンのコードで作る。`git pull` しないと、push した変更は公開サイトに反映されない。
- 新カードが追加されたら、`src/data/card_names_ja.json` の日本語名を足す（[docs/development.md](docs/development.md#保守)）。
