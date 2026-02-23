---
applies_to:
  - "*.txt"
---
# E2E Block Rule
If the target file content includes the token `E2E_BLOCK`, you must report a violation.
Return deny for that file.
