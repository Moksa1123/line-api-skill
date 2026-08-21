# line-api-skill

**LINE の API を推測するのはやめて、調べよう。**

LINE Platform のドキュメント全体を検索可能なデータベースに変換する
[Agent Skill](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)。
AI アシスタントが記憶ではなく仕様に基づいて答えるようになります。

<p>
  <img src="https://img.shields.io/badge/endpoints-121-success?style=flat-square" alt="121 endpoints">
  <img src="https://img.shields.io/badge/fields-1584-blue?style=flat-square" alt="1584 fields">
  <img src="https://img.shields.io/badge/dataset-3675%20rows-orange?style=flat-square" alt="3675 rows">
  <img src="https://img.shields.io/badge/platforms-8-9cf?style=flat-square" alt="8 platforms">
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-0-brightgreen?style=flat-square" alt="zero dependencies">
</p>

```
121 エンドポイント · 1,584 のリクエスト/レスポンス項目 · 295 のレスポンス項目
233 のエラーコード · 247 の webhook 項目 · 136 の Flex コンポーネント · 44 の URL スキーム
58 バージョンにわたる 35 の LIFF API · 80 のモバイル SDK 型 · 92 件の公式 FAQ
```

[English](README.md) · [繁體中文](README.zh-TW.md) · 日本語 · [한국어](README.ko.md)

---

## 解決したい問題

LINE の API は、小さなミスの代償が追いにくい形で返ってきます。

`chatBarText` の上限は 14 文字。カルーセルの各カラムの `text` は 120 文字まで
——ただしサムネイルかタイトルを付けた瞬間 60 文字に縮みます。リッチメニューの画像は
`api.line.me` ではなく `api-data.line.me` にアップロードします。replyToken は 1 回きり、
1 分で失効します。1 つのカルーセル内の bubble は幅を揃える必要があります。

どれも推測できるものではなく、記憶で答えるアシスタントは自信を持って間違えます。
このスキルは「まず調べる」を徹底させます。

## クイックスタート

```bash
git clone https://github.com/Moksa1123/line-api-skill
cd line-api-skill
python tools/install-skill.py claude-code --global
```

あとは普通の言葉で頼むだけです：

```
あなた：  注文照会に Flex カードで返信する LINE bot を作って

アシスタント：（エンドポイント・Flex の構造・項目の上限を調べ、
               コードを書き、送信前に JSON をオフライン検証する）
```

## インストール

```bash
python tools/install-skill.py --list                   # 対応プラットフォーム一覧
python tools/install-skill.py claude-code --global
python tools/install-skill.py cursor                   # 現在のプロジェクトへ
python tools/install-skill.py claude-ai --to ./build    # アップロード用 zip を生成
```

8 プラットフォーム対応 —— Claude Code、Claude.ai、Cursor、Codex CLI、Gemini CLI、
Devin Desktop（旧 Windsurf）、GitHub Copilot、Continue。スキルの読み込み方式に応じて
3 つの形式でインストールします：ディレクトリ丸ごと、単一のルールファイルに平坦化、
または Web アップロード用の zip。アップグレード時は前バージョンの残骸を削除します
——去年の間違ったデータを今年の正しいデータの隣に残すインストーラーは、
無いほうがましだからです。

## 使い方

通常、ツールを自分で実行する必要はありません。スキルがアシスタントに手順を教えます：

```
1. まず調べる      search.py     エンドポイント、項目、上限、enum、エラー、FAQ
2. JSON を書く     （アシスタント）調べた構造そのままに、推測しない
3. オフライン検証  validate.py   型、必須、タイポ、enum、上限、非推奨要素
4. それから送信    lineapi.py    正しいホスト、正しいヘッダー
```

手動で使うこともできます：

```bash
python scripts/search.py "carousel"                  # 検索ドメインを自動判定
python scripts/search.py "get bot info" --domain response
python scripts/validate.py message.json --as push
python scripts/signature.py verify --secret <s> --body-file b.json --signature <sig>
python scripts/lineapi.py info
```

バリデーターは問題箇所のパスを直接示します：

```
❌ $.contents.body.layout               必須プロパティ layout がありません
❌ $.contents.body.contents[0].weight   'extra-bold' は不正です。regular, bold を使用
⚠️  $.template.columns                  カラム間で action の数が揃っていません
```

## カバー範囲

| 領域 | 調べられること |
|---|---|
| Messaging API | 97 エンドポイント、レート制限、リトライキー、送信上限、統計 |
| メッセージオブジェクト | 11 種類、クイックリプライ、4 種のテンプレート、9 種の action |
| Flex Message | コンテナ、9 コンポーネント、全プロパティ、サイズ上限 |
| リッチメニュー | オブジェクト構造、画像仕様、エイリアス、ユーザー個別リンク |
| Webhook | 20 イベント、型付き 247 項目、署名検証 |
| LINE Login | OAuth 2.0 + OIDC、スコープ、ID トークン検証 |
| LIFF | 35 API、導入バージョン、Tree-shaking 対応モジュール |
| LINE MINI App | 認証済み／未認証の違い、サービスメッセージ、アプリ内課金 |
| URL スキーム | 44 スキームと、よく踏む 3 つのプラットフォーム制限 |
| モバイル SDK | iOS / Android の 80 型、公式リファレンスへのリンク付き |

さらに LINE 公式用語 57 語、FAQ 92 件、整理済みのトラブルシューティング、
提供終了機能の一覧（LINE Notify は 2025-03-31 に終了）も収録。
アシスタントが死んだ API を勧めることはありません。

## ツール

| ツール | 内容 |
|---|---|
| `search.py` | 25 ドメインを BM25 検索。中国語クエリは英語用語に自動展開 |
| `validate.py` | メッセージ / Flex のオフライン検証：型、必須、タイポ、enum、上限 |
| `signature.py` | webhook 署名、チャネルアクセストークン（純 Python の RS256 JWT 実装込み） |
| `lineapi.py` | 依存ゼロの Messaging API クライアント。ホストを自動で振り分け |
| `test_line.py` | オフライン 43 項目 + ライブ 6 項目 |

## データの作り方

```
https://developers.line.biz/llms.txt        github.com/line/line-openapi
        ↓ tools/fetch_sources.py                    ↓
231 の公式ページ（多くは .md 版あり）          10 の OpenAPI 仕様
        ↓ tools/build_dataset.py
line-api/data/*.csv    ← 相互検証：ドキュメントのエンドポイント ⊇ OpenAPI のエンドポイント
```

4 つの独立した検査。いずれも実際に誤りを検出した実績があります：

| 検査 | 内容 |
|---|---|
| `test_line.py` | データ整合性、検索、バリデーター、署名、JWT |
| `audit_coverage.py` | ドキュメントに書かれた項目がすべてデータセットに入ったか |
| `check_links.py` | 全ドキュメント URL が有効か（SPA の偽 200 も検出） |
| `check_docs.py` | README の数値が実データと一致しているか |

取得したページは `.docs-cache/` に置かれ、**git 管理外・非公開**です
—— その内容は LY Corporation に帰属します。本リポジトリが公開するのは、
そこから導出したデータセットと自ら書いた説明のみです。

最新ドキュメントに追従するには：

```bash
python tools/fetch_sources.py
python tools/build_dataset.py
python tools/audit_coverage.py
python tools/check_links.py --md
python tools/check_docs.py
python line-api/scripts/test_line.py
```

## ライセンス

本リポジトリのコードは MIT。

LINE、LINE Messaging API、LIFF、LINE MINI App は LY Corporation の商標です。
本プロジェクトは LY Corporation とは無関係であり、データセットは同社の公開ドキュメントと
公開 OpenAPI 仕様を整理したものです。
