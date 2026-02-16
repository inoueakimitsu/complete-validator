---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
# ライブラリとシンプルさ

## ライブラリの機能を活用してコードを簡潔にする

言語やフレームワークの豊富なメソッドやAPIを活用し、複雑な自作ロジックを避けます。ライブラリが提供する高レベルAPIを使うことで、不要なコード記述を避けられます。

**Bad:**
```javascript
var show_next_tip = function () {
  var num_tips = $('.tip').size();
  var shown_tip = $('.tip:visible');
  var shown_tip_num = Number(shown_tip.attr('id').slice(4));
  if (shown_tip_num === num_tips) {
    $('#tip-1').show();
  } else {
    $('#tip-' + (shown_tip_num + 1)).show();
  }
  shown_tip.hide();
};
```

**Good:**
```javascript
var show_next_tip = function () {
  var cur_tip = $('.tip:visible').hide();
  var next_tip = cur_tip.next('.tip');
  if (next_tip.size() === 0) {
    next_tip = $('.tip:first');
  }
  next_tip.show();
};
```

## 標準ライブラリを定期的に学習する

標準ライブラリの関数やモジュールの名前を定期的 (15 分程度) に読み直し、適切なツールを活用します。自前実装より標準ライブラリを使います。

**Bad:**
```cpp
// 重複排除を自前実装
std::vector<int> unique(std::vector<int>& elements) {
    std::map<int, bool> seen;
    std::vector<int> result;
    for (int e : elements) {
        if (seen.find(e) == seen.end()) {
            result.push_back(e);
            seen[e] = true;
        }
    }
    return result;
}
```

**Good:**
```cpp
// 標準ライブラリを使用
std::set<int> unique_set(elements.begin(), elements.end());
std::vector<int> result(unique_set.begin(), unique_set.end());
```

## 不要な機能は実装しない

過度に見積もられた機能はプロジェクトを複雑化させ、テストと保守のコストが増加します。要求を詳しく調べ、本当に必要な機能だけを実装します。

**Bad:**
```python
# 日付変更線、極地、曲率調整などの複雑な処理を全て実装
def find_nearest_store(lat, lon):
    handle_international_dateline()
    handle_poles()
    adjust_curvature()
    # 100行以上の複雑な実装
```

**Good:**
```python
# 必要な機能のみに限定 (テキサス州のみ対応)
def find_nearest_store_in_texas(lat, lon):
    nearest = None
    min_distance = float('inf')
    for store in stores:
        dist = distance(lat, lon, store.lat, store.lon)
        if dist < min_distance:
            min_distance = dist
            nearest = store
    return nearest
```

## 単純な解決策でも要件の一部を満たせれば検討する

複雑な完全解の代わりに、シンプルで理解しやすい部分解が要件を十分に満たすか検討します。90%の効果をより少ないコードで実現できることが多いです。

**Bad:**
```java
// LRU キャッシュを手動実装 (ハッシュ テーブルと単方向リストで約 100 行)
```

**Good:**
```java
// アクセスが常に順序通りなので、単一項目キャッシュで十分 (数行)
DiskObject lastUsed;
DiskObject lookup(String key) {
    if (lastUsed == null || !lastUsed.key().equals(key)) {
        lastUsed = loadDiskObject(key);
    }
    return lastUsed;
}
```

## 未使用のコードを削除する

実装した機能が使用されていない場合、定期的に削除します。コードを書く時間投資を恐れて未使用コードを保持すべきではありません。

**Bad:**
```python
def handle_international_filenames(path):
    """国際的なファイル名を処理 (実装されたが使われていない)"""
    pass

def recover_from_memory_shortage():
    """メモリ不足からの回復ロジック (実装されたが使われない)"""
    pass
```

**Good:**
```python
# 実際に使用される機能のみを実装
def handle_common_filenames(path):
    pass
```
