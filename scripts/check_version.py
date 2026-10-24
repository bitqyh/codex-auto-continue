#!/usr/bin/env python3
"""Verify that the release tag matches every version declaration in the repo."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(pattern: str, path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise SystemExit(f"cannot find version in {path}")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="", help="tag name, e.g. v0.5.0 or refs/tags/v0.5.0")
    args = parser.parse_args()

    versions = {
        "pyproject.toml": read(r'^version = "([^"]+)"', ROOT / "pyproject.toml"),
        "__init__.py": read(r'^__version__ = "([^"]+)"', ROOT / "src" / "codex_auto_continue" / "__init__.py"),
    }
    unique = set(versions.values())
    if len(unique) != 1:
        print("version mismatch:", versions, file=sys.stderr)
        return 1
    version = unique.pop()

    if args.tag:
        expected = args.tag.removeprefix("refs/tags/")
        if expected.startswith("v"):
            expected = expected[1:]
        if expected != version:
            print(f"tag {args.tag!r} does not match repo version {version!r}", file=sys.stderr)
            return 1

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
