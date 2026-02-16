---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
# 制御フロー

## 条件式の両辺の順序を自然に配置する

条件式では左側に「調査対象」 (変わる値)、右側に「比較対象」 (比較の基準、変わらない値) を配置します。

**Bad:**
```
if (10 <= length) {
    // ...
}
while (bytes_expected < bytes_received) {
    // ...
}
```

**Good:**
```
if (length >= 10) {
    // ...
}
while (bytes_received < bytes_expected) {
    // ...
}
```

## 否定形より肯定形の条件を使う

if/else ブロックの条件は、否定形 (if (!condition)) より肯定形 (if (condition)) を使います。

**Bad:**
```python
if not debug:
    # 処理
else:
    # デバッグ処理
```

**Good:**
```python
if debug:
    # デバッグ処理
else:
    # 処理
```

## if/else ブロックは単純な条件を先に書く

複数の条件がある場合、単純で関心を引く条件を先に処理します。

**Bad:**
```javascript
if (!url.hasQueryParameter("expand_all")) {
    response.render(items);
} else {
    for (let i = 0; i < items.length; i++) {
        items[i].expand();
    }
}
```

**Good:**
```javascript
if (url.hasQueryParameter("expand_all")) {
    for (let i = 0; i < items.length; i++) {
        items[i].expand();
    }
} else {
    response.render(items);
}
```

## 三項演算子は単純な場合にのみ使う

三項演算子は行数を短くするためではなく、コードが簡潔になる場合に限定して使います。

**Bad:**
```cpp
return exponent == 0 ? mantissa * (1 << exponent) : mantissa / (1 << -exponent);
```

**Good (複雑な処理):**
```cpp
if (exponent >= 0) {
    return mantissa * (1 << exponent);
} else {
    return mantissa / (1 << -exponent);
}
```

**Good (単純な値の選択):**
```cpp
time_str += (hour >= 12) ? "pm" : "am";
```

## do/while ループを避ける

do/while ループはループ条件が下に書かれるため不自然です。可能な限り while ループで書き直します。

**Bad:**
```java
do {
    if (node.name().equals(name))
        return true;
    node = node.next();
} while (node != null && --max_length > 0);
```

**Good:**
```java
while (node != null && max_length-- > 0) {
    if (node.name().equals(name)) return true;
    node = node.next();
}
return false;
```

## 関数から早く返す (ガード節の活用)

複数の return 文を使って失敗ケースを早めに関数から返すことで、ネストを減らし可読性を向上させます。

**Bad:**
```python
def contains(str, substr):
    if str is not None and substr is not None:
        if substr == "":
            return True
        else:
            # 検索処理
            pass
    return False
```

**Good:**
```python
def contains(str, substr):
    if str is None or substr is None:
        return False
    if substr == "":
        return True
    # 検索処理
```

## ネストを浅くする

ネストが深いコードは読み手に精神的スタックの負担を強います。条件の変化を記憶しておく必要が増え、理解が困難になります。

**Bad:**
```java
if (user_result == SUCCESS) {
    if (permission_result != SUCCESS) {
        reply.WriteErrors("error reading permissions");
        reply.Done();
        return;
    }
    reply.WriteErrors("");
} else {
    reply.WriteErrors(user_result);
}
reply.Done();
```

**Good:**
```java
if (user_result != SUCCESS) {
    reply.WriteErrors(user_result);
    reply.Done();
    return;
}
if (permission_result != SUCCESS) {
    reply.WriteErrors("error reading permissions");
    reply.Done();
    return;
}
reply.WriteErrors("");
reply.Done();
```

## ループ内での continue による条件スキップ

関数内での早期 return と同様に、ループ内では continue を使ってネストを浅くできます。

**Bad:**
```cpp
for (int i = 0; i < results.size(); i++) {
    if (results[i] != NULL) {
        non_null_count++;
        if (results[i]->name != "") {
            cout << "Considering candidate..." << endl;
        }
    }
}
```

**Good:**
```cpp
for (int i = 0; i < results.size(); i++) {
    if (results[i] == NULL) continue;
    non_null_count++;
    if (results[i]->name == "") continue;
    cout << "Considering candidate..." << endl;
}
```
