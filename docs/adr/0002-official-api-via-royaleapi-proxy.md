# 0002. 公式 API を RoyaleAPI のプロキシ経由で使う

- ステータス: Accepted
- 日付: 2026-09-05（旧要件定義書の作成日）

## 背景（Context）

公式 API のトークンは、発行時に登録したグローバル IP アドレスに紐づき、登録外の IP からのリクエストは 403 で拒否される。家庭用回線は IP が変動しうるため、直接アクセスでは突然すべての機能が止まる。

## 決定内容（Decision）

RoyaleAPI の公式プロキシ `proxy.royaleapi.dev` を経由する（`.env` の `CR_USE_PROXY=true` が既定）。トークンにはプロキシ側の固定 IP `45.79.218.79` を登録する。すべてのリクエストに User-Agent `clash-royale-battle-analyzer/1.0.0` を付ける。

## 理由と検討した代替案（Consequences / Alternatives）

- 自宅の IP が変わっても影響を受けない。
- プロキシの前段の Cloudflare は、既定の User-Agent（`Python-urllib/3.12` など）を Error 1010 で遮断するため、User-Agent の設定が必須になる。403 のうち `error_code` 1010 は、トークンの不正と区別して案内する。
- 検討した代替案: `api.clashroyale.com` への直接アクセス（`CR_USE_PROXY=false` で今も選べる。許可 IP に自分の IP の登録が必要）。
