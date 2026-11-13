"""把 web/node_modules 里的 KaTeX dist 同步到后端静态目录（升级 KaTeX 时手动跑一次）。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web" / "node_modules" / "katex"
DEST = ROOT / "backend" / "app" / "static" / "katex"
FILES = ("katex.min.css", "katex.min.js")
DIRS = ("fonts",)
EXTRA_FILES = (Path("contrib") / "auto-render.min.js",)


def main() -> None:
    version = json.loads((SOURCE / "package.json").read_text(encoding="utf-8"))["version"]
    DEST.mkdir(parents=True, exist_ok=True)
    dist = SOURCE / "dist"
    for name in FILES:
        shutil.copy2(dist / name, DEST / name)
    for name in DIRS:
        target = DEST / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(dist / name, target)
    for rel in EXTRA_FILES:
        (DEST / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dist / rel, DEST / rel)
    (DEST / "VERSION.txt").write_text(
        f"katex@{version} copied from web/node_modules/katex/dist (S5-3)\n", encoding="utf-8"
    )
    print(f"katex@{version} -> {DEST}")


if __name__ == "__main__":
    main()