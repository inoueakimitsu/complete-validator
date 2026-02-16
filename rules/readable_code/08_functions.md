---
applies_to: ["*.py", "*.cpp", "*.cxx", "*.ts", "*.tsx", "*.js", "*.jsx", "*.java", "*.rb", "*.go", "*.c"]
---
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
