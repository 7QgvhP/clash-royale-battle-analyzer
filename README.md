# clash-royale-battle-analyzer

クラッシュロワイヤルの対戦履歴を自動で蓄積し、勝率・苦手カード・デッキ相性を分析するローカルツール。

- バージョン: 1.30.1

## 概要

公式 API が返す対戦履歴は直近の数十戦分だけなので、定期的に収集してローカルの SQLite に蓄積する。
蓄積したデータから、相手カードごとの勝率・苦手カード・自デッキごとの成績・カードレベル差の影響などを分析する。
結果は静的サイトとして Cloudflare Pages に公開し、PC の状態に関係なくスマートフォンから見られる。

## 主な機能

- 対戦履歴の自動収集と蓄積（毎日23時に、収集から公開まで）
- 相手カード別の勝率と、苦手カードの特定（Wilson 信頼区間つき）
- 自デッキ別の成績、環境（メタ）、カードレベル差の分析、カード育成の状況
- カードの性能と、呪文で倒せるユニットの一覧
- 複数プレイヤーの追跡
- 推測困難な URL の静的サイトとしての公開

## クイックスタート

前提：Windows、Python、Supercell の API トークンとプレイヤータグ（[docs/usage.md](docs/usage.md#インストール)）。

```bash
pip install -r requirements.txt
copy .env.example .env
python scripts/doctor.py
python -m src.collector.collect --init
python -m src.web.app
```

ブラウザで `http://127.0.0.1:8730` を開く。公開サイトと定期収集の設定は [docs/usage.md](docs/usage.md) を参照。

## ドキュメント

| ファイル | 内容 |
|---|---|
| [docs/spec.md](docs/spec.md) | 仕様（目的、機能要件、分析ロジック、画面、データモデル、技術的制約） |
| [docs/usage.md](docs/usage.md) | 使用方法（セットアップ、API トークンの取得、公開の設定、各画面の見方） |
| [docs/architecture.md](docs/architecture.md) | 設計（全体構成、ディレクトリ、外部 API、性能値の出典） |
| [docs/development.md](docs/development.md) | 開発者向けガイド（確認方法、保守の手順） |
| [docs/configuration.md](docs/configuration.md) | 設定リファレンス（`.env`、`config.yaml`、コマンドラインオプション） |
| [docs/adr/](docs/adr/README.md) | 設計判断記録（ADR） |
| [CHANGELOG.md](CHANGELOG.md) | 変更履歴 |

## ライセンス

TODO(要確認): LICENSE ファイルがなく、ライセンスは定められていない。
