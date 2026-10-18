"""S1-1 演示脚本：打印解析结果前 N 段（任务卡要求 6）。

用法（仓库根目录）：
    python scripts/parse_demo.py <文件> [--limit 50] [--force-pymupdf]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.ai.parse import parse_document  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="文档解析演示（S1-1）")
    parser.add_argument("file", help="PDF/DOCX 文件路径")
    parser.add_argument("--limit", type=int, default=50, help="打印前 N 段（默认 50）")
    parser.add_argument("--force-pymupdf", action="store_true", help="跳过 Docling 走快速路径")
    args = parser.parse_args()

    doc = parse_document(args.file, force_pymupdf=args.force_pymupdf)
    print(f"文件: {doc.source}")
    print(f"解析器: {doc.parser}    扫描版: {'是' if doc.is_scanned else '否'}")
    if doc.degraded_reason:
        print(f"降级/提示: {doc.degraded_reason}")
    print(f"块总数: {len(doc.blocks)}（打印前 {min(args.limit, len(doc.blocks))} 段）")
    print("-" * 72)
    for i, b in enumerate(doc.blocks[: args.limit], start=1):
        head = " > ".join(b.heading_path) if b.heading_path else "（无层级）"
        page = f"p.{b.page_no}" if b.page_no is not None else "p.无(docx)"
        text = b.text.replace("\n", " ")
        print(f"[{i}] {page}「{head}」({b.type.value})")
        print(f"    {text[:76]}{'…' if len(text) > 76 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
