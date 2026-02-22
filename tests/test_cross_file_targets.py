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


def test_build_reverse_map_and_expand_dependencies():
    check_style = _load_check_style_module()
    contents = {
        "main.py": "import helper\n\ndef run():\n    return helper.normalize_name('A')\n",
        "helper.py": "def normalize_name(v: str) -> str:\n    return v.lower()\n",
        "tool.py": "def tool() -> None:\n    pass\n",
    }

    reverse_map = check_style.build_reverse_python_import_map(contents)
    impacted = check_style.expand_reverse_dependencies({"helper.py"}, reverse_map)

    assert "helper.py" in impacted
    assert "main.py" in impacted
    assert "tool.py" not in impacted


def test_rule_target_pool_expands_only_for_cross_file_rules():
    check_style = _load_check_style_module()
    target_files = ["helper.py"]
    cross_targets = {"helper.py", "main.py"}

    normal_pool = check_style._rule_target_pool(
        {"cross_file": False, "dependency_scope": "python_imports"},
        target_files,
        cross_targets,
    )
    cross_pool = check_style._rule_target_pool(
        {"cross_file": True, "dependency_scope": "python_imports"},
        target_files,
        cross_targets,
    )
    unsupported_scope_pool = check_style._rule_target_pool(
        {"cross_file": True, "dependency_scope": "unknown_scope"},
        target_files,
        cross_targets,
    )

    assert normal_pool == ["helper.py"]
    assert sorted(cross_pool) == ["helper.py", "main.py"]
    assert unsupported_scope_pool == ["helper.py"]


def test_load_rules_from_dir_keeps_cross_file_options(tmp_path):
    check_style = _load_check_style_module()
    rule_dir = tmp_path / "rules"
    rule_dir.mkdir(parents=True, exist_ok=True)
    (rule_dir / "cross_file_rule.md").write_text(
        "---\n"
        'applies_to: ["*.py"]\n'
        "cross_file: true\n"
        "dependency_scope: \"python_imports\"\n"
        "---\n"
        "## Rule body\n",
        encoding="utf-8",
    )

    rules, warnings = check_style.load_rules_from_dir(rule_dir)
    assert warnings == []
    assert len(rules) == 1
    name, patterns, body, options = rules[0]
    assert name == "cross_file_rule.md"
    assert patterns == ["*.py"]
    assert "Rule body" in body
    assert options["cross_file"] is True
    assert options["dependency_scope"] == "python_imports"
