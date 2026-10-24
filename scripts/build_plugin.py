#!/usr/bin/env python3
"""Build the Codex plugin bundle: copy the CLI package into plugins/*/lib."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "codex_auto_continue"
PLUGIN = ROOT / "plugins" / "codex-auto-continue"
LIB = PLUGIN / "lib" / "codex_auto_continue"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"


def package_version() -> str:
    text = (SRC / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("cannot find __version__")


def main() -> int:
    if LIB.exists():
        shutil.rmtree(LIB)
    LIB.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SRC,
        LIB,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    version = package_version()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["version"] = version
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copymode(PLUGIN / "bin" / "codex-continue", PLUGIN / "bin" / "codex-continue")
    print(f"built plugin bundle v{version} -> {LIB.parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
