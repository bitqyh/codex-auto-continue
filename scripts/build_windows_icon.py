#!/usr/bin/env python3
"""Build ui/windows-tray/assets/CodexContinue.ico from the app icon (stdlib only)."""

from __future__ import annotations

import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ui" / "menubar" / "assets" / "AppIcon.png"
TARGET = ROOT / "ui" / "windows-tray" / "assets" / "CodexContinue.ico"
SIZES = (32, 48, 256)


def resize(source: Path, size: int, target: Path) -> None:
    subprocess.run(
        ["sips", "-z", str(size), str(size), str(source), "--out", str(target)],
        check=True,
        capture_output=True,
    )


def build_ico(pngs: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries = b""
    payload = b""
    for size, data in pngs:
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    return header + entries + payload


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"missing source icon: {SOURCE}")
    with tempfile.TemporaryDirectory() as tmp:
        pngs: list[tuple[int, bytes]] = []
        for size in SIZES:
            out = Path(tmp) / f"icon-{size}.png"
            resize(SOURCE, size, out)
            pngs.append((size, out.read_bytes()))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(build_ico(pngs))
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
