---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
# 基本原則

## 理解性を最優先にコードを書く

コードは読む人が最短時間で理解できるように書きます。コード長より理解時間を優先します。

**Bad:**
```python
assert((!(bucket = FindBucket(key))) || !bucket->IsOccupied())
```

**Good:**
```python
bucket = FindBucket(key)
if bucket is not None:
    assert not bucket.is_occupied()
```
