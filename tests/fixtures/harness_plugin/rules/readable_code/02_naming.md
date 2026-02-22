---
applies_to: ["*.py"]
---
## Naming style
- Flag only clearly unreadable names.
- Always flag placeholder names such as `tmp`, `foo`, `bar`, `bad_function`.
- Always flag single-letter parameter names except common loop indices (`i`, `j`, `k`).
- Do not flag module/file names in this harness.
- Do not flag concise but conventional names (`add`, `value`, `sanitize`) when intent is clear.
