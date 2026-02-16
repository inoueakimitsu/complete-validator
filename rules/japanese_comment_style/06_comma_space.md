---
applies_to: ["*.py", "*.md"]
---
## 全角カンマ後のスペース禁止

読点「、」の直後に半角スペースを入れないでください。

**Bad:**
```python
# xyz と相関の強い、 factor_candidate_list の要素を抽出します。
```

**Good:**
```python
# xyz と相関の強い、factor_candidate_list の要素を抽出します。
```
