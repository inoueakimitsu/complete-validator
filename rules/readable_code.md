---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---

# リーダブルコード - 統合ルール集

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

# コメント

## 自明な情報はコメントに書かない

コードから直ちに理解できる情報をコメントに記述しません。

**Bad:**
```cpp
// Account クラスの定義
class Account {
public:
    // コンストラクタ
    Account();
    // profit に新しい値を設定する
    void SetProfit(double profit);
};
```

**Good:**
```cpp
class Account {
public:
    Account();
    void SetProfit(double profit);
};
```

## ひどい名前にコメントを付けるのではなく、名前を改善する

コメントはひどい名前の埋め合わせに使用しません。名前そのものを改善して「自己文書化」させます。

**Bad:**
```cpp
// Reply に対して Request で記述した制限を課す。
void CleanReply(Request request, Reply reply);
```

**Good:**
```cpp
void EnforceLimitsFromRequest(Request request, Reply reply);
```

## 設計上の判断を記録する

パフォーマンスやアルゴリズム選択に関する重要な判断や、なぜ一見奇妙な実装方法を採用したのかを説明するコメントを記述します。

**Bad:**
```python
data = BinaryTree()
```

**Good:**
```python
# このデータだとハッシュテーブルよりもバイナリツリーのほうが40%速かった。
# 左右の比較よりもハッシュの計算コストのほうが高いようだ。
data = BinaryTree()
```

## 定数の背景をコメントで説明する

定数を定義する際は、その値がなぜその値に設定されているのかを説明するコメントを記述します。

**Bad:**
```python
NUM_THREADS = 8
image_quality = 0.72
```

**Good:**
```python
NUM_THREADS = 8  # 値は「>= 2 * num_processors」で十分。1だと小さすぎて、50だと大きすぎる
image_quality = 0.72  # 0.72ならユーザーはファイルサイズと品質の面で妥協できる
```

## コード内の罠や予期しない動作を警告する

他のプログラマが間違って関数を使用する可能性がある場合や、実装に非自明な制約や副作用がある場合は、事前に警告コメントを記述します。

**Bad:**
```cpp
void SendEmail(string to, string subject, string body);
```

**Good:**
```cpp
// メールを送信する外部サービスを呼び出している (1 分でタイムアウト)
// HTTPリクエスト処理中から呼び出すと、サービス遅延でアプリケーションがハングする可能性があります
void SendEmail(string to, string subject, string body);
```

## 改善が必要なコードを文書化する

コードの品質、設計の問題、または欠陥を認識している場合は、それをコメント (TODO、FIXME、HACK、XXX など) で文書化し、将来の改善を促します。

**Bad:**
```python
def analyze(data):
    # 汚い実装だが動く
    result = process(data)
    return result
```

**Good:**
```python
def analyze(data):
    # TODO: このクラスは汚くなってきている。
    # サブクラス 'ResourceNode' を作って整理したほうがいいかもしれない。
    result = process(data)
    return result
```

## ファイルやクラスに全体像のコメントを付ける

新しいチームメンバが最初に困るのが全体像の理解です。ファイルやクラスの役割、他のコンポーネントとの関係、設計の意図を簡潔に説明します。

**Bad:**
```python
# file: database.py
class Connection:
    def __init__(self):
        pass
```

**Good:**
```python
# file: database.py
# このファイルには、ファイルシステムに関する便利なインターフェースを提供
# するヘルパー関数が含まれています。ファイルのパーミッションなどを扱います。
class Connection:
    def __init__(self):
        pass
```

## 大きなコード ブロックに要約コメントを付ける

複数のステップに分かれた処理を行う際に、各ブロックの目的を簡潔に説明します。

**Bad:**
```python
def GenerateUserReport():
    # ... long code block ...
    for x in all_items:
        # ... many lines ...
    file.write(data)
```

**Good:**
```python
def GenerateUserReport():
    # このユーザーのロックを獲得する
    acquire_lock(user_id)
    # ユーザーの情報をDBから読み込む
    user_data = db.fetch(user_id)
    # 情報をファイルに書き出す
    file.write(user_data)
    # このユーザーのロックを解放する
    release_lock(user_id)
```

## コメント内の曖昧な代名詞を避ける

コメント内で「それ」「これ」などの代名詞を使うと、読み手が解釈に時間をかけます。代名詞を具体的な名詞に置き換えます。

**Bad:**
```python
# データをキャッシュに入れる。ただし、先にそのサイズをチェックする。
```

**Good:**
```python
# データをキャッシュに入れる。ただし、先にデータのサイズをチェックする。
```

## 関数の動作を正確に記述する

関数が「何をするのか」を明確に記載します。特に「行」「サイズ」など曖昧な概念を使う場合は、実装の仕様に基づいた具体的な定義を記載します。

**Bad:**
```cpp
// このファイルに含まれる行数を返す。
int CountLines(string filename) { ... }
```

**Good:**
```cpp
// このファイルに含まれる改行文字('\n')を数える。
int CountLines(string filename) { ... }
```

## コメントで関数の入出力例を示す

複雑な関数の動作は、実例 (入力と出力の具体例) を示すことで、千言万語の説明より効果的に機能を伝えられます。

**Bad:**
```
// 'SRC'の先頭や末尾にある'chars'を除去する。
String Strip(String src, String chars) { ... }
```

**Good:**
```
// 実例: Strip("abba/a/ba", "ab")は"/a/"を返す
String Strip(String src, String chars) { ... }
```

## コメントで実装の意図 (WHY) を記述する

コードの動作 (WHAT) をそのまま説明するコメントではなく、なぜそのようにしたのか (意図) を高レベルで記述します。

**Bad:**
```
for (list<Product>::reverse_iterator it = products.rbegin(); ...) {
    // list を逆順にイテレートする
    DisplayPrice(it->price);
}
```

**Good:**
```
// 値段の高い順に表示する
for (list<Product>::reverse_iterator it = products.rbegin(); ...) {
    DisplayPrice(it->price);
}
```

## コメントを簡潔に保つ

コメントは情報密度が高く簡潔でなければなりません。複数行で説明できることは 1 行に集約すべきです。

**Bad:**
```
// int は CategoryType。
// pair の最初の float は 'score'
// 2つめは 'weight'。
typedef hash_map<int, pair<float, float> > ScoreMap;
```

**Good:**
```
// Category Type -> (score, weight)
typedef hash_map<int, pair<float, float> > ScoreMap;
```

## 名前付き引数コメントを使って引数を明確化する

言語が名前付き引数をサポートしていない場合、インライン コメントで引数の意味を明確にします。

**Bad:**
```
Connect(10, false);
```

**Good:**
```
// C++/Java の場合、インラインコメントで名前を付ける
Connect(/* timeout_ms = */ 10, /* use_encryption = */ false);
```

# コードレイアウト

## コメント位置をコードの上に移動させる

繰り返されるコメントをコード ブロックの上部にまとめて配置し、個別の行からは削除します。

**Bad:**
```
public static final Connection wifi =
new TcpConnectionSimulator(500, 80, 200, 1); /* throughput, latency, jitter, packet loss */
public static final Connection fiber =
new TcpConnectionSimulator(45000, 10, 0, 0); /* throughput, latency, jitter, packet loss */
```

**Good:**
```
// TcpConnectionSimulator (throughput, latency, jitter, packet_loss)
// [Kbps] [ms][ms] [percent]
public static final Connection wifi =
new TcpConnectionSimulator(500, 80, 200, 1);
public static final Connection fiber =
new TcpConnectionSimulator(45000, 10, 0, 0);
```

## 宣言をグループにまとめる

クラスやモジュール内の複数の関連メソッドや変数は、論理的にグループ化し、各グループにコメントをつけることで、コード全体の構造を素早く把握できるようにします。

**Bad:**
```
class FrontendServer {
public:
    FrontendServer();
    void ViewProfile(HttpRequest* request);
    void OpenDatabase(string location, string user);
    void SaveProfile(HttpRequest* request);
    void FindFriends(HttpRequest* request);
    void CloseDatabase(string location);
};
```

**Good:**
```
class FrontendServer {
public:
    FrontendServer();

    // ハンドラ
    void ViewProfile(HttpRequest* request);
    void SaveProfile(HttpRequest* request);
    void FindFriends(HttpRequest* request);

    // データベースのヘルパー
    void OpenDatabase(string location, string user);
    void CloseDatabase(string location);
};
```

## コードを段落に分割する

長い関数やメソッドを、段落 (空行とコメント) で視覚的に分割することで、関連する処理をグループ化し、全体の流れを理解しやすくします。

**Bad:**
```
def suggest_new_friends(user, email_password):
    friends = user.friends()
    friend_emails = set(f.email for f in friends)
    contacts = import_contacts(user.email, email_password)
    contact_emails = set(c.email for c in contacts)
    non_friend_emails = contact_emails - friend_emails
    suggested_friends = User.objects.select(email_in=non_friend_emails)
    return render("suggested_friends.html", display)
```

**Good:**
```
def suggest_new_friends(user, email_password):
    # ユーザーの友達のメールアドレスを取得する
    friends = user.friends()
    friend_emails = set(f.email for f in friends)

    # ユーザーのメールアカウントからすべてのメールアドレスをインポートする
    contacts = import_contacts(user.email, email_password)
    contact_emails = set(c.email for c in contacts)

    # まだ友達になっていないユーザーを探す
    non_friend_emails = contact_emails - friend_emails
    suggested_friends = User.objects.select(email_in=non_friend_emails)

    # それをページに表示する
    return render("suggested_friends.html", display)
```

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

# 関数抽出と設計

## 無関係の下位問題を別関数に抽出する

関数の高レベルの目標と直接関係のない細部の処理は、別の関数に抽出します。メインのビジネス ロジックと無関係な小さな処理 (文字列処理、データ変換、ライブラリのラッパーなど) は独立した関数に分離します。

**Bad:**
```javascript
var findClosestLocation = function (lat, lng, array) {
    var closest;
    var closest_dist = Number.MAX_VALUE;
    for (var i = 0; i < array.length; i += 1) {
        var lat_rad = radians(lat);
        var lng_rad = radians(lng);
        var lat2_rad = radians(array[i].latitude);
        var lng2_rad = radians(array[i].longitude);
        var dist = Math.acos(Math.sin(lat_rad) * Math.sin(lat2_rad) +
                             Math.cos(lat_rad) * Math.cos(lat2_rad) *
                             Math.cos(lng2_rad - lng_rad));
        if (dist < closest_dist) {
            closest = array[i];
            closest_dist = dist;
        }
    }
    return closest;
};
```

**Good:**
```javascript
var spherical_distance = function (lat1, lng1, lat2, lng2) {
    var lat1_rad = radians(lat1);
    var lng1_rad = radians(lng1);
    var lat2_rad = radians(lat2);
    var lng2_rad = radians(lng2);
    return Math.acos(Math.sin(lat1_rad) * Math.sin(lat2_rad) +
                     Math.cos(lat1_rad) * Math.cos(lat2_rad) *
                     Math.cos(lng2_rad - lng1_rad));
};

var findClosestLocation = function (lat, lng, array) {
    var closest;
    var closest_dist = Number.MAX_VALUE;
    for (var i = 0; i < array.length; i += 1) {
        var dist = spherical_distance(lat, lng, array[i].latitude, array[i].longitude);
        if (dist < closest_dist) {
            closest = array[i];
            closest_dist = dist;
        }
    }
    return closest;
};
```

## 過度な小さな関数への分割を避ける

再利用できず、コードの流れを追いにくくなるほど細かく分割すると可読性が低下します。

**Bad:**
```python
def url_safe_encrypt_obj(obj):
    obj_str = json.dumps(obj)
    return url_safe_encrypt_str(obj_str)

def url_safe_encrypt_str(data):
    encrypted_bytes = encrypt(data)
    return base64.urlsafe_b64encode(encrypted_bytes)

def encrypt(data):
    cipher = make_cipher()
    encrypted_bytes = cipher.update(data)
    encrypted_bytes += cipher.final()
    return encrypted_bytes

def make_cipher():
    return Cipher("aes_128_cbc", key=PRIVATE_KEY, init_vector=INIT_VECTOR, op=ENCODE)
```

**Good:**
```python
def url_safe_encrypt(obj):
    obj_str = json.dumps(obj)
    cipher = Cipher("aes_128_cbc", key=PRIVATE_KEY, init_vector=INIT_VECTOR, op=ENCODE)
    encrypted_bytes = cipher.update(obj_str)
    encrypted_bytes += cipher.final()
    return base64.urlsafe_b64encode(encrypted_bytes)
```

## 一度に 1 つのタスクを行うように構成する

複数の独立したタスク (パース、検証、ビジネス ロジック適用など) を同時に行うコードは理解しにくいです。タスクを列挙して、異なる関数や論理的な領域に分割します。

**Bad:**
```javascript
var vote_changed = function (old_vote, new_vote) {
    var score = get_score();
    if (new_vote !== old_vote) {
        if (new_vote === 'Up') {
            score += (old_vote === 'Down'? 2: 1);
        } else if (new_vote === 'Down') {
            score -= (old_vote === 'Up'? 2: 1);
        } else if (new_vote === "") {
            score += (old_vote === 'Up'? -1: 1);
        }
    }
    set_score(score);
};
```

**Good:**
```javascript
function vote_value(vote) {
    if (vote === 'Up') return +1;
    if (vote === 'Down') return -1;
    return 0;
}

var vote_changed = function (old_vote, new_vote) {
    var score = get_score();
    score -= vote_value(old_vote);
    score += vote_value(new_vote);
    set_score(score);
};
```

## 汎用ユーティリティ関数を作成する

言語の組み込みライブラリで提供されていない基本的なタスクは、自分で関数化して汎用ユーティリティとして整理します。

**Bad:**
```cpp
ifstream file(file_name);
file.seekg(0, ios::end);
const int file_size = file.tellg();
char* file_buf = new char[file_size];
file.seekg(0, ios::beg);
file.read(file_buf, file_size);
file.close();
```

**Good:**
```cpp
string read_file_to_string(const string& file_name) {
    ifstream file(file_name);
    file.seekg(0, ios::end);
    const int file_size = file.tellg();
    string file_buf(file_size, '\0');
    file.seekg(0, ios::beg);
    file.read(&file_buf[0], file_size);
    file.close();
    return file_buf;
}

// Usage:
string contents = read_file_to_string(file_name);
```

## 劣悪なインターフェースをラッパー関数で隠蔽する

外部ライブラリやシステムのインターフェースが複雑または不直感的である場合、ラッパー関数を作成して使いやすいインターフェースに統一します。

**Bad:**
```javascript
var max_results;
var cookies = document.cookie.split(';');
for (var i = 0; i < cookies.length; i++) {
    var c = cookies[i];
    c = c.replace(/^[ ]+/, '');
    if (c.indexOf("max_results=") === 0)
        max_results = Number(c.substring(12, c.length));
}
document.cookie = "max_results=50; expires=Wed, 1 Jan 2020 20:53:47 UTC; path=/";
```

**Good:**
```javascript
function get_cookie(name) {
    var cookies = document.cookie.split(';');
    for (var i = 0; i < cookies.length; i++) {
        var c = cookies[i].replace(/^[ ]+/, '');
        if (c.indexOf(name + "=") === 0)
            return c.substring(name.length + 1);
    }
    return null;
}

function set_cookie(name, value, days_to_expire) {
    var expires = new Date();
    expires.setDate(expires.getDate() + days_to_expire);
    document.cookie = name + "=" + value + "; expires=" + expires.toUTCString() + "; path=/";
}

// Usage:
var max_results = Number(get_cookie("max_results"));
set_cookie("max_results", "50", 30);
```

## ヘルパーメソッドによる可読性向上

複数の長い処理の繰り返しや重複がある場合、ヘルパーメソッドに抽出することで可読性を向上させます。

**Bad:**
```
assert(ExpandFullName(database_connection, "Doug Adams", &error)
    == "Mr. Douglas Adams");
assert(error == "");
assert(ExpandFullName(database_connection, "Jake Brown", &error)
    == "Mr. Jacob Brown III");
assert(error == "");
```

**Good:**
```
CheckFullName("Doug Adams", "Mr. Douglas Adams", "");
CheckFullName("Jake Brown", "Mr. Jake Brown III", "");

void CheckFullName(string partial_name,
    string expected_full_name,
    string expected_error) {
    string error;
    string full_name = ExpandFullName(database_connection, partial_name, &error);
    assert(error == expected_error);
    assert(full_name == expected_full_name);
}
```

## 複雑なロジックは自然言語で説明してから実装する

複雑なロジックは、まず簡単な言葉で説明します。その説明で使うキーワードやフレーズに注目し、説明に合わせてコードを書き直します。否定形を避けるとロジックが理解しやすくなることが多いです。

**Bad:**
```php
$is_admin = is_admin_request();
if ($document) {
  if (!$is_admin && ($document['username'] != $_SESSION['username'])) {
    return not_authorized();
  } else {
    // render page
  }
} else {
  if (!$is_admin) {
    return not_authorized();
  }
  // render page
}
```

**Good:**
```php
// 説明: 権限があるのは (1) 管理者、(2) 文書の所有者 (文書がある場合)、その他は権限がない
if (is_admin_request()) {
  // 権限あり
} elseif ($document && ($document['username'] == $_SESSION['username'])) {
  // 権限あり
} else {
  return not_authorized();
}
// ページをレンダリング
```

## オブジェクトから値を抽出する時は先に変数に割り当てる

複数の値を抽出する際は、すべての値をまず変数に割り当ててから処理します。複雑なキーや入れ子アクセスを繰り返すと読みづらくなります。

**Bad:**
```python
if location_info["LocalityName"]:
    place = location_info["LocalityName"]
if not place:
    place = location_info["SubAdministrativeAreaName"]
if not place:
    place = location_info["AdministrativeAreaName"]
```

**Good:**
```python
town = location_info.get("LocalityName")
state = location_info.get("SubAdministrativeAreaName")
country = location_info.get("CountryName")

first_half = town or state or "Middle-of-Nowhere"
second_half = country or "Planet Earth"
return first_half + ", " + second_half
```

## 複数の責務を持つクラスは分割する

1 つのクラスに多くの責務があると複雑になります。「一度に 1 つのことを」の原則に従い、責務ごとに分割します。線形な依存関係でクラスを設計し、ユーザーに公開するインターフェースは最小限にします。

**Bad:**
```cpp
class MinuteHourCounter {
    // バケツの管理、時間トラッキング、合計計算がすべて1クラスに混在
};
```

**Good:**
```cpp
class ConveyorQueue {
    // キューの管理と合計計算のみ
};

class TrailingBucketCounter {
    // 時間経過に伴うバケツシフト
    ConveyorQueue buckets;
};

class MinuteHourCounter {
    // 異なる時間スケールの複数カウンターを管理
    TrailingBucketCounter minute_counts;
    TrailingBucketCounter hour_counts;
};
```

## メモリ使用量を一定に保つ設計にする

入力数に依存しない固定のメモリ使用量を目指します。予測不能なメモリ消費は本番環境で問題になります。計算負荷の高い処理結果はキャッシュ変数に保持し、変更時のみ更新します。

**Bad:**
```cpp
class Counter {
    std::vector<Event> all_events;  // Add() が呼ばれるたびにメモリが増える
public:
    void Add(Event e) {
        all_events.push_back(e);
    }
    int Count() {
        int sum = 0;
        for (auto& e : all_events) sum += e.count;  // 毎回計算 O(n)
        return sum;
    }
};
```

**Good:**
```cpp
class Counter {
    std::deque<Event> recent_events;
    int max_size;
    int total_count = 0;  // キャッシュ変数
public:
    void Add(Event e) {
        recent_events.push_back(e);
        total_count += e.count;
        if (recent_events.size() > max_size) {
            total_count -= recent_events.front().count;
            recent_events.pop_front();
        }
    }
    int Count() {
        return total_count;  // O(1) で即座に返却
    }
};
```

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

# テスト

## テスト関数は簡潔で意図が明確であるべき

テストは短く、何をテストしているかが一目瞭然である必要があります。重要でない詳細はヘルパー関数に隠し、テストの本質を 1 行で表現できるように設計します。

**Bad:**
```cpp
void Test1(){
  vector<ScoredDocument> docs;
  docs.resize(5);
  docs[0].url = "http://example.com";
  docs[0].score = -5.0;
  docs[1].url = "http://example.com";
  docs[1].score = 1;
  docs[2].url = "http://example.com";
  docs[2].score = 4;
  SortAndFilterDocs(&docs);
  assert(docs.size() == 3);
  assert(docs[0].score == 4);
}
```

**Good:**
```cpp
void TestFilteringAndSorting_RemovesNegativeScores(){
  CheckScoresBeforeAfter("-5, 1, 4, -99998.7, 3", "4, 3, 1");
}
```

## テスト専用のミニ言語を実装する

テストで繰り返される複雑な設定を文字列形式で簡潔に表現できるようにすることで、テストコードの可読性と保守性を向上させます。

**Bad:**
```cpp
void Test1() {
    vector<ScoredDocument> docs;
    AddScoredDoc(docs, -5.0);
    AddScoredDoc(docs, 1);
    AddScoredDoc(docs, 4);
    SortAndFilterDocs(&docs);
    assert(docs[0].score == 4);
    assert(docs[1].score == 3.0);
}
```

**Good:**
```cpp
void CheckScoresBeforeAfter(string input, string expected_output) {
    vector<ScoredDocument> docs = ScoredDocsFromString(input);
    SortAndFilterDocs(&docs);
    string output = ScoredDocsToString(docs);
    assert(output == expected_output);
}

CheckScoresBeforeAfter("-5, 1, 4, -99998.7, 3", "4, 3, 1");
```

## エラー メッセージは詳細で役に立つものにする

テスト失敗時のエラー メッセージは、実際の値と期待値、入力値など、デバッグに必要な情報をすべて含めます。高度なアサート機能 (BOOST_REQUIRE_EQUAL など) を使用します。

**Bad:**
```cpp
assert(output == expected_output);
// 失敗時は "Assertion failed" とだけ表示される
```

**Good:**
```cpp
if (output != expected_output) {
    cerr << "CheckScoresBeforeAfter() failed," << endl;
    cerr << "Input: \"" << input << "\"" << endl;
    cerr << "Expected Output: \"" << expected_output << "\"" << endl;
    cerr << "Actual Output: \"" << output << "\"" << endl;
    abort();
}
```

## 適切なテスト入力値を選択する

テストは単純でありながら、コードを完全にテストできる入力値を選択します。エッジ ケース (空の入力、境界値、重複など) も含めます。

**Bad:**
```cpp
// 複雑で意味不明な値を使用
CheckScoresBeforeAfter("-99998.7, -5.0, 1, 3, 4", "4, 3, 1");
```

**Good:**
```cpp
// シンプルかつ完全なテストケース
CheckScoresBeforeAfter("-5, 1, 4", "4, 1");
void TestFiltering_EmptyVector() { ... }
void TestFiltering_WithZeroScore() { ... }
void TestSorting_DuplicateScores() { ... }
```

## テストケースは複数の小さなテストに分ける

1 つの巨大なテストで多くのシナリオをカバーするのではなく、別々の観点からコードをテストする複数の小さなテストを作成します。テスト関数の名前は説明的にし、何をテストしているかを明確にします。

**Bad:**
```cpp
void Test1(){
  // フィルタリングとソート機能を同時にテスト
  vector<ScoredDocument> docs;
  SortAndFilterDocs(&docs);
  assert(docs.size() == 3);
  assert(docs[0].score == 4);
}
```

**Good:**
```cpp
void TestFiltering_RemovesNegativeScores(){
  vector<ScoredDocument> docs = {ScoreDoc(-5.0), ScoreDoc(1), ScoreDoc(4)};
  FilterDocs(&docs);
  assert(docs.size() == 2);
}

void TestSorting_DescendingOrder(){
  vector<ScoredDocument> docs = {ScoreDoc(1), ScoreDoc(4), ScoreDoc(3)};
  SortDocs(&docs);
  assert(docs[0].score == 4);
}
```

## テストしやすい設計を心がける

コードを書く際に「これはテストしやすいか」を常に念頭に置きます。疎結合な設計、明確なインターフェース、グローバル変数の最小化、外部コンポーネントへの依存を減らすことで、自動的にテスト可能で読みやすいコードになります。

**Bad:**
```cpp
static GlobalState state;
void UpdateCounter(int value) {
  state.count += value;  // グローバル状態に依存
}
```

**Good:**
```cpp
class Counter {
  private:
    int count;
  public:
    Counter() : count(0) {}
    void Add(int value) { count += value; }
    int Get() { return count; }
};
```

## テスタビリティのために外部から時刻を注入する

クラス内で時刻を取得するのではなく、外部からパラメーターとして受け取ることで、テストしやすくバグが少なくなります。時刻の呼び出しは 1 箇所に集約します。

**Bad:**
```cpp
class Counter {
public:
    void Add(int count) {
        time_t now = time();  // クラス内で時刻取得
        // ...処理...
    }
};
```

**Good:**
```cpp
class Counter {
public:
    void Add(int count, time_t now) {  // 時刻を外部から注入
        // ...処理...
    }
};
```

## テストカバレッジを100%にする必要はない

すべてのコードをテストする必要はありません。最後の 10% (UI、どうでもいいエラー ケースなど) をテストするよりも、重要な部分をテストすることが重要です。バグのコストが低い部分はテストが割に合いません。本物のコードの読みやすさを犠牲にしてまでテストしやすさを追求してはいけません。

**Bad:**
```cpp
// すべての可能なエラーケースをテスト
void TestUIComponent_AllErrorConditions() {
  // 100個以上のテストケース
}
```

**Good:**
```cpp
// 重要な機能のみをテスト
void TestCriticalPath_ValidInput() {}
void TestCriticalPath_InvalidInput() {}
void TestErrorHandling_MajorFailures() {}
```

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
