"""S6-1 export_paper_pdf：校验试卷归属后给出下载地址（不渲染二进制）。"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec
from app.services.paper_plan_service import get_paper

VARIANT_LABELS = {"questions": "题干卷", "answers": "答案卷"}


class ExportPaperPdfIn(ToolInput):
    paper_id: int = Field(ge=1)
    variant: Literal["questions", "answers"] = "questions"


class ExportPaperPdfOut(ToolOutput):
    paper_id: int
    title: str
    variant: str
    question_count: int
    total_score: int
    filename: str
    download_url: str


def export_paper_pdf(ctx: ToolContext, data: ExportPaperPdfIn) -> ExportPaperPdfOut:
    detail = get_paper(ctx.session, user_id=ctx.user.id, paper_id=data.paper_id)
    return ExportPaperPdfOut(
        paper_id=detail.id,
        title=detail.title,
        variant=data.variant,
        question_count=len(detail.items),
        total_score=detail.total_score,
        filename=f"试卷-{detail.id}-{VARIANT_LABELS[data.variant]}.pdf",
        download_url=(
            f"/api/v1/papers/{detail.id}/export.pdf?variant={data.variant}"
        ),
    )


SPEC = ToolSpec(
    name="export_paper_pdf",
    description=(
        "用途：为已保存试卷生成受权校验后的下载地址；供错题组卷任务的最后一步使用。"
        "参数 paper_id 是本人试卷 id，variant 选 questions（题干卷）或 answers（答案卷）。"
        "返回题目数、总分、文件名与 /api/v1/papers/{id}/export.pdf 下载地址；"
        "工具不渲染 PDF，真正下载仍走既有导出接口。"
    ),
    input_model=ExportPaperPdfIn,
    output_model=ExportPaperPdfOut,
    handler=export_paper_pdf,
)