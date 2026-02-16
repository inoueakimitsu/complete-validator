---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
# 式の簡潔化

## 巨大な式を分割する

人間は一度に 3～4 つのもの (変数や概念) しか考えられません。複雑な式は中間変数に分割して、各部分に名前を付けることで理解しやすくします。

**Bad:**
```python
if line.split(':')[0].strip() == "root":
    # ...
```

**Good:**
```python
username = line.split(':')[0].strip()
if username == "root":
    # ...
```

## 要約変数で複雑な条件を単純化

複数の変数や複雑なロジックを含む条件式は、その意図を表す要約変数に代入することで、読みやすくします。

**Bad:**
```java
if (request.user.id == document.owner_id) {
    // ユーザーはこの文書を編集できる
}
if (request.user.id != document.owner_id) {
    // 文書は読み取り専用
}
```

**Good:**
```java
boolean user_owns_document = (request.user.id == document.owner_id);
if (user_owns_document) {
    // ユーザーはこの文書を編集できる
}
if (!user_owns_document) {
    // 文書は読み取り専用
}
```

## ド モルガンの法則で論理式を簡潔にする

論理式を等価な別の形に変換することで、複雑な否定条件を読みやすくします。

**Bad:**
```cpp
if (!(file_exists && !is_protected)) {
    Error("Sorry, could not read file.");
}
```

**Good:**
```cpp
if (!file_exists || is_protected) {
    Error("Sorry, could not read file.");
}
```

## 短絡評価の悪用を避ける

ブール演算子の短絡評価を利用して複雑なロジックを 1 行に詰め込むと、理解が難しくなります。

**Bad:**
```cpp
assert((!(bucket = FindBucket(key))) || !bucket->IsOccupied());
```

**Good:**
```cpp
bucket = FindBucket(key);
if (bucket != NULL) {
    assert(!bucket->IsOccupied());
}
```

## 複雑なロジックは逆転させて単純化する

複雑な式や条件判定は、問題を「逆転」させることで単純化できます。

**Bad:**
```cpp
bool Range::OverlapsWith(Range other) {
    return (begin >= other.begin && begin < other.end) ||
           (end > other.begin && end <= other.end) ||
           (begin <= other.begin && end >= other.end);
}
```

**Good:**
```cpp
bool Range::OverlapsWith(Range other) {
    if (other.end <= begin) return false;  // 一方の終点が、この始点よりも前
    if (other.begin >= end) return false;  // 一方の始点が、この終点よりも後
    return true;  // 残ったものは重なっている
}
```

## 重複した式を変数に抽出する

コード内に何度も現れる同じ式は、変数として関数の上部に抽出します。

**Bad:**
```javascript
var update_highlight = function (message_num) {
    if ($("#vote_value" + message_num).html() === "Up") {
        $("#thumbs_up" + message_num).addClass("highlighted");
        $("#thumbs_down" + message_num).removeClass("highlighted");
    } else if ($("#vote_value" + message_num).html() === "Down") {
        $("#thumbs_up" + message_num).removeClass("highlighted");
        $("#thumbs_down" + message_num).addClass("highlighted");
    }
};
```

**Good:**
```javascript
var update_highlight = function (message_num) {
    var thumbs_up = $("#thumbs_up" + message_num);
    var thumbs_down = $("#thumbs_down" + message_num);
    var vote_value = $("#vote_value" + message_num).html();
    var hi = "highlighted";

    if (vote_value === "Up") {
        thumbs_up.addClass(hi);
        thumbs_down.removeClass(hi);
    } else if (vote_value === "Down") {
        thumbs_up.removeClass(hi);
        thumbs_down.addClass(hi);
    }
};
```
