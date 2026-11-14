# 設計

## 全体構成

> 旧要件定義書の図をそのまま移した。現在の運用では、収集は毎日23時に1回（「データの流れ」を参照）で、ダッシュボードのポートは `8730`（`config.yaml` の `web.port`）。図の「1時間おき」「5000」は作成時点の値。

```
[Supercell公式API]
        |
        | HTTPS（proxy.royaleapi.dev 経由）
        v
[収集スクリプト collect.py]  <-- Windowsタスクスケジューラが1時間おきに起動
        |
        | 差分をUPSERT
        v
[SQLite データベース data/battles.db]
        |
        | 集計クエリ
        v
[分析モジュール analysis/]
        |
        v
[Flask Webダッシュボード app.py]  <-- ブラウザ http://127.0.0.1:5000
```

収集と閲覧は完全に分離する。収集は無人で動き続け、ダッシュボードは見たいときだけ起動する。

## ディレクトリ構成と各モジュールの責務

```
clash-royale-battle-analyzer/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── config.yaml               # 最低試合数・類似度しきい値・対象モード等
├── docs/
│   └── spec.md ほか         # ドキュメント一式（旧 requirements.md・setup-*.md を統合）
├── src/
│   ├── api/
│   │   ├── client.py         # APIクライアント（プロキシ切替・リトライ）
│   │   └── models.py         # レスポンスのパース
│   ├── db/
│   │   ├── schema.sql        # テーブル定義
│   │   └── repository.py     # DBアクセス
│   ├── collector/
│   │   └── collect.py        # 収集エントリポイント
│   ├── analysis/
│   │   ├── stats.py          # 勝率・Wilson信頼区間
│   │   ├── cards.py          # 相手カード別集計
│   │   ├── decks.py          # デッキ類似度グループ化
│   │   └── levels.py         # レベル差分析
│   ├── web/
│   │   ├── app.py            # Flaskアプリ
│   │   ├── templates/
│   │   └── static/           # style.css / app.js（画面共通の処理）/ アイコン
│   └── data/
│       └── card_names_ja.json  # 英語名→日本語名 対応表
├── data/
│   ├── battles.db            # SQLite（Git管理外）
│   └── logs/
└── scripts/
    ├── register_task.ps1     # タスクスケジューラ登録
    ├── unregister_task.ps1   # 登録解除
    ├── doctor.py             # 設定診断
    └── backup.py             # DBバックアップ
```

## データの流れ

公開サイトのみで運用する構成を標準とする。**ローカルのダッシュボードは起動しなくてよい。**

```
[PC] 毎日23時: 収集 → 静的サイトの書き出し → アップロード
                                    ↓
[Cloudflare Pages] ← あなたと友人のスマートフォンからいつでも閲覧
```

### ダッシュボードのコードは削除できない

`python -m src.web.app` を起動しない運用でよいが、**Flaskアプリのコード自体は静的サイトの
生成に使われている**（`static_export.py` が内部でテンプレートを描画するため）。
起動しなければ動作もリソース消費も無いので、そのまま残しておくこと。

### 公開サイトでできないこと

| 操作 | 代替手段 |
|---|---|
| 対戦履歴の全件閲覧 | `config.yaml` の `publish.history_limit` を増やす。または一時的にダッシュボードを起動する |

閲覧に必要な機能はすべて公開サイト側に揃っている。書き込みを伴う操作は持たない
（閲覧者が操作できず、所有者だけが使える非対称な機能になるため）。

デッキの呼び名は、コストの高いカード3枚から自動で組み立てている。
例:「メガナイト・インフェルノドラゴン・スケルトンバレル ほか」

## 外部依存

| 依存 | 用途 |
|---|---|
| Supercell 公式 API（RoyaleAPI のプロキシ経由） | 対戦履歴・プレイヤー・カードの取得（[ADR 0002](adr/0002-official-api-via-royaleapi-proxy.md)） |
| SQLite（`data/battles.db`） | 対戦履歴の蓄積（[ADR 0003](adr/0003-accumulate-in-local-sqlite.md)） |
| Flask、Chart.js | ダッシュボードと静的サイトの描画（[ADR 0007](adr/0007-flask-and-chartjs.md)） |
| Cloudflare Pages（wrangler） | 静的サイトの公開（[ADR 0006](adr/0006-static-site-on-cloudflare-pages.md)） |
| Clash Royale Wiki（MediaWiki） | カードの性能値の取得 |
| requests、python-dotenv、PyYAML | HTTP、`.env`、`config.yaml` |

### 外部APIの使用範囲

| 用途 | エンドポイント | 頻度 |
|---|---|---|
| 対戦履歴 | `GET /v1/players/{tag}/battlelog` | 1時間おき |
| プロフィール | `GET /v1/players/{tag}` | 1時間おき |
| カードマスタ | `GET /v1/cards` | 初回および手動更新時のみ |

- ベースURL（プロキシ経由）: `https://proxy.royaleapi.dev/v1`
- ベースURL（直接）: `https://api.clashroyale.com/v1`
- 認証: `Authorization: Bearer <APIトークン>`
- **`User-Agent` の設定は必須**（§2.4 参照）。未設定だとCloudflareに遮断される
- プレイヤータグの `#` はURLエンコードして `%23` とする

### APIから取得できるデータ

公式APIで取得できる内容の一覧。**本ツールが実際に使っているのは一部だけ**なので、
分析軸を増やしたくなったときの参照用として記載する。すべて 2026-09-08 に実測して確認した。

#### エンドポイント一覧

| エンドポイント | 内容 | 本ツールでの利用 |
|---|---|---|
| `/players/{tag}` | プレイヤー情報 | **利用中**（名前・トロフィー） |
| `/players/{tag}/battlelog` | 直近の対戦履歴（約30件） | **利用中**（中核データ） |
| `/players/{tag}/upcomingchests` | 次に出る宝箱（15件） | 未使用 |
| `/cards` | カードマスタ（123枚＋タワー4種） | **利用中**（名前・画像・レアリティ）。HP・ダメージ等の性能値は返らない |
| `/clans/{tag}` | クラン情報 | 未使用 |
| `/clans/{tag}/members` | クランメンバー一覧（最大50人） | 未使用 |
| `/clans/{tag}/currentriverrace` | 進行中のクラン戦 | 未使用 |
| `/clans/{tag}/riverracelog` | クラン戦の記録 | 未使用 |
| `/clans?name=...` | クラン検索 | 未使用 |
| `/locations` | 地域一覧（262件） | 未使用 |
| `/locations/{id}/rankings/players` | 地域別プレイヤーランキング | 未使用 |
| `/locations/{id}/rankings/clans` | 地域別クランランキング | 未使用 |
| `/globaltournaments` | 開催中のグローバルトーナメント | 未使用 |
| `/tournaments?name=...` | トーナメント検索 | 未使用 |
| `/leaderboards` | リーダーボード一覧（30件） | 未使用 |

`/clans/{tag}/warlog` は 404 を返す（旧クラン戦の廃止に伴い提供終了）。
`/challenges` も 404 で、現在は提供されていない。

#### プレイヤー情報の中身（38項目）

```
tag / name / expLevel / kingTowerLevel / collectionLevel
trophies / bestTrophies / legacyTrophyRoadHighScore
wins / losses / battleCount / threeCrownWins / currentWinLoseStreak
challengeCardsWon / challengeMaxWins
tournamentCardsWon / tournamentBattleCount
donations / donationsReceived / totalDonations / clanCardsCollected / warDayWins
starPoints / expPoints / totalExpPoints
arena（現在のアリーナ）
leagueStatistics（シーズン成績）
currentPathOfLegendSeasonResult / lastPathOfLegendSeasonResult / bestPathOfLegendSeasonResult
    → ランク戦のリーグ番号・トロフィー・順位
badges[108]        獲得バッジと進捗
achievements[12]   実績と進捗
cards[117]         所持カードとレベル・枚数
supportCards[2]    所持タワートループ
currentDeck[8] / currentDeckSupportCards[1]   現在のバトルデッキ
currentFavouriteCard   お気に入りカード
progress           シーズン別の進捗
```

#### 対戦1件の中身

**対戦そのもの**

```
type              PvP（ラダー）/ pathOfLegend（ランク戦）/ trail（イベント）など
battleTime        対戦日時（UTC）
gameMode          ゲームモードの id と name
arena             アリーナの id / name / rawName
deckSelection     collection（自分のデッキ）/ draftCompetitive（ドラフト）
isLadderTournament / isHostedMatch  フラグ
leagueNumber      ランク戦のリーグ番号
eventTag          イベント戦のタグ（イベント時のみ）
modifiers         イベント戦の特殊ルール（イベント時のみ）
```

**参加者ごと**（`team[]` と `opponent[]`。2v2では2要素になる）

```
tag / name                 プレイヤータグと名前
clan                       所属クラン
startingTrophies           対戦前のトロフィー（イベント戦では返らない）
trophyChange               トロフィー増減（同上）
crowns                     獲得クラウン数
kingTowerHitPoints         キングタワーの残りHP
princessTowersHitPoints[]  プリンセスタワーの残りHP
elixirLeaked               エリクサーの漏れ量
globalRank                 世界順位（上位者のみ）
cards[8]                   使用デッキ
supportCards[]             タワートループ
```

**カード1枚ごと**

```
id / name                  カードIDと英語名
level / maxLevel           レベル（レアリティ基準）と段数
maxEvolutionLevel          進化可能なら1以上
evolutionLevel             進化・ヒーローを装備している場合のみ付く（本ツールは 1=進化、2=ヒーローとみなす）
rarity                     common / rare / epic / legendary / champion
elixirCost                 コスト
iconUrls.medium            カード画像
iconUrls.evolutionMedium   進化版の画像
iconUrls.heroMedium        ヒーロー版の画像
```

#### 本ツールが使っていない主なデータ

分析軸を増やす余地として、以下がある。

| データ | 使える分析の例 |
|---|---|
| `elixirLeaked` | エリクサーを溢れさせた試合の勝率 |
| `princessTowersHitPoints` | 惜敗か大敗かの判別（フェーズ2で予定） |
| `clan` | クラン仲間との対戦成績 |
| `cards`（所持一覧） | 未所持カードや低レベルカードの把握 |
| `leagueStatistics` | シーズンごとの成績比較 |
| `currentPathOfLegendSeasonResult` | ランク戦のリーグ推移 |
| `badges` / `achievements` | 進捗の可視化 |
| ランキング系 | 上位プレイヤーの使用デッキ傾向 |

なお `raw_json` 列に対戦のJSONを丸ごと保存しているため、**上記のうち対戦に含まれる項目は
後から遡って集計できる**（対戦履歴はAPIから再取得できないため、あえて全部残している）。

#### 取得できないもの

- **運用開始より前の対戦履歴**（`battlelog` は直近約30件のみ）
- カード名の日本語表記（`Accept-Language` などの言語指定に非対応。実測で確認済み）
- リプレイの内容、対戦中の操作ログ
- 他プレイヤーの非公開情報（そもそも公開情報しか返さない）

### カードの性能値の出典と計算

#### 性能値はどこから来ているか

**公式APIはカードの性能値を提供していない。** `/cards` が返すのは名前・レアリティ・
コスト・画像・最大レベルだけで、HP・ダメージ・射程は含まれない。

性能値はゲーム本体のデータファイルに入っているが、そこからの抽出は Supercell の
利用規約 §1.1 が禁じている（"obtain any information from the Service or any Supercell
game using any method not expressly permitted by Supercell"）。**本ツールはこの方法を
採らない。**

そのため、内容が **CC BY-SA** で再利用を許諾されており、かつ公開された MediaWiki API で
取得できる [Clash Royale Wiki](https://clashroyale.fandom.com/) を情報源としている。
ライセンス上の義務として、各カードのページに出典・取得日・元ページへのリンクを表示する。

有志が編集する資料のため、値が最新でない可能性がある。画面のリンクから元ページを開いて
照合できるようにしてあるのはそのためである。

#### 数値の計算方法

wiki は性能値を**レベル11基準**で持っている。各レベルの値は

```
そのレベルの値 = 基準値 × 1.1^(レベル - 11)
```

で算出する。これは wiki 自身がレベル別の表を作るのに使っている式と同じなので、
リンク先の表と本ツールの表示は一致する。丸めの都合で ±1 程度ずれることがある。

ただし一部のカードは、レベル別の表に数値が**直接書かれている**列を持つ（式で変数を
参照していない）。バランス調整のとき、表の数値だけが直されて変数が古いまま残ることが
あるため、直書きの列は基準レベル（11）の行から読み取り、変数より優先する。どの列を
どの項目に当てるかは `src/data/card_stats_columns.json` に書く。

攻撃速度の変数を持たないカードは、基本情報の表（Hit Speed）の値を使う。

射程・移動速度・展開時間などはレベルで変わらないため、そのまま「基本情報」に出す。
