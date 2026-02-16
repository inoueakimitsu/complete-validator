# ルール ファイル テンプレート

## 最小構成テンプレート

フロント マター + 1 ルールの最小構成です。

```markdown
---
applies_to: ["*.py"]
---
# ルールカテゴリ名

## ルール名

ルールの説明です。AI が機械的に判定できる具体的な記述にしてください。

**Bad:**
\`\`\`python
# 違反例
\`\`\`

**Good:**
\`\`\`python
# 正しい例
\`\`\`
```

## 例外付きルールのテンプレート

```markdown
## ルール名

ルールの説明です。

**Bad:**
\`\`\`python
# 違反例
\`\`\`

**Good:**
\`\`\`python
# 正しい例
\`\`\`

ただし、以下の場合は例外です。

- 条件 A の場合は適用しない
- 条件 B の場合は別の形式を使用する

**Bad:**
\`\`\`python
# 例外を誤って適用した例 ← 元が十分な場合、冗長
\`\`\`

**Good:**
\`\`\`python
# 例外を正しく適用した例
\`\`\`
```

## 複数 Bad/Good 例のテンプレート

1 つのルールに対して複数のパターンを示す場合のテンプレートです。

```markdown
## ルール名

ルールの説明です。

**Bad:**
\`\`\`python
# パターン A の違反例
\`\`\`

**Good:**
\`\`\`python
# パターン A の正しい例
\`\`\`

**Bad:**
\`\`\`python
# パターン B の違反例
\`\`\`

**Good:**
\`\`\`python
# パターン B の正しい例
\`\`\`
```

## `applies_to` の書き方

### 基本

`applies_to` は fnmatch パターンのリストです。**ファイルのベース名 (パスを含まない) に対してマッチ**します。

```yaml
# 単一パターン
applies_to: ["*.py"]

# 複数パターン
applies_to: ["*.py", "*.pyi"]

# 複数の言語
applies_to: ["*.py", "*.md"]

# 特定のファイル名
applies_to: ["Makefile", "Dockerfile"]

# パターンの組み合わせ
applies_to: ["*.ts", "*.tsx", "*.js", "*.jsx"]
```

### 重要な注意点

- パターンはファイル名のみでマッチします。`src/*.py` のようなパス付きパターンは意図通りに動作しません。
- `fnmatch` の仕様に従います。`*` は任意の文字列、`?` は任意の 1 文字にマッチします。
- `applies_to` がないルール ファイルはスキップされ、警告メッセージが出力されます。

### パターンの選び方

| 対象 | パターン例 |
|---|---|
| Python ファイル | `["*.py"]` |
| Python + スタブ | `["*.py", "*.pyi"]` |
| TypeScript/JavaScript | `["*.ts", "*.tsx", "*.js", "*.jsx"]` |
| Markdown | `["*.md"]` |
| 全ファイル共通 | `["*"]` |
| 設定ファイル | `["*.json", "*.yaml", "*.yml", "*.toml"]` |

## 実際のルール ファイルの例

### python_style.md (抜粋)

```markdown
---
applies_to: ["*.py"]
---
# Python Style Rules

## No Bare Except

Never use bare `except:` clauses. Always specify the exception type.
At minimum, use `except Exception:`.

**Bad:**
\`\`\`python
try:
    do_something()
except:
    pass
\`\`\`

**Good:**
\`\`\`python
try:
    do_something()
except ValueError:
    handle_error()
\`\`\`
```

### japanese_comment_style.md (抜粋)

```markdown
---
applies_to: ["*.py", "*.md"]
---
# Japanese Comment Style Rules

プログラムのコメントおよび docstring に適用されるルールです。

## 体言止め禁止

見出し以外の体言止めの箇所は、体言止めを使わず「～です。」「～します。」のように文末を丁寧語にしてください。

**Bad:**
\`\`\`python
# ～の場合
# ～のリスト。
\`\`\`

**Good:**
\`\`\`python
# ～の場合の処理です。
# ～のリストです。
\`\`\`

ただし、簡潔に表現できるものを冗長にしないでください。

**Bad:**
\`\`\`python
# A を指定します。  ← 元が単に "A" で十分な場合、冗長
\`\`\`

**Good:**
\`\`\`python
# A です。
\`\`\`
```
