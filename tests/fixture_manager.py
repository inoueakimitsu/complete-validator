"""Test fixture loading for static/dynamic scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class StaticFixture:
    path: Path
    name: str
    repo_path: Path
    diff_path: Path | None
    annotations: dict[str, Any]


@dataclass
class DynamicFixture:
    path: Path
    name: str
    steps_path: Path
    target_file: str
    interval_seconds: int
    steps: list[dict[str, Any]]
    annotations: list[dict[str, Any]]


@dataclass
class DynamicStep:
    step: int
    time_offset: int
    append: str


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class FixtureManager:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_static_fixtures(self, fixture_filter: list[str] | None = None) -> list[StaticFixture]:
        root = self.root / "static"
        if not root.exists():
            return []

        fixture_dirs = sorted([p for p in root.iterdir() if p.is_dir() and p.name.startswith("case_")])
        if fixture_filter:
            wanted = set(fixture_filter)
            fixture_dirs = [p for p in fixture_dirs if p.name in wanted or str(p.relative_to(root)) in wanted]

        fixtures: list[StaticFixture] = []
        for path in fixture_dirs:
            repo_path = path / "repo"
            annotations = _load_json(path / "annotations.json")
            if not repo_path.exists() or annotations is None:
                continue
            fixtures.append(
                StaticFixture(
                    path=path,
                    name=path.name,
                    repo_path=repo_path,
                    diff_path=(path / "diff.patch") if (path / "diff.patch").exists() else None,
                    annotations=annotations,
                )
            )
        return fixtures

    def list_dynamic_fixtures(
        self,
        fixture_filter: list[str] | None = None,
    ) -> list[DynamicFixture]:
        root = self.root / "dynamic"
        if not root.exists():
            return []

        fixture_dirs = sorted([p for p in root.iterdir() if p.is_dir() and p.name.startswith("meeting_")])
        if fixture_filter:
            wanted = set(fixture_filter)
            fixture_dirs = [p for p in fixture_dirs if p.name in wanted or str(p.relative_to(root)) in wanted]

        fixtures: list[DynamicFixture] = []
        for path in fixture_dirs:
            steps_path = path / "steps.json"
            data = _load_json(steps_path)
            if not data:
                continue
            fixtures.append(
                DynamicFixture(
                    path=path,
                    name=path.name,
                    steps_path=steps_path,
                    target_file=data.get("target_file", ""),
                    interval_seconds=int(data.get("interval_seconds", 5)),
                    steps=[s for s in data.get("steps", []) if isinstance(s, dict)],
                    annotations=list(data.get("annotations", [])),
                )
            )
        return fixtures


def read_annotations(static_fixture: StaticFixture) -> list[dict[str, Any]]:
    annotations = static_fixture.annotations.get("annotations", []) if isinstance(static_fixture.annotations, dict) else []
    return [a for a in annotations if isinstance(a, dict)]


def read_dynamic_annotations(dynamic_fixture: DynamicFixture) -> list[dict[str, Any]]:
    return [a for a in dynamic_fixture.annotations if isinstance(a, dict)]


def read_all_annotations(fixture: StaticFixture | DynamicFixture) -> list[dict[str, Any]]:
    if isinstance(fixture, StaticFixture):
        return read_annotations(fixture)
    if isinstance(fixture, DynamicFixture):
        return read_dynamic_annotations(fixture)
    return []
