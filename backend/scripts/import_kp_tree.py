"""S2-9 知识点树导入 CLI：append / overwrite，支持 --dry-run。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.db import get_session_factory  # noqa: E402
from app.services.kp_import import import_tree, load_tree_file  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入知识点树 JSON")
    parser.add_argument("--file", default="data/kp_math.json", help="种子 JSON 路径")
    parser.add_argument("--mode", choices=["append", "overwrite"], default="append")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不落库")
    args = parser.parse_args(argv)

    try:
        tree = load_tree_file(Path(args.file))
        session = get_session_factory()()
        try:
            result = import_tree(
                session, tree=tree, mode=args.mode, dry_run=args.dry_run
            )
        finally:
            session.close()
    except (FileNotFoundError, ValueError) as exc:
        print(f"数据错误: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 —— CLI 需要给出可读失败
        print(f"导入失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    prefix = "[dry-run] " if args.dry_run else ""
    stats = result.stats
    print(
        f"{prefix}导入完成 subject={tree.subject.code} mode={args.mode} "
        f"created={stats.created} updated={stats.updated} deleted={stats.deleted} "
        f"skipped={stats.skipped} unchanged={stats.unchanged}"
    )
    for code, reason in result.skipped:
        print(f"skip code={code} reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())