# CompleteValidator

`rules/` 内の Markdown ルールに基づく AI バリデーションを実行する Claude Code Plugin です。
git commit 時の自動チェック (PreToolUse hook)、任意のタイミングでのオンデマンド チェック、バックグラウンド ストリーム チェックの 3 つのモードをサポートします。
検出した違反は systemMessage として Claude Code エージェントに返します。

## 開発方針

- **問題を発見してもすぐに対症療法を適用しないでください。** まず根本原因を分析し、設計上の判断として CLAUDE.md や Issue に記録したうえで、適切な修正方針を検討してください。表面的な修正 (マジック ナンバーの追加、条件分岐の追加など) を即座に行うのではなく、問題の全体像を把握してから対処してください。

## インストール

### ローカル パスからインストール

```bash
# マーケットプレースとして登録
/plugin marketplace add ../complete-validator

# プラグインをインストール
/plugin install complete-validator@complete-validator --scope project
```

### GitHub からインストール

```bash
/plugin marketplace add inoueakimitsu/complete-validator
/plugin install complete-validator@complete-validator --scope project
```

### その他の Git ホスト (GitLab、Bitbucket、自前サーバー) からインストール

```bash
/plugin marketplace add https://gitlab.com/<org>/complete-validator.git
/plugin install complete-validator@complete-validator --scope project
```

`--scope` は `project` (チーム共有)、`user` (全プロジェクト)、`local` (個人、gitignore 対象) から選択できます。

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
  │  - tool_input.command に "git commit" が含まれるか判定 (複合コマンド対応)
  │  - git commit 以外 → exit 0 (出力なし = 許可、数十 ms)
  │  - git commit → 先行する git add を実行後、check_style.py --staged --plugin-dir に委譲
  │
  ▼
scripts/check_style.py --staged --plugin-dir "$PLUGIN_DIR"
  │  1. git diff --cached で staged diff 取得
  │  2. git diff --cached --name-only --diff-filter=d で全 staged ファイル取得
  │  3. CWD から上方向に .complete-validator/rules/ を探索し、プラグイン組み込み rules/ とマージ
  │  4. .complete-validator/suppressions.md を読み込み (存在すれば)
  │  5. .complete-validator/config.json から max_workers を読み込み (デフォルト 4)
  │  6. git show :<path> で staged 版ファイル内容取得
  │  7. per-file 単位 (1 ルール × 1 ファイル) で並列チェック (max_workers で同時起動数を制限):
  │     a. cache key = sha256(prompt_version + rule_name + file_path + rule_body + diff + suppressions)
  │     b. キャッシュ ヒット → 即返却
  │     c. プロンプト構築 (1 ルール ファイル + 1 ファイルの diff/全文 + suppressions)
  │     d. claude -p でチェック実行 (CLAUDECODE 環境変数を除去してネスト検出回避)
  │     e. キャッシュ保存
  │  8. ルール名ごとに結果を集約 → deny が 1 つでもあれば全体 deny
  │
  ▼
Claude Code エージェント
  - 違反あり → deny でブロック、エージェントが修正して再 commit
  - 偽陽性 → .complete-validator/suppressions.md に記述して再 commit
  - 違反なし → allow で commit 成功
```

### ストリーム モード アーキテクチャ

```
Claude Code エージェント
  │
  │  python3 check_style.py --stream [--staged] --plugin-dir ...
  │
  ▼
check_style.py --stream
  │  1. stream-id 生成 (YYYYMMDD-HHMMSS-<random6>)
  │  2. .complete-validator/stream-results/<stream-id>/ 作成
  │  3. 古い結果ディレクトリを最新 5 件のみ保持するようクリーンアップ
  │  4. subprocess.Popen で子プロセス (--stream-worker) を起動 (start_new_session=True)
  │  5. stream-id を stdout に出力して即 exit 0
  │
  ▼
check_style.py --stream-worker --stream-id <id>
  │  1. ルールとファイルを読み込み
  │  2. (rule_file, individual_file) ペアを列挙
  │  3. ThreadPoolExecutor で並列実行 (max_workers は config.json で設定、デフォルト 4)
  │  4. 完了するたびに per-file 結果ファイルと status.json を更新
  │
  ▼
.complete-validator/stream-results/<stream-id>/
  ├── status.json        # 進捗 (total_units, completed_units, status, summary)
  ├── worker.log         # ワーカー ログ
  └── results/
      ├── <rule>__<hash>.json  # per-file 結果
      └── ...
  │
  ▼
Claude Code エージェント
  - status.json をポーリングして進捗確認
  - deny の結果を確認して修正
  - 修正後に再チェック (キャッシュ ヒットで高速)
  - 全 allow なら commit (hook は per-file preflight で高速パス)
```

全モード共通で処理単位は **1 ルール ファイル × 1 個別ファイル** です。hook モードとストリーム モードは同じ per-file 単位で `claude -p` を実行し、同じキャッシュ空間を共有します。ストリーム モードの結果は hook モードでもそのまま使われます。

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
│       └── SKILL.md             # スキル定義 (ルール概要、使い方)
├── rules/
│   ├── python_style.md                # Python スタイル ルール
│   ├── readable_code/                 # リーダブルコード ルール (セクション分割)
│   │   ├── 01_basics.md
│   │   ├── ...
│   │   └── 11_review.md
│   └── japanese_comment_style/        # 日本語コメント スタイル ルール (ルール分割)
│       ├── 01_taigendome.md
│       ├── ...
│       └── 13_trailing_paren.md
├── scripts/
│   ├── check_style.sh           # hook エントリ ポイント (シェルラッパー)
│   └── check_style.py           # チェック本体
├── .gitignore
└── CLAUDE.md
```

## 各ファイルの役割

### `.claude-plugin/marketplace.json`

マーケットプレース定義です。`/plugin marketplace add` でこのリポジトリを登録する際に参照されます。 `source` フィールドでプラグイン本体の位置を `"./"` (リポジトリ ルート) として指定しています。

### `.claude-plugin/plugin.json`

Plugin のメタデータを定義します。 `name` がプラグイン名として使用され、スキルは `/complete-validator:complete-validator` で呼び出せます。

### `hooks/hooks.json`

- `PreToolUse` の `Bash` matcher で全 Bash ツール呼び出し時に発火します。
- `${CLAUDE_PLUGIN_ROOT}/scripts/check_style.sh` を実行します。
- Plugin インストール時に自動登録されます。
- タイムアウトは 600 秒です。

### `scripts/check_style.sh`

- stdin から hook JSON を受け取り、`tool_input.command` を python3 で抽出します。
- コマンドを `&&`、`||`、`;` で分割し、いずれかのパートが `git commit` にマッチするか判定します。
  - `git commit -m "test"` (単独コマンド)
  - `git add test.py && git commit -m "test"` (複合コマンド、エージェントが頻繁に使用)
  - `git -C /path commit -m "test"` (`-C` オプション付き)
- 複合コマンドの場合、`git commit` より前にある `git add` パートを先に実行します。詳細は後述の「PreToolUse hook の注意事項」を参照してください。
- `CLAUDE_PLUGIN_ROOT` 環境変数があれば使用し、なければスクリプト位置からスタンドアロン互換で相対解決します。
- jq 非依存で、python3 -c で JSON をパースします。

### `scripts/check_style.py`

主要な処理フローです。 4 つのモードをサポートします。

- **working モード** (デフォルト): `git diff` で unstaged な変更をチェックします。オンデマンド実行用です。
- **staged モード** (`--staged`): `git diff --cached` で staged な変更をチェックします。commit hook 用です。
- **full-scan モード** (`--full-scan`): 全 tracked ファイルをチェックします。既存コードのスキャン用です。
- **stream モード** (`--stream`): バックグラウンドで per-file チェックを実行し、結果をファイルに逐次出力します。

**CLI:**
```bash
python3 scripts/check_style.py                    # working モード (デフォルト)
python3 scripts/check_style.py --staged            # staged モード
python3 scripts/check_style.py --full-scan         # フル スキャン モード
python3 scripts/check_style.py --stream            # ストリーム モード
python3 scripts/check_style.py --stream --staged   # ストリーム モード (staged)
python3 scripts/check_style.py --full-scan --stream # ストリーム モード (フル スキャン)
python3 scripts/check_style.py --plugin-dir DIR    # プラグイン ディレクトリを指定 (組み込みルールの場所)
```

**処理フロー (hook/オンデマンド)**

1. **diff 取得**: working モードでは `git diff`、staged モードでは `git diff --cached` を使用します。空なら exit 0 で許可します。
2. **変更ファイル一覧取得**: `git diff --name-only --diff-filter=d` で取得します。staged 時は `--cached` を付与します。
3. **ルール読み込み**: CWD から上方向に `.complete-validator/rules/` を再帰探索 (`rglob`) し、プラグイン組み込み `rules/` とマージします (nearest wins)。`applies_to` パターンで対象ファイルを絞り込みます。ルール名はディレクトリ相対パス (例: `readable_code/02_naming.md`) です。
4. **suppressions 読み込み**: プロジェクトの `.complete-validator/suppressions.md` が存在すれば読み込みます。
5. **config 読み込み**: `.complete-validator/config.json` から `max_workers` を読み込みます (デフォルト 4)。
6. **ファイル内容取得**: staged モードでは `git show :<path>`、working モードではファイルを直接読み込みます。
7. **per-file 単位で並列チェック**: ストリーム モードと同じ処理単位 (1 ルール × 1 ファイル) で `ThreadPoolExecutor` を使って `claude -p` を並列実行します。同時起動数は `max_workers` で制限されます。
   a. **キャッシュ確認**: `sha256(prompt_version + "per-file" + rule_name + file_path + rule_body + diff + suppressions)` をキーにキャッシュを参照します。
   b. **プロンプト構築**: 1 ルール ファイル + 1 ファイルの diff/全文 + suppressions で構成します。
   c. **`claude -p` 実行**: `CLAUDECODE` 環境変数を除去してネストセッション検出を回避しつつ実行します。
   d. **キャッシュ保存**: per-file 単位でキャッシュします。
8. **結果集約**: ルール名ごとに per-file 結果を集約し、ルール名でソートします。deny が 1 つでもあれば全体 deny になります。

**処理フロー (ストリーム)**

1. **stream-id 生成**: `YYYYMMDD-HHMMSS-<random6>` 形式の ID を生成します。
2. **結果ディレクトリ作成**: `.complete-validator/stream-results/<stream-id>/` を作成します。
3. **ワーカー起動**: `subprocess.Popen` で子プロセス (`--stream-worker`) を起動します (`start_new_session=True`)。
4. **即 exit**: stream-id を stdout に出力して親プロセスは即 exit 0 します。
5. **ワーカー処理**: (rule_file, individual_file) ペアを列挙し、`ThreadPoolExecutor` で並列実行します。
6. **結果出力**: 完了するたびに per-file 結果ファイルと `status.json` を更新します。

設計上の重要な判断です。

- **ルール ファイルの再帰探索**: `rglob("*.md")` でサブディレクトリ内のルール ファイルも読み込みます。ルールの物理分割により 1 回の `claude -p` のプロンプトが小さくなり、検出精度が向上します。
- **統一された per-file 実行**: hook モードとストリーム モードは同じ per-file 単位 (1 ルール × 1 ファイル) で `claude -p` を実行します。キャッシュ空間も共有されるため、ストリーム モードの結果が hook モードでもそのまま使われます。
- **max_workers による同時起動数制限**: `claude -p` は Node.js プロセスで 1 つあたり 200-400MB のメモリを消費します。`.complete-validator/config.json` の `max_workers` (デフォルト 4) で同時起動数を制限し、OOM を防止します。
- **per-file キャッシュ**: per-file 粒度のキャッシュを使用します。1 つのルールだけ変更した場合でも他はキャッシュ ヒットします。
- **違反ありの場合は `"permissionDecision": "deny"`**: commit をブロックします。エージェントが違反を修正してから再 commit します。
- **偽陽性対策**: `.complete-validator/suppressions.md` に記述することで、既知の偽陽性を抑制できます。
- **エラー時は allow**: `claude -p` のタイムアウト (580 秒) や失敗時は警告メッセージ付きで allow します。
- **deadline 管理**: hook の 600 秒タイムアウトの手前 (590 秒) を deadline とし、各 Future の取得時に残り時間を計算します。

## ルールの読み込み順序

ルールは以下の順序で読み込まれ、同名ファイルは近い方が勝ちます (nearest wins)。

1. **CWD に最も近い `.complete-validator/rules/`**: 最優先
2. **親ディレクトリの `.complete-validator/rules/`**: 上位に向かって順に探索
3. **プラグイン組み込み `rules/`**: ベース (最低優先)

異なるファイル名のルールはすべてマージされます。同名ファイルは近い方が完全に置き換えます (部分マージなし)。

**典型的なプロジェクト:**

```
/project/.complete-validator/rules/    ← 1 番目 (プロジェクト固有)
$PLUGIN_DIR/rules/                     ← 2 番目 (組み込み)
```

**モノレポ:**

```
/repo/.complete-validator/rules/              ← 3 番目 (リポジトリ共通)
/repo/packages/api/.complete-validator/rules/ ← 2 番目 (パッケージ固有)
/repo/packages/api/src/                       ← CWD
$PLUGIN_DIR/rules/                            ← 4 番目 (組み込み)
```

## ルールの追加方法

### プラグイン組み込みルール

`rules/` ディレクトリに `.md` ファイルを追加します。サブディレクトリも再帰的に探索 (`rglob`) されるため、関連するルールをサブディレクトリにまとめることができます (例: `rules/readable_code/01_basics.md`)。ファイルはアルファベット順に読み込まれます。全プロジェクトに適用されます。

### プロジェクト固有ルール

プロジェクトの `.complete-validator/rules/` ディレクトリに `.md` ファイルを追加します。サブディレクトリも再帰的に探索されます。そのプロジェクトのみに適用されます。組み込みルールと同名のファイル (相対パスで比較) を置くと、プロジェクト側が優先されます。

```bash
# プロジェクト固有ルールのディレクトリを作成
mkdir -p .complete-validator/rules

# プロジェクト固有のルールを追加
# (プラグイン組み込みルールと同じフォーマット)
```

### ルール ファイルのフォーマット

- 先頭に YAML フロント マターで `applies_to` を指定します (必須)
- `applies_to` にはファイル名の glob パターンのリストを指定します
- `## ` 見出しでルールを区切ります
- 各ルールにルール名、説明、Bad/Good の具体例を記載します
- 複数ファイルに分割できます (例: `rules/python_style.md`、`rules/naming.md`)
- サブディレクトリにまとめることもできます (例: `rules/readable_code/01_basics.md`)。ルール名はディレクトリ相対パスになります
- `applies_to` フロント マターがないルール ファイルはスキップされ、警告メッセージが出力されます

フロント マターの例です。

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

ルールを変更するとキャッシュ キーが変わるため、次回の commit 時に自動的に再チェックが走ります。

## キャッシュ

- git toplevel の `$GIT_TOPLEVEL/.complete-validator/cache.json` に保存されます。
- **per-file キャッシュ** (全モード共通): キーは `sha256(prompt_version + "per-file" + rule_name + file_path + rule_body + diff + suppressions)` です。hook モードとストリーム モードで同じキャッシュ空間を共有します。
- diff、ルール、または suppressions が変わると自動的にキャッシュ ミスになります。
- 1 つのルールだけ変更した場合、他のルールはキャッシュ ヒットして高速化します。
- キャッシュ クリアは `rm -f .complete-validator/cache.json` です。
- `.gitignore` により Git 管理外です。

## 設定ファイル (config.json)

プロジェクトの `.complete-validator/config.json` で動作を設定できます。

```json
{
  "max_workers": 4
}
```

| キー | 型 | デフォルト | 説明 |
|---|---|---|---|
| `max_workers` | int | 4 | `claude -p` の同時起動数の上限。大きくすると高速になるがメモリ消費が増加します。`claude -p` は 1 プロセスあたり 200-400MB のメモリを消費するため、環境に合わせて調整してください。 |

ファイルが存在しない場合はデフォルト値が使用されます。

## 偽陽性の抑制 (suppressions)

バリデーションで偽陽性が発生した場合、プロジェクトの `.complete-validator/suppressions.md` に記述することで抑制できます。

- プロジェクトの git toplevel にある `.complete-validator/suppressions.md` に保存されます。
- フォーマットは自由記述の Markdown です。どのルールのどの検出が偽陽性かを説明してください。
- suppressions の内容はプロンプトに「既知の例外」として追加され、該当する場合は違反として報告されなくなります。
- suppressions を変更するとキャッシュ キーが変わるため、次回の commit 時に自動的に再チェックが走ります。
- チームで共有するため、このファイルは Git 管理下に置くことを推奨します。

以下は記述例です。

```markdown
# Suppressions

- `python_style.md` の docstring 必須ルール: `__init__.py` の空ファイルには docstring 不要
- `japanese_comment_style.md` の日本語コメントルール: 英語のライブラリ名はそのまま使用可
```

## 前提条件

- Python 3.10 以上 (`list[str]`、`dict[str, str]` 構文を使用)
- Claude Code CLI (`claude` コマンド) がインストール済み、認証済み
- Git

## 手動テスト

### commit hook 経由 (staged モード)

```bash
# git commit 以外のコマンド → 即 exit 0 (出力なし)
echo '{"tool_input":{"command":"git status"}}' | bash scripts/check_style.sh

# git commit → AI バリデーション実行 (--staged --plugin-dir で委譲)
echo '{"tool_input":{"command":"git commit -m test"}}' | bash scripts/check_style.sh
```

### オンデマンド (working モード)

```bash
# unstaged な変更をチェック (デフォルト)
python3 scripts/check_style.py

# staged な変更をチェック
python3 scripts/check_style.py --staged

# plugin-dir を明示指定 (組み込みルールの場所)
python3 scripts/check_style.py --plugin-dir /path/to/complete-validator
```

### ストリーム モード

```bash
# ストリーム チェックを開始 (working モード)
python3 scripts/check_style.py --stream --plugin-dir /path/to/complete-validator
# → stream-id が stdout に出力されます。

# ストリーム チェックを開始 (staged モード)
python3 scripts/check_style.py --stream --staged --plugin-dir /path/to/complete-validator

# ストリーム チェックを開始 (フル スキャン)
python3 scripts/check_style.py --full-scan --stream --plugin-dir /path/to/complete-validator

# 進捗確認
cat .complete-validator/stream-results/<stream-id>/status.json

# 個別結果確認
cat .complete-validator/stream-results/<stream-id>/results/*.json

# ワーカー ログ確認
cat .complete-validator/stream-results/<stream-id>/worker.log
```

### キャッシュ クリア

```bash
rm -f .complete-validator/cache.json
```

## プラグインの E2E テスト

**重要: プラグインの hook はプラグイン自身のリポジトリ内では発火しません。** Claude Code は作業ディレクトリに `.claude-plugin/plugin.json` が存在する場合、そのディレクトリを「プラグインを編集中の通常プロジェクト」として扱い、プラグインとしては読み込みません。そのため hook が登録されず発火しません。hook のテストは必ず別のプロジェクトで行ってください。

別のプロジェクトにプラグインとしてインストールし、実際に hook が発火するかを確認します。

### クリーン インストール手順

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
| 1 | `*.py` のみ commit | python_style + readable_code/* + japanese_comment_style/* が適用される |
| 2 | `*.md` のみ commit | japanese_comment_style/* のみが適用される |
| 3 | `*.py` + `*.md` 混在 commit | 各ファイルに正しいルールが適用される |
| 4 | どのルールにもマッチしない拡張子のみ (`*.txt` など) | チェックがスキップされる |
| 5 | `applies_to` なしのルール ファイルを追加 | スキップされ、警告メッセージが出る |

### テスト用プロジェクトの作成例

**重要: PreToolUse hook は Claude Code エージェントの Bash ツール経由でのみ発火します。** 通常のシェルで `git commit` を実行してもバリデーションは走りません。テストは必ず Claude Code 内で実行してください。

#### Step 1: シェルでプロジェクト準備

通常のシェルでテスト用プロジェクトを作成し、initial commit まで済ませます (hook 不要)。

```bash
mkdir /tmp/test-cv && cd /tmp/test-cv && git init

# テスト用ファイルを作成
echo 'def hello(): pass' > test.py
echo '# テストドキュメント' > test.md
echo 'hello' > test.txt

# initial commit (hook なしで OK)
git add -A && git commit -m "initial commit"
```

#### Step 2: Claude Code 起動 + プラグイン インストール

テスト用プロジェクトのディレクトリで Claude Code を起動し、プラグインをインストールします。

```bash
cd /tmp/test-cv
claude
```

Claude Code 内で以下を実行します。

```
/plugin marketplace add inoueakimitsu/complete-validator
/plugin install complete-validator@complete-validator --scope project
```

#### Step 3: Claude Code 内でテスト実行

Claude Code 内でエージェントにファイル変更と commit を指示します。エージェントが Bash ツールで `git commit` を呼ぶことで hook が発火し、バリデーションが実行されます。

```
# シナリオ 1: *.py のみ → python_style + japanese_comment_style が適用される
test.py に関数を追加して commit してください

# シナリオ 2: *.md のみ → japanese_comment_style のみが適用される
test.md にセクションを追加して commit してください

# シナリオ 3: *.py + *.md 混在 → 各ファイルに正しいルールが適用される
test.py と test.md を両方修正して commit してください

# シナリオ 4: ルールなし → チェックがスキップされる
test.txt を修正して commit してください
```

### 後片付け

```bash
# テスト用プロジェクトの削除
rm -rf /tmp/test-cv
```

Claude Code 内でプラグインをアンインストールする場合は以下を実行します。

```
/plugin uninstall complete-validator@complete-validator --scope project
```

### PreToolUse hook の注意事項

E2E テストや開発時に知っておくべき PreToolUse hook の挙動です。

#### hook はコマンド実行前に発火します

PreToolUse hook は Bash ツールのコマンドが実行される**前**に発火します。これにより、以下の問題が発生します。

エージェントは `git add test.py && git commit -m "..."` のように `git add` と `git commit` を**1 つの Bash ツール呼び出し**にまとめることが多いです。この場合、hook が発火した時点では `git add` がまだ実行されていないため、`git diff --cached` が空になり、`check_style.py` が「差分なし」として即 allow してしまいます。

`check_style.sh` はこの問題に対処するため、複合コマンド内の `git commit` より前にある `git add` パートを抽出して先に実行します。これにより、`check_style.py` が staged diff を正しく取得できます。

#### エージェントのコマンド形式は多様です

エージェントが生成する `git commit` コマンドの形式は一定ではありません。`check_style.sh` は以下のすべてに対応する必要があります。

- `git commit -m "message"` (単独コマンド)
- `git add file && git commit -m "message"` (複合コマンド、最も多い)
- `git -C /path/to/repo commit -m "message"` (`-C` オプション付き)
- `git add file && git commit -m "$(cat <<'EOF'\nmessage\nEOF\n)"` (HEREDOC を使ったメッセージ)

#### hook が発火しているかの確認方法

hook が発火しているかどうかは、キャッシュ ファイルの有無で判断できます。

- `$GIT_TOPLEVEL/.complete-validator/cache.json` が作成されていれば、hook が発火してバリデーションが実行されています。
- 作成されていなければ、hook が発火していないか、`check_style.py` が差分なしで即終了しています。

デバッグ時は `check_style.sh` の `LOG_FILE` (`$PLUGIN_DIR/.complete-validator/hook_debug.log`) に stderr が出力されます。

#### プラグインはキャッシュから実行されます

プラグインのインストール時にファイルが `~/.claude/plugins/cache/` 以下にコピーされます。ローカルのソースコードを編集しても、キャッシュ版には反映されません。

- キャッシュは `~/.claude/plugins/cache/complete-validator/complete-validator/<version>/` に保存されます。
- 開発中にキャッシュ版を更新するには、キャッシュ版のファイルを直接上書きするか、プラグインを再インストールしてください。

### tmux による自動テスト

Claude Code の TUI を tmux の `send-keys` と `capture-pane` で操作することで、別の Claude Code セッション内で E2E テストを自動実行できます。

#### 基本構成

```bash
# 1. tmux セッション作成
tmux new-session -d -s test-cv -c /tmp/test-cv -x 200 -y 50

# 2. Claude Code 起動 (ネスト検出回避 + 権限スキップ)
tmux send-keys -t test-cv "env -u CLAUDECODE claude --dangerously-skip-permissions" Enter

# 3. 起動待ち
sleep 8

# 4. プロンプト送信
tmux send-keys -t test-cv "test.py に関数を追加して commit してください"
sleep 0.5
tmux send-keys -t test-cv Enter

# 5. 結果取得 (hook 実行を含めて 2-3 分待つ)
sleep 150
tmux capture-pane -t test-cv -p -S -50

# 6. クリーンアップ
tmux send-keys -t test-cv Escape
sleep 0.5
tmux send-keys -t test-cv "/exit"
sleep 0.5
tmux send-keys -t test-cv Enter
sleep 3
tmux kill-session -t test-cv
```

#### tmux send-keys のコツ

- **テキストと Enter は分けて送信します。** テキストを送った後、`sleep 0.5` を挟んでから `Enter` を送ります。同時に送ると Enter が改行として扱われることがあります。
  ```bash
  # Good
  tmux send-keys -t test-cv "プロンプト文"
  sleep 0.5
  tmux send-keys -t test-cv Enter

  # Bad (テキスト末尾の Enter が改行になることがある)
  tmux send-keys -t test-cv "プロンプト文" Enter
  ```
- **入力のクリアには `Escape` + `C-u` を使います。** 入力バッファーに残ったテキストをクリアできます。
  ```bash
  tmux send-keys -t test-cv Escape
  sleep 0.5
  tmux send-keys -t test-cv C-u
  ```
- **`Ctrl+C` で処理を中断できます。** エージェントの実行中に中断する場合に使います。
  ```bash
  tmux send-keys -t test-cv C-c
  ```
- **メニュー選択は `Down`/`Up` + `Enter` で操作します。** 権限確認ダイアログなどの操作に使います。
  ```bash
  tmux send-keys -t test-cv Down   # 2 番目の選択肢に移動
  sleep 0.3
  tmux send-keys -t test-cv Enter  # 確定
  ```

#### `env -u CLAUDECODE` が必要です

Claude Code は `CLAUDECODE` 環境変数でネストセッションを検出します。Claude Code 内の Bash ツールから別の Claude Code を起動する場合、この環境変数を除去しないとエラーになります。

```bash
env -u CLAUDECODE claude --dangerously-skip-permissions
```

#### `--dangerously-skip-permissions` で承認を省略できます

テスト時に毎回ツール実行の承認を行うのは非効率です。`--dangerously-skip-permissions` フラグで全ツールの権限チェックをスキップできます。このフラグなしの場合、`send-keys` で `Down` + `Enter` を送って各ダイアログを承認する必要があります。

#### 待ち時間の目安

| 操作 | 待ち時間 |
|---|---|
| Claude Code 起動 | 8 秒 |
| `/plugin` コマンド | 5-10 秒 |
| ファイル編集 + `git commit` (hook なし) | 30-60 秒 |
| ファイル編集 + `git commit` (hook あり、キャッシュ ミス) | 3-5 分 (ルール数 × ファイル数 / max_workers に依存) |
| ファイル編集 + `git commit` (hook あり、キャッシュ ヒット) | 30-60 秒 |

#### capture-pane で結果を取得します

```bash
# 直近 50 行を取得
tmux capture-pane -t test-cv -p -S -50

# 特定のキーワードで hook 発火を確認
tmux capture-pane -t test-cv -p -S -50 | grep -c "Blocked by hook"

# hook が deny を返した場合、エージェントの出力に以下が含まれます
#   PreToolUse:Bash hook returned blocking error
#   Blocked by hook
#   Error: Hook PreToolUse:Bash denied this tool
```

## バージョン管理

機能追加やバグ修正を行った場合、以下の 2 ファイルのバージョンを更新してください。

- `.claude-plugin/marketplace.json` の `plugins[0].version`
- `.claude-plugin/plugin.json` の `version`

セマンティック バージョニング (`MAJOR.MINOR.PATCH`) に従います。

- **MAJOR**: 後方互換性のない変更 (ルール ファイルのフォーマット変更など)
- **MINOR**: 後方互換性のある機能追加
- **PATCH**: バグ修正

## 開発環境セットアップ

### pre-push hook の設定

clone 後に以下のコマンドで pre-push hook を設定してください。`.git/hooks/` は Git 管理外のため、手動でコピーする必要があります。

```bash
cp git-hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

この hook は push 時にバージョン ファイル (`.claude-plugin/marketplace.json`、`.claude-plugin/plugin.json`) の更新漏れをチェックします。バージョン ファイル以外の変更が含まれているのにバージョンが更新されていない場合、push をブロックします。

## 制限事項

- `claude -p` の呼び出しに数秒～数十秒かかります。キャッシュ ヒット時は 0.3 秒程度です。
- ルール数 × ファイル数の組み合わせが多い場合、`max_workers` (デフォルト 4) で並列数を制限しているため全体の実行時間が長くなります。
