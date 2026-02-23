---
name: complete-validator
description: git commit 時にルールベースの AI バリデーションを自動実行します。
---

# CompleteValidator

`rules/` 内の Markdown ルールに基づく AI バリデーションを実行するプラグインです。

## 自動チェック (commit hook)

PreToolUse hook により、Bash ツールで `git commit` が実行される際に自動で発火します。
staged された変更に対してルール チェックを行い、違反があれば deny で commit をブロックします。

### 違反が検出されたとき

1. 違反内容を確認し、修正が必要か偽陽性かを判断します。
2. 明らかな違反であればコードを修正して再 commit します。
3. 偽陽性の可能性がある場合は**必ずユーザーに確認します**。ユーザーに違反内容を提示し、修正すべきか偽陽性として抑制すべきかを質問します。
4. ユーザーが偽陽性と判断した場合はプロジェクトの `.complete-validator/suppressions.md` に抑制理由を追記し、再 commit します。
5. 全ての違反が解消されるまで繰り返します。

## オンデマンド チェック

commit 前に任意のタイミングでバリデーションを実行できます。

### 実行モードの既定方針 (重要)

- 通常運用では **stream モードを既定** とします。
- 理由:
  - 検出と修正を並行できるため、全体の壁時計時間を短縮できる。
  - `claim/resolve` による排他制御を使って安全に逐次修正できる。
  - 大きい差分や full scan でもタイムアウト回避しやすい。
- 例外:
  - 変更がごく少数で「一発で結果だけ見たい」場合のみ非 stream 実行を選んでよい。

```bash
# working (unstaged) な変更をチェック (デフォルト)
python3 scripts/check_style.py

# staged な変更をチェック
python3 scripts/check_style.py --staged

# プラグイン ディレクトリを明示指定 (組み込みルールの場所)
python3 scripts/check_style.py --plugin-dir /path/to/complete-validator
```

## フル スキャン

diff に関係なく、リポジトリ内の全 tracked ファイルをルールに基づいてチェックします。
ツール導入前にコミットされた既存コードの違反を検出するのに使います。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --full-scan --plugin-dir ${CLAUDE_PLUGIN_ROOT}
```

- 違反がある場合は exit code 1 を返し、違反内容を stderr に出力します。
- 違反がない場合は exit code 0 を返します。
- 結果はキャッシュされ、ファイル内容が変わらなければ再実行時にキャッシュ ヒットします。

**注意:** フル スキャンではルール数 × 全 tracked ファイル数のユニットが生成されるため、`claude -p` の呼び出し回数が非常に多くなります (例: 13 ルール × 31 ファイル = 403 ユニット)。フォアグラウンド実行では完了まで 10 分以上かかる場合があるため、`--full-scan --stream` でのストリーム モード実行を推奨します。ストリーム モードであればバックグラウンドで実行され、ポーリングで進捗を確認しながら逐次修正できます。

## ストリーム モード

バックグラウンドで per-file のバリデーションを実行し、結果をポーリングしながら逐次修正できるモードです。ルール数やファイル数が多い場合に、hook の 600 秒タイムアウトを回避しつつ効率的にチェックできます。

### 標準ワークフロー (通常はこれを実行)

1. ストリーム チェックを開始して stream-id を取得します。

```bash
# working (unstaged) な変更をストリーム チェック
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --stream --plugin-dir ${CLAUDE_PLUGIN_ROOT}

# staged な変更をストリーム チェック
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --stream --staged --plugin-dir ${CLAUDE_PLUGIN_ROOT}

# 全 tracked ファイルをストリーム チェック (フル スキャン)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --full-scan --stream --plugin-dir ${CLAUDE_PLUGIN_ROOT}
```

stream-id が stdout に出力されます。バックグラウンドでワーカーが起動し、ルール × ファイルの各ペアを並列チェックします。

2. queue から未処理 violation を取得します。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --list-violations <stream-id> --plugin-dir ${CLAUDE_PLUGIN_ROOT}
```

3. 取得したエントリを 1 件 claim します。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --claim <stream-id> <violation-id> --plugin-dir ${CLAUDE_PLUGIN_ROOT}
```

`claim` の返り値 JSON から `claim_uuid` と `state_version` を必ず保持します。

4. violation を修正します。長時間作業中は lease を heartbeat で延長します。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --heartbeat <stream-id> <violation-id> --claim-uuid <claim_uuid> --state-version <state_version> --plugin-dir ${CLAUDE_PLUGIN_ROOT}
```

5. 修正完了後に resolve します (CAS)。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --resolve <stream-id> <violation-id> --claim-uuid <claim_uuid> --state-version <state_version> --plugin-dir ${CLAUDE_PLUGIN_ROOT}
```

6. `--list-violations` を再実行し、未処理が 0 になるまで 2-5 を繰り返します。

7. 補助として `status.json` / `results` を確認します。

```bash
cat .complete-validator/stream-results/<stream-id>/status.json
```

`completed_units` が増加し、最終的に `status` が `"completed"` になります。

3. deny の結果を確認して修正します。

```bash
# 個別結果を確認します。
cat .complete-validator/stream-results/<stream-id>/results/*.json
```

各結果ファイルには `rule_name`、`file_path`、`status`、`message`、`cache_hit` が含まれます。

4. 修正後に再チェックします。キャッシュ ヒットした箇所は即座に完了するため、修正した箇所のみが再実行されます。

5. 全結果が allow になったら commit します。hook 側は per-file キャッシュの preflight により高速パスで通過します。

### 最小 consumer ループ例

```bash
STREAM_ID="$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --stream --staged --plugin-dir ${CLAUDE_PLUGIN_ROOT})"

while true; do
  LIST_JSON="$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --list-violations "$STREAM_ID" --plugin-dir ${CLAUDE_PLUGIN_ROOT})"
  COUNT="$(printf '%s' "$LIST_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("count", 0))')"
  [ "$COUNT" -eq 0 ] && break

  VID="$(printf '%s' "$LIST_JSON" | python3 -c 'import json,sys; e=json.load(sys.stdin).get("entries",[]); print(e[0]["violation_id"] if e else "")')"
  [ -z "$VID" ] && sleep 1 && continue

  CLAIM_JSON="$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --claim "$STREAM_ID" "$VID" --plugin-dir ${CLAUDE_PLUGIN_ROOT})" || continue
  CUUID="$(printf '%s' "$CLAIM_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("claim_uuid",""))')"
  SVER="$(printf '%s' "$CLAIM_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("state_version",0))')"
  [ -z "$CUUID" ] && continue

  # ここで対象ファイルを修正する

  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py --resolve "$STREAM_ID" "$VID" --claim-uuid "$CUUID" --state-version "$SVER" --plugin-dir ${CLAUDE_PLUGIN_ROOT}
done
```

注意:
- `claim_uuid/state_version` が一致しない resolve は失敗します。
- 他 worker が同じファイルを処理中の場合、claim は拒否されます。別 violation を処理します。

## 偽陽性の抑制 (suppressions)

プロジェクトの `.complete-validator/suppressions.md` に記述すると、該当する検出が抑制されます。

ユーザーが偽陽性と判断した場合、以下の形式で追記してください。

```markdown
- `<ルール ファイル名>` の <ルール名>: <抑制理由の説明>
```

このファイルは Git 管理下に置いてください。内容が変わるとキャッシュが無効化され、次回 commit 時に再チェックされます。

## ルールの追加

### プラグイン組み込みルール

プラグインの `rules/` ディレクトリに `.md` ファイルを追加してください。全プロジェクトに適用されます。

### プロジェクト固有ルール

プロジェクトの `.complete-validator/rules/` ディレクトリに `.md` ファイルを追加してください。サブディレクトリも再帰的に探索されます。そのプロジェクトのみに適用されます。組み込みルールと同名のファイルを置くと、nearest wins でプロジェクト側が優先されます。

いずれの場合も `## ` 見出しでルールを区切り、Bad/Good の具体例を記載します。

## 設定

プロジェクトの `.complete-validator/config.json` で `claude -p` の同時起動数を調整できます。

```json
{
  "max_workers": 4
}
```

デフォルトは 4 です。メモリに余裕がある環境では値を大きくすることで高速化できます。
