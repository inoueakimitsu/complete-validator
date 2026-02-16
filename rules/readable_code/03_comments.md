---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
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
