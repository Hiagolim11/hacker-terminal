"""Lightweight project context detection without invoking external commands."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectContext:
    root: Path | None
    branch: str | None
    environment: str | None


def find_git_root(directory: Path) -> Path | None:
    current = directory.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def read_git_branch(root: Path | None) -> str | None:
    if root is None:
        return None
    git_path = root / ".git"
    if git_path.is_file():
        try:
            pointer = git_path.read_text(encoding="utf-8").strip()
            if pointer.startswith("gitdir:"):
                git_path = (root / pointer.removeprefix("gitdir:").strip()).resolve()
        except OSError:
            return None
    try:
        head = (git_path / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if head.startswith("ref: refs/heads/"):
        return head.removeprefix("ref: refs/heads/")
    return head[:8] if head else None


def detect_project_context(directory: Path) -> ProjectContext:
    root = find_git_root(directory)
    environment_path = os.environ.get("VIRTUAL_ENV")
    environment = Path(environment_path).name if environment_path else None
    if environment is None and root is not None and (root / ".venv").is_dir():
        environment = ".venv"
    return ProjectContext(root, read_git_branch(root), environment)
