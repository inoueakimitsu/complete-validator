---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
# コードレビューとコミット

## 小さな diff で commit する

変更を commit する際、diff だけを読んでも読みやすいコードになっているか判断できるように、コード変更を小分けにして commit します。1 つの diff に 1 つの変更を。各改善方法ごとに別々にコミットすることで、diff の目的が明確になり、レビュアーが変更の意図を理解しやすくなります。

**Bad:**
```
git add file1.py file2.py file3.py
git commit -m "Improve code readability"
# 3つのファイルで異なる改善を同時に行っている
```

**Good:**
```
git add file1.py
git commit -m "Use clearer variable names in fetch_data()"

git add file2.py
git commit -m "Align vertical lines in data structures"
```

## 添削コミットで改善例を示す

他の開発者が書いたコードが読みにくい場合、直接「こうすれば読みやすくなる」というコードを改善 commit として提示します。コミットメッセージになぜこの書き方の方が読みやすいのかという理由を記載します。まずは自分が仲間の diff を読み、フィードバックすることで、チーム全体で code review する文化を作ります。

**Bad:**
```
レビューコメント: 「この関数はもっと読みやすくできます」
```

**Good:**
```
Commit: 添削コミット
コミットメッセージ:
「関数の責任を小さくしたので、意図が明確になりました。
元のバージョンでは関数が複数の異なる処理を行っており、
読者がすべての処理を追跡する必要がありました。
この変更により、各関数は単一の責任を担うようになり、
diff を読むだけで動作が理解しやすくなります。」

変更内容: 大きな関数を複数の小さな関数に分割
```
