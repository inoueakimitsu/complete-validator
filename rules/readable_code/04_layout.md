---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
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
