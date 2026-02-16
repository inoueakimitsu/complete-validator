---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
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
