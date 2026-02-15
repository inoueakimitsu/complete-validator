---
name: complete-validator
description: git commit 時にルールベースの AI スタイルチェックを自動実行します。
---

# CompleteValidator

`rules/` 内の Markdown ルールに基づく AI スタイルチェックを実行するプラグインです。

## 自動チェック (commit hook)

PreToolUse hook により、Bash ツールで `git commit` が実行される際に自動で発火します。
staged された変更に対してルールチェックを行い、違反があれば deny で commit をブロックします。

### 違反が検出されたとき

1. 違反内容を確認し、修正が必要か偽陽性かを判断する
2. 明らかな違反 → コードを修正して再 commit
3. 偽陽性の可能性がある場合 → **必ずユーザーに確認する**。ユーザーに違反内容を提示し、修正すべきか偽陽性として抑制すべきかを質問する
4. ユーザーが偽陽性と判断した場合 → プロジェクトの `.complete-validator/suppressions.md` に抑制理由を追記し、再 commit する
5. 全ての違反が解消されるまで繰り返す

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

## 偽陽性の抑制 (suppressions)

プロジェクトの `.complete-validator/suppressions.md` に記述すると、該当する検出が抑制されます。

ユーザーが偽陽性と判断した場合、以下の形式で追記してください:

```markdown
- `<ルールファイル名>` の <ルール名>: <抑制理由の説明>
```

このファイルは Git 管理下に置いてください。内容が変わるとキャッシュが無効化され、次回 commit 時に再チェックされます。

## ルールの追加

`rules/` ディレクトリに `.md` ファイルを追加してください。`## ` 見出しでルールを区切り、Bad/Good の具体例を記載します。
