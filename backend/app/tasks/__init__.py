"""异步任务包（S2-7/S2-8/S2-10/S3-1）：注册表、执行器、ARQ 队列与 Worker 入口。

这里显式导入内置任务模块：注册表靠 import 副作用填充，
worker/runner 只 import 本包时也必须能看到全部内置任务。
"""
from app.tasks import analyze_mistake as _analyze_mistake  # noqa: F401  注册 mistake.analyze
from app.tasks import demo as _demo  # noqa: F401  注册 demo.sleep
from app.tasks import generate_variants as _generate_variants  # noqa: F401  注册 mistake.variants
from app.tasks import index_note as _index_note  # noqa: F401  注册 index.note
from app.tasks import kp_align as _kp_align  # noqa: F401  注册 kp.align
from app.tasks import mistake_recognize as _mistake_recognize  # noqa: F401  注册 mistake.recognize
from app.tasks import parse_document as _parse_document  # noqa: F401  注册 parse.document
from app.tasks import question_extract as _question_extract  # noqa: F401  注册 question.extract

__all__ = [
    "_analyze_mistake",
    "_demo",
    "_generate_variants",
    "_index_note",
    "_kp_align",
    "_mistake_recognize",
    "_parse_document",
    "_question_extract",
]