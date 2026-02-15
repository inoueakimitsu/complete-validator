---
applies_to: ["*.py"]
---
# Python Style Rules

## docstring 必須

すべての関数、クラス、メソッド (private を含む) に docstring を記述してください。引数がある場合は Parameters セクション、戻り値がある場合は Returns セクションも記述してください。

**Bad:**
```python
def calculate_total(prices: list[float], tax_rate: float) -> float:
    return sum(prices) * (1 + tax_rate)


class DataProcessor:
    def process(self, data: list[str]) -> list[str]:
        return [d.strip() for d in data]
```

**Good:**
```python
def calculate_total(prices: list[float], tax_rate: float) -> float:
    """税込み合計金額を計算します。

    Parameters
    ----------
    prices: list[float]
        商品価格のリストです。
    tax_rate: float
        税率です。

    Returns
    -------
    float
        税込み合計金額です。
    """
    return sum(prices) * (1 + tax_rate)


class DataProcessor:
    """データの前処理を行うクラスです。"""

    def process(self, data: list[str]) -> list[str]:
        """文字列リストの前後の空白を除去します。

        Parameters
        ----------
        data: list[str]
            処理対象の文字列リストです。

        Returns
        -------
        list[str]
            空白を除去した文字列リストです。
        """
        return [d.strip() for d in data]
```

## NumPy 形式 docstring

docstring は NumPy 形式で書いてください。Parameters と Returns 内もスタイルを合わせてください。

**Bad:**
```python
def func(x):
    """処理を実行する。

    Args:
        x: 入力値
    """
```

**Good:**
```python
def func(x: int) -> str:
    """処理を実行します。

    Parameters
    ----------
    x: int
        入力値です。

    Returns
    -------
    str
        結果の文字列です。
    """
```

## docstring 内の型ヒント記法

docstring 内の型ヒントでは、変数名と `:` の間にスペースを入れないでください。`:` の後にはスペースを 1 つ入れてください。このルールは docstring 内の型ヒント記法にのみ適用し、通常のコード (スライス記法など) には適用しないでください。

**Bad:**
```python
"""
Parameters
----------
target_file : io.BytesIO
    対象ファイルです。
target_columns : list[str]
    対象カラムのリストです。
correct :str | None
    正解文字列です。
"""
```

**Good:**
```python
"""
Parameters
----------
target_file: io.BytesIO
    対象ファイルです。
target_columns: list[str]
    対象カラムのリストです。
correct: str | None
    正解文字列です。
"""
```

以下はこのルールの対象外です。修正しないでください。

```python
sentence[i : i + 512]  # スライス記法であり型ヒントではないため対象外
```

## No Bare Except

Never use bare `except:` clauses. Always specify the exception type.
At minimum, use `except Exception:`.

**Bad:**
```python
try:
    do_something()
except:
    pass
```

**Good:**
```python
try:
    do_something()
except ValueError:
    handle_error()
```

## Type Hints on Public Functions

All public functions and methods must have type hints for parameters and return values.

**Bad:**
```python
def get_user(user_id):
    ...
```

**Good:**
```python
def get_user(user_id: int) -> User:
    ...
```

## Import Organization

Imports must be organized in three groups, separated by blank lines:
1. Standard library imports
2. Third-party imports
3. Local/project imports

Each group should be sorted alphabetically.

**Bad:**
```python
import my_module
import os
import requests
```

**Good:**
```python
import os
import sys

import requests

import my_module
```

## No Print Statements

Use the `logging` module instead of `print()` for any output.
`print()` is acceptable only in CLI entry points or scripts explicitly designed for console output.

**Bad:**
```python
def process_data(data):
    print(f"Processing {len(data)} items")
    ...
```

**Good:**
```python
import logging

logger = logging.getLogger(__name__)

def process_data(data):
    logger.info("Processing %d items", len(data))
    ...
```
