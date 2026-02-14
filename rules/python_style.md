---
applies_to: ["*.py"]
---
# Python Style Rules

## Docstrings Required

All public functions and methods (those not starting with `_`) must have a docstring.
The docstring should describe what the function does, its parameters, and its return value.

**Bad:**
```python
def calculate_total(items):
    return sum(item.price for item in items)
```

**Good:**
```python
def calculate_total(items):
    """Calculate the total price of all items."""
    return sum(item.price for item in items)
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
