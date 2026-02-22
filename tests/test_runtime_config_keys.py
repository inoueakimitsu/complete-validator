import importlib.util
import sys
from pathlib import Path


def _load_check_style_module():
    root = Path(__file__).resolve().parents[1]
    scripts_dir = root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    module_path = scripts_dir / "check_style.py"
    spec = importlib.util.spec_from_file_location("check_style", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_config_parsers_cover_context_cache_batching():
    check_style = _load_check_style_module()
    assert check_style.get_context_level({"context_level": "diff"}) == "diff"
    assert check_style.get_context_level({"context_level": "full_file"}) == "full_file"
    assert check_style.get_context_level({"context_level": "smart"}) == "smart"
    assert check_style.get_context_level({"context_level": "invalid"}) == "diff"

    assert check_style.get_cache_enabled({"cache": True}) is True
    assert check_style.get_cache_enabled({"cache": False}) is False
    assert check_style.get_cache_enabled({"cache": "x"}) is True

    assert check_style.get_batching_enabled({"batching": True}) is True
    assert check_style.get_batching_enabled({"batching": False}) is False
    assert check_style.get_batching_enabled({"batching": "x"}) is False


def test_check_single_rule_respects_context_level_and_cache_toggle(monkeypatch):
    check_style = _load_check_style_module()
    captured = {"full_scan": None, "get_called": False, "put_called": False}

    class DummyCache:
        def get(self, key):
            captured["get_called"] = True
            return None

        def put(self, key, value):
            captured["put_called"] = True

    def fake_build_prompt(rule_name, rule_body, file_path, file_content, file_diff, suppressions="", full_scan=False):
        captured["full_scan"] = full_scan
        return "prompt"

    monkeypatch.setattr(check_style, "build_prompt_for_single_file", fake_build_prompt)
    monkeypatch.setattr(check_style, "run_claude_check", lambda prompt, model="sonnet": "No violations found.")

    result = check_style.check_single_rule_single_file(
        rule_name="r.md",
        rule_body="## body",
        file_path="a.py",
        file_content="print('x')\n",
        file_diff="+print('x')\n",
        suppressions="",
        cache=DummyCache(),
        full_scan=False,
        model="sonnet",
        context_level="full_file",
        cache_enabled=False,
    )

    assert result[2] == "allow"
    assert captured["full_scan"] is True
    assert captured["get_called"] is False
    assert captured["put_called"] is False


def test_run_parallel_checks_batching_changes_unit_order(monkeypatch):
    check_style = _load_check_style_module()
    recorded: list[tuple[str, str]] = []

    def fake_check(rule_name, rule_body, file_path, file_content, file_diff, suppressions, cache, **kwargs):
        recorded.append((rule_name, file_path))
        return (rule_name, file_path, "allow", "No violations found.", False)

    class DummyCache:
        def get(self, key):
            return None

        def put(self, key, value):
            return None

    monkeypatch.setattr(check_style, "check_single_rule_single_file", fake_check)

    rules = [
        ("rule_b.md", ["*.py"], "body", {}),
        ("rule_a.md", ["*.py"], "body", {}),
    ]
    target_files = ["b.py", "a.py"]
    files = {"a.py": "print('a')", "b.py": "print('b')"}
    diff_chunks = {"a.py": "+a", "b.py": "+b"}

    check_style.run_parallel_checks(
        rules=rules,
        target_files=target_files,
        files=files,
        diff_chunks=diff_chunks,
        suppressions="",
        cache=DummyCache(),
        full_scan=False,
        max_workers=1,
        model="sonnet",
        batching_enabled=False,
    )
    without_batching = list(recorded)

    recorded.clear()
    check_style.run_parallel_checks(
        rules=rules,
        target_files=target_files,
        files=files,
        diff_chunks=diff_chunks,
        suppressions="",
        cache=DummyCache(),
        full_scan=False,
        max_workers=1,
        model="sonnet",
        batching_enabled=True,
    )
    with_batching = list(recorded)

    assert without_batching != with_batching
    assert with_batching[0][1] <= with_batching[-1][1]
