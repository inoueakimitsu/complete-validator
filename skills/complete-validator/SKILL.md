---
name: complete-validator
description: git commit 時にルールベースの AI スタイルチェックを自動実行します。
---

# CompleteValidator

git commit 時に `rules/` 内の Markdown ルールに基づく AI スタイルチェックを自動実行するプラグインです。

## 仕組み

PreToolUse hook により、Bash ツールで `git commit` が実行される際に自動で発火します。
staged された Python ファイルに対してルールチェックを行い、違反があれば systemMessage でエージェントに通知します。
commit はブロックせず、エージェントが違反を修正してから再度 commit します。

## ルールの追加

`rules/` ディレクトリに `.md` ファイルを追加してください。`## ` 見出しでルールを区切り、Bad/Good の具体例を記載します。
