---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
# 命名規則

## 明確な単語を名前に選ぶ

「get」「size」など空虚で不明確な単語を避け、実際の動作や目的を表す具体的で明確な単語を使います。

**Bad:**
```python
def get_page(url):
    pass

class BinaryTree:
    def size(self):  # 高さ? ノード数? メモリ消費量?
        pass
```

**Good:**
```python
def fetch_page(url):  # インターネットから取得することが明確
    pass

class BinaryTree:
    def num_nodes(self):
        pass
    def memory_bytes(self):
        pass
```

## 汎用的な名前 (retval、tmp など) を避ける

「tmp」「retval」「foo」などの空虚な名前ではなく、変数の値や目的を表す具体的な名前を選びます。

**Bad:**
```python
def euclidean_norm(v):
    retval = 0.0  # 「これは戻り値」以外の情報がない
    for i in range(len(v)):
        retval += v[i] * v[i]
    return math.sqrt(retval)
```

**Good:**
```python
def euclidean_norm(v):
    sum_squares = 0.0  # 変数の目的 (2 乗の合計) が明確
    for i in range(len(v)):
        sum_squares += v[i] * v[i]
    return math.sqrt(sum_squares)
```

## ループ イテレーターには説明的な名前をつける

ネストが深い場合は、ループの対象を表した名前 (`club_i`、`member_i`、`user_i`) を使うとバグが見つけやすくなります。

**Bad:**
```cpp
for (int i = 0; i < clubs.size(); i++)
    for (int j = 0; j < clubs[i].members.size(); j++)
        for (int k = 0; k < users.size(); k++)
            if (clubs[i].members[j] == users[k])  // インデックスが逆で見つけにくい
                cout << "user[" << k << "] is in club[" << i << "]" << endl;
```

**Good:**
```cpp
for (int ci = 0; ci < clubs.size(); ci++)
    for (int mi = 0; mi < clubs[ci].members.size(); mi++)
        for (int ui = 0; ui < users.size(); ui++)
            if (clubs[ci].members[mi] == users[ui])
                cout << "user[" << ui << "] is in club[" << ci << "]" << endl;
```

## 抽象的な名前よりも具体的な名前を使う

メソッドの動作を直接表した具体的な名前にします。抽象的で曖昧な名前は避けます。

**Bad:**
```java
boolean serverCanStart()  // 抽象的 - 何をリッスンするのか不明確
```

**Good:**
```java
boolean canListenOnPort()  // 具体的 - TCP/IPポートをリッスンできるか
```

## 変数名にフォーマットや型情報を追加する

データのフォーマットが重要な場合は、変数名に情報を追加します。

**Bad:**
```python
id = "af84ef845cd8"  # 16進数か、その他の形式か不明確
```

**Good:**
```python
hex_id = "af84ef845cd8"  # 16進数であることが明示される
```

## 計測可能な値には単位を名前に含める

時間、バイト数、速度などの単位がある値には、変数名に単位を含めます。

**Bad:**
```javascript
var start = (new Date()).getTime();      // 秒? ミリ秒?
var elapsed = (new Date()).getTime() - start;
document.writeln("読み込み時間:" + elapsed + " 秒");
```

**Good:**
```javascript
var start_ms = (new Date()).getTime();      // ミリ秒であることが明示
var elapsed_ms = (new Date()).getTime() - start_ms;
document.writeln("読み込み時間:" + (elapsed_ms / 1000) + " 秒");
```

## セキュリティ上の注意が必要なデータに属性を追加する

ユーザー入力や信頼できないデータには、処理前の状態を示す属性を名前に追加します。

**Bad:**
```python
password = get_user_input()          # そのまま使う?
comment = request.get_parameter()    # エスケープされてる?
```

**Good:**
```python
plaintext_password = get_user_input()    # 暗号化が必要
unescaped_comment = request.get_parameter()  # エスケープが必要
untrusted_url = get_external_input()
trusted_url = validate_and_sanitize(untrusted_url)
```

## スコープに合わせた名前の長さを選ぶ

スコープが大きい変数には長い名前をつけます。数行のみのスコープでは短い名前も許容されます。

**Bad:**
```cpp
// グローバルスコープで短い名前を使用
int m;  // 何を表しているかわからない
LookUpNamesNumbers(&m);
```

**Good:**
```cpp
// ローカルスコープ内で短い名前を使用
if (debug) {
  map<string, int> m;
  LookUpNamesNumbers(&m);
  Print(m);
}

// グローバルスコープでは長く明確な名前
map<string, int> name_to_count;
```

## プロジェクト固有の省略形を避ける

新しくプロジェクトに参加した人にとって理解しにくい省略形は避けます。

**Bad:**
```python
class BEManager:  # BackEndManager の省略、新人には意味不明
  pass
```

**Good:**
```python
class BackEndManager:  # 完全な名前で明確
  pass
```

## あいまいな関数名を避ける

filter() は「選択する」のか「除外する」のか解釈が分かれるため、select() か exclude() など明確な関数名を使い分けます。

**Bad:**
```python
results = Database.all_objects.filter("year <= 2011")
# results に 「year <= 2011」 が含まれるのか、含まれないのか不明確
```

**Good:**
```python
selected = Database.all_objects.select("year <= 2011")
excluded = Database.all_objects.exclude("year <= 2011")
```

## 限界値には min/max プレフィックスを使う

「以下」と「未満」の誤解を防ぐため、限界値の名前には min_ または max_ プレフィックスを付けます。

**Bad:**
```python
CART_TOO_BIG_LIMIT = 10
if shopping_cart.num_items() >= CART_TOO_BIG_LIMIT:  # >= か > か不明確
  Error("カートにある商品数が多すぎます。")
```

**Good:**
```python
MAX_ITEMS_IN_CART = 10
if shopping_cart.num_items() > MAX_ITEMS_IN_CART:
  Error("カートにある商品数が多すぎます。")
```

## 包含的範囲には first と last を使う

範囲の終端を含める場合は「first」「last」を使います。

**Bad:**
```python
print integer_range(start=2, stop=4)  # [2,3]？ [2,3,4]？
```

**Good:**
```python
set.PrintKeys(first="Bart", last="Maggie")  # Bart から Maggie までを含む
```

## 包含排他的範囲には begin と end を使う

範囲が始端を含み終端を除く場合 (半開区間) は、「begin」「end」を使います。

**Bad:**
```python
print_events_in_range(from="OCT 16 12:00am", to="OCT 17 12:00am")
```

**Good:**
```python
print_events_in_range(begin="OCT 16 12:00am", end="OCT 17 12:00am")
```

## ブール値の名前に接頭辞をつける

ブール値の変数、関数には「is」「has」「can」「should」などの接頭辞をつけ、true/false の意味を明確にします。

**Bad:**
```python
read_password = True  # これから読み取る? すでに読み取った?
```

**Good:**
```python
user_is_authenticated = True
has_space_left = True
can_edit_document = True
```

## ブール値の否定形を避ける

ブール変数を否定形にすると読みづらくなるため、肯定形を使います。

**Bad:**
```python
disable_ssl = False
if not disable_ssl:
    connect_securely()
```

**Good:**
```python
use_ssl = True
if use_ssl:
    connect_securely()
```

## get メソッドはアクセサーのみにする

get で始まるメソッドは軽量なアクセサーという規約があります。重い計算を行う場合は「compute」や「calculate」などの名前を使います。

**Bad:**
```java
public class StatisticsCollector {
    public double getMean() {
        // すべてのサンプルをイテレートして平均を計算
        return total / num_samples;
    }
}
```

**Good:**
```java
public class StatisticsCollector {
    public double computeMean() {
        // コスト高い処理であることが名前から明確
        return total / num_samples;
    }
}
```
