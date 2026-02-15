---
name: complete-validator
description: git commit 時にルールベースの AI スタイルチェックを自動実行します。
---

# CompleteValidator

`rules/` 内の Markdown ルールに基づく AI スタイルチェックを実行するプラグインです。

## 自動チェック (commit hook)

PreToolUse hook により、Bash ツールで `git commit` が実行される際に自動で発火します。
staged された変更に対してルールチェックを行い、違反があれば systemMessage でエージェントに通知します。
commit はブロックせず、エージェントが違反を修正してから再度 commit します。

## オンデマンドチェック

commit 前に任意のタイミングでスタイルチェックを実行できます。

```bash
# working (unstaged) な変更をチェック（デフォルト）
python3 scripts/check_style.py

# staged な変更をチェック
python3 scripts/check_style.py --staged

# ルールディレクトリを明示指定
python3 scripts/check_style.py --project-dir /path/to/complete-validator
```

## ルールの追加

`rules/` ディレクトリに `.md` ファイルを追加してください。`## ` 見出しでルールを区切り、Bad/Good の具体例を記載します。
