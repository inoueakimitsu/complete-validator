# CompleteValidator

`rules/` 内の Markdown ルールに基づく AI スタイルチェックを実行する Claude Code Plugin です。
git commit 時の自動チェック (PreToolUse hook) と、任意のタイミングでのオンデマンドチェックの 2 つのモードをサポートします。
検出した違反は systemMessage として Claude Code エージェントに返します。

## インストール

### ローカルパスからインストール

```bash
# マーケットプレースとして登録
/plugin marketplace add ../complete-validator

# プラグインをインストール
/plugin install complete-validator@complete-validator --scope project
```

### GitHub からインストール

```bash
/plugin marketplace add <owner>/complete-validator
/plugin install complete-validator@complete-validator --scope project
```

### その他の Git ホスト（GitLab、Bitbucket、自前サーバー）からインストール

```bash
/plugin marketplace add https://gitlab.com/<org>/complete-validator.git
/plugin install complete-validator@complete-validator --scope project
```

`--scope` は `project`（チーム共有）、`user`（全プロジェクト）、`local`（個人・gitignore 対象）から選択できます。

## アーキテクチャ

```
Claude Code エージェント
  │
  │  Bash ツール呼び出し (git commit ...)
  │
  ▼
hooks/hooks.json (PreToolUse: Bash)
  │
  │  stdin: {"tool_input": {"command": "git commit ..."}}
  │
  ▼
scripts/check_style.sh
  │  - tool_input.command が "git commit" で始まるか判定
  │  - git commit 以外 → exit 0 (出力なし = 許可、数十ms)
  │  - git commit → check_style.py --staged --project-dir に委譲
  │
  ▼
scripts/check_style.py --staged --project-dir "$PLUGIN_DIR"
  │  1. git diff --cached で staged diff 取得
  │  2. git diff --cached --name-only --diff-filter=d で全 staged ファイル取得
  │  3. rules/*.md をフロントマター付きで読み込み、ファイルとルールをマッチング
  │  4. cache key = sha256(diff + rules) → キャッシュヒットなら即返却
  │  5. git show :<path> で staged 版ファイル内容取得
  │  6. プロンプト構築 (ルールとファイルの対応関係を明示 + diff)
  │  7. claude -p でチェック実行 (CLAUDECODE 環境変数を除去してネスト検出回避)
  │  8. 結果を {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","additionalContext":"..."}} として stdout に出力
  │  9. キャッシュ保存
  │
  ▼
Claude Code エージェント
  - systemMessage として違反内容を受け取る
  - エージェントが違反を修正してから再度 commit する
```

## Plugin ファイル構成

```
complete-validator/
├── .claude-plugin/
│   ├── marketplace.json         # マーケットプレース定義 (配布用)
│   └── plugin.json              # Plugin メタデータ
├── git-hooks/
│   └── pre-push                 # pre-push hook (clone 後に .git/hooks/ へコピー)
├── hooks/
│   └── hooks.json               # PreToolUse hook 設定 (インストール時に自動登録)
├── skills/
│   └── complete-validator/
│       └── SKILL.md             # スキル定義 (ルール概要・使い方)
├── rules/
│   └── *.md # 各種ルール
├── scripts/
│   ├── check_style.sh           # hook エントリポイント (シェルラッパー)
│   └── check_style.py           # チェック本体
├── .gitignore
└── CLAUDE.md
```

## 各ファイルの役割

### `.claude-plugin/marketplace.json`

マーケットプレース定義です。`/plugin marketplace add` でこのリポジトリを登録する際に参照されます。`source` フィールドでプラグイン本体の位置を `"./"` （リポジトリルート）として指定しています。

### `.claude-plugin/plugin.json`

Plugin のメタデータを定義します。`name` がプラグイン名として使用され、スキルは `/complete-validator:complete-validator` で呼び出せます。

### `hooks/hooks.json`

- `PreToolUse` の `Bash` matcher で全 Bash ツール呼び出し時に発火します
- `${CLAUDE_PLUGIN_ROOT}/scripts/check_style.sh` を実行します
- Plugin インストール時に自動登録されます
- タイムアウトは 120 秒です

### `scripts/check_style.sh`

- stdin から hook JSON を受け取り、`tool_input.command` を python3 で抽出します
- `git commit` で始まるコマンドのみ `check_style.py` に委譲し、それ以外は即 exit 0 です
- `CLAUDE_PLUGIN_ROOT` 環境変数があれば使用し、なければスクリプト位置から相対解決します (スタンドアロン互換)
- jq 非依存です (python3 -c で JSON パース)

### `scripts/check_style.py`

主要な処理フローです。2 つのモードをサポートします。

- **working モード** (デフォルト) — `git diff` で unstaged な変更をチェック。オンデマンド実行用
- **staged モード** (`--staged`) — `git diff --cached` で staged な変更をチェック。commit hook 用

**CLI:**
```bash
python3 scripts/check_style.py                    # working モード (デフォルト)
python3 scripts/check_style.py --staged            # staged モード
python3 scripts/check_style.py --project-dir DIR   # ルール/キャッシュのベースディレクトリを指定
```

**処理フロー:**

1. **diff 取得** — working: `git diff` / staged: `git diff --cached`。空なら exit 0 (許可)
2. **変更ファイル一覧取得** — `git diff --name-only --diff-filter=d` (staged 時は `--cached` 付き)
3. **ルール読み込み** — `rules/` 内の全 `.md` ファイルをフロントマター付きで読み込み、`applies_to` パターンで対象ファイルをマッチング
4. **キャッシュ確認** — `sha256(diff + rules)` をキーに `.complete-validator/cache.json` を参照
5. **ファイル内容取得** — staged: `git show :<path>` / working: ファイルを直接読み込み
6. **プロンプト構築** — ルールとファイルの対応関係を明示したプロンプトを構築
7. **`claude -p` 実行** — `CLAUDECODE` 環境変数を除去して実行 (ネストセッション検出を回避)
8. **結果出力** — `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","additionalContext":"[Style Check Result]\n..."}}` を stdout に出力
9. **キャッシュ保存** — 結果を cache.json に書き込み

**`--project-dir` の自動検出:** 省略時は `git rev-parse --show-toplevel` で検出します。

設計上の重要な判断です。

- **常に `"permissionDecision": "allow"`** — commit をブロックしません。違反は additionalContext でエージェントに伝え、エージェントが修正します
- **エラー時も allow** — `claude -p` のタイムアウト (90 秒) や失敗時は警告メッセージ付きで allow します
- **キャッシュ** — 同じ diff + ルールの組み合わせなら `claude -p` を呼ばず即座にキャッシュ返却します

## ルールの追加方法

`rules/` ディレクトリに `.md` ファイルを追加します。ファイルはアルファベット順に読み込まれます。

ルールファイルのフォーマットです。

- 先頭に YAML フロントマターで `applies_to` を指定します (必須)
- `applies_to` にはファイル名の glob パターンのリストを指定します
- `## ` 見出しでルールを区切ります
- 各ルールにルール名、説明、Bad/Good の具体例を記載します
- 複数ファイルに分割できます (例: `rules/python_style.md`、`rules/naming.md`)
- `applies_to` フロントマターがないルールファイルはスキップされ、警告メッセージが出力されます

フロントマターの例です。

```markdown
---
applies_to: ["*.py"]
---
# Python Style Rules
...
```

```markdown
---
applies_to: ["*.py", "*.md"]
---
# Japanese Comment Style Rules
...
```

ルールを変更するとキャッシュキーが変わるため、次回の commit 時に自動的に再チェックが走ります。

## キャッシュ

- 保存場所は `.complete-validator/cache.json` です
- キーは `sha256(diff + ルール全文)` です
- diff またはルールが変わると自動的にキャッシュミスになります
- キャッシュクリアは `rm -f .complete-validator/cache.json` です
- `.gitignore` により Git 管理外です

## 前提条件

- Python 3.10 以上 (`list[str]`、`dict[str, str]` 構文を使用)
- Claude Code CLI (`claude` コマンド) がインストール済み・認証済み
- Git

## 手動テスト

### commit hook 経由 (staged モード)

```bash
# git commit 以外のコマンド → 即 exit 0 (出力なし)
echo '{"tool_input":{"command":"git status"}}' | bash scripts/check_style.sh

# git commit → スタイルチェック実行 (--staged --project-dir で委譲)
echo '{"tool_input":{"command":"git commit -m test"}}' | bash scripts/check_style.sh
```

### オンデマンド (working モード)

```bash
# unstaged な変更をチェック (デフォルト)
python3 scripts/check_style.py

# staged な変更をチェック
python3 scripts/check_style.py --staged

# project-dir を明示指定
python3 scripts/check_style.py --project-dir /path/to/complete-validator
```

### キャッシュクリア

```bash
rm -f .complete-validator/cache.json
```

## プラグインの E2E テスト

別のプロジェクトにプラグインとしてインストールし、実際に hook が発火するかを確認します。

### クリーンインストール手順

既にインストール済みの場合は先にアンインストールしてからインストールします。Claude Code 内で以下のコマンドを実行してください。

```bash
# 1. 既存のプラグインをアンインストール (未インストールならスキップ)
/plugin uninstall complete-validator@complete-validator --scope project

# 2. マーケットプレースを削除して再登録 (ソースの変更にも対応)
/plugin marketplace remove complete-validator
/plugin marketplace add inoueakimitsu/complete-validator

# 3. プラグインをインストール
/plugin install complete-validator@complete-validator --scope project
```

### テストシナリオ

テスト用プロジェクトで以下を確認します。

| # | シナリオ | 期待動作 |
|---|---|---|
| 1 | `*.py` のみ commit | python_style + japanese_comment_style が適用される |
| 2 | `*.md` のみ commit | japanese_comment_style のみが適用される |
| 3 | `*.py` + `*.md` 混在 commit | 各ファイルに正しいルールが適用される |
| 4 | どのルールにもマッチしない拡張子のみ (例: `*.txt`) | チェックがスキップされる |
| 5 | `applies_to` なしのルールファイルを追加 | スキップされ、警告メッセージが出る |

### テスト用プロジェクトの作成例

```bash
mkdir /tmp/test-cv && cd /tmp/test-cv && git init

# テスト用ファイルを作成
echo 'def hello(): pass' > test.py
echo '# テストドキュメント' > test.md
echo 'hello' > test.txt

# *.py のみ commit → シナリオ 1
git add test.py && git commit -m "test: py only"

# *.md のみ commit → シナリオ 2
git add test.md && git commit -m "test: md only"

# *.txt のみ commit → シナリオ 4
git add test.txt && git commit -m "test: txt only"
```

### 後片付け

```bash
# テスト用プロジェクトの削除
rm -rf /tmp/test-cv

# プラグインのアンインストール (テスト用プロジェクトから)
/plugin uninstall complete-validator@complete-validator --scope project
```

## バージョン管理

機能追加やバグ修正を行った場合、以下の 2 ファイルのバージョンを更新してください。

- `.claude-plugin/marketplace.json` の `plugins[0].version`
- `.claude-plugin/plugin.json` の `version`

セマンティック バージョニング (`MAJOR.MINOR.PATCH`) に従います。

- **MAJOR** — 後方互換性のない変更 (ルールファイルのフォーマット変更など)
- **MINOR** — 後方互換性のある機能追加
- **PATCH** — バグ修正

## 開発環境セットアップ

### pre-push hook の設定

clone 後に以下のコマンドで pre-push hook を設定してください。`.git/hooks/` は Git 管理外のため、手動でコピーする必要があります。

```bash
cp git-hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

この hook は push 時にバージョンファイル (`.claude-plugin/marketplace.json`、`.claude-plugin/plugin.json`) の更新漏れをチェックします。バージョンファイル以外の変更が含まれているのにバージョンが更新されていない場合、push をブロックします。

## 制限事項

- `claude -p` の呼び出しに数秒～数十秒かかります (キャッシュヒット時は 0.3 秒程度)
- 大量のファイルを一度に commit するとプロンプトが大きくなり、API の制限に達する可能性があります
