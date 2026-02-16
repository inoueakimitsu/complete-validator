---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
# 変数管理

## 役に立たない一時変数を削除する

複雑な式を分割していない、より明確にしていない、一度しか使わない一時変数は削除します。

**Bad:**
```python
now = datetime.datetime.now()
root_message.last_view_time = now
```

**Good:**
```python
root_message.last_view_time = datetime.datetime.now()
```

## 制御フロー変数を避ける

プログラムの実行を制御するためだけの変数 (done フラグなど) は削除します。break や return を使用することで、同じ目的を達成できます。

**Bad:**
```cpp
boolean done = false;
while (/* 条件 */ && !done) {
    if (...) {
        done = true;
        continue;
    }
}
```

**Good:**
```cpp
while (/* 条件 */) {
    if (...) {
        break;
    }
}
```

## 変数のスコープを最小限に縮める

グローバル変数やメンバ変数を避け、変数のスコープをできるだけ小さくします。

**Bad:**
```cpp
class LargeClass {
    string str_;
    void Method1() {
        str_ = ...;
        Method2();
    }
    void Method2() {
        // str_ を使っている
    }
    // str_ を使わないメソッドがたくさんある
};
```

**Good:**
```cpp
class LargeClass {
    void Method1() {
        string str = ...;
        Method2(str);
    }
    void Method2(string str) {
        // str を使っている
    }
};
```

## 変数定義を使用直前に移動する

変数の定義を関数の先頭に集めるのではなく、実際に使用する直前に定義します。

**Bad:**
```python
def ViewFilteredReplies(original_id):
    filtered_replies = []
    root_message = Messages.objects.get(original_id)
    all_replies = Messages.objects.select(root_id=original_id)
    # ... ここで filtered_replies と all_replies は未使用
    root_message.view_count += 1
    # ... ずっとあとに使用
    for reply in all_replies:
        if reply.spam_votes <= MAX_SPAM_VOTES:
            filtered_replies.append(reply)
    return filtered_replies
```

**Good:**
```python
def ViewFilteredReplies(original_id):
    root_message = Messages.objects.get(original_id)
    root_message.view_count += 1
    all_replies = Messages.objects.select(root_id=original_id)
    filtered_replies = []
    for reply in all_replies:
        if reply.spam_votes <= MAX_SPAM_VOTES:
            filtered_replies.append(reply)
    return filtered_replies
```

## 変数は一度だけ書き込む

変数は設定後に変更しない設計にします。変更が必要な場合は const/final などのイミュータブル修飾子を使います。

**Bad:**
```javascript
var value = 0;
value = calculateA();
value = value + calculateB();
value = value * calculateC();
```

**Good:**
```javascript
const valueA = calculateA();
const valueB = valueA + calculateB();
const result = valueB * calculateC();
```
