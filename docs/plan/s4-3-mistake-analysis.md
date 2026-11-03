# S4-3 错因诊断服务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 错题录入后异步调用 LLM 产出「知识点 / 主因+次因 / 第一处错误步骤 / 正确解法 / 复习建议」并落 `mistake_analyses`，前端详情页展示并支持重跑。

**Architecture:** 新增 `ai/analyze/`（结构化诊断适配器）与 `services/mistake_analysis_service.py`（触发 + 执行 + upsert），任务 `mistake.analyze` 由既有 runner 执行且 handler 不 commit；题库录入与拍照识别各自 best-effort 入队；`POST /mistakes/{id}/analyze` 提供手动重跑，前端轮询 `GET /tasks/{id}`。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic / Pydantic v2 / PG16 / ARQ；Vue 3 + TS + Element Plus + md-editor-v3。

**Spec:** `docs/spec/s4-3-mistake-analysis.md`（开工前必读；本文的实现细节与 spec 冲突时以 spec 为准，仍冲突则停下报告）

## Global Constraints

- 所有业务错误抛 `AppError` 子类：`NotFoundError`(404/40400)、`InvalidParamError`(422/42200)、`MistakeAnalysisError`(诊断专用，非 HTTP)；路由不拼错误 JSON。
- 所有查询显式带 `user_id`；他人数据与不存在统一 **404/40400**。
- service 一个用例一个事务（`_commit`）；任务 handler **不得 commit**，由 `tasks/runner.py` 统一提交/回滚。
- LLM 调用只在 `ai/` 层；`scene="mistake"`（必须在 `llm_call_logs` CHECK 白名单内，S4-2 C1 已验证）。
- Prompt 只放 `app/ai/prompts/` 文件，代码里不出现超过 3 行的 prompt 字符串。
- 枚举一律 TEXT+CHECK，值集常量在 `app/models/enums.py`（`CauseType` 已有，本卡不新增枚举）。
- 新增依赖：**无**。不许动 `requirements.txt` / `package.json`。
- 提交信息：`feat(s4-3): …` / `test(s4-3): …` / `docs(s4-3): …` / `fix(s4-3): …`。
- 测试全绿是提交前提；禁止跳过用例、禁止编造数字（§6）。
- 命令一律在 `backend\` 下用 `..\.venv\Scripts\python.exe -m …`；前端在 `web\` 下用 `npm run …`。

### 一页速查：既有约定

- 模型基类：`from app.core.db import Base`；主键 `BigInteger, Identity(always=True)`。
- 事务：`services/mistake_service.py::_commit` 就是 `session.commit()` 的薄封装（失败 `rollback` 后抛）。
- 任务注册：`app/tasks/registry.py::register(name)`；名字常量定义在 service，task 反向 import（S3-1 先例）。
- 任务提交：`app/services/task_service.py::create_task(session, *, owner: User, name: str, payload: dict, queue: TaskQueue) -> AsyncTask`（内部提交）。
- 检索：`app/services/retrieval_service.py::search_chunks(session, *, user_id, query, top_k=None, rerank=None, retrieval=None, scope=None, debug=False) -> RetrievalSearchResponse`；`hits: list[RetrievalHit]`（字段 `note_title`、`snippet`、`content`）。
- JSON 解析：`from app.ai.json_utils import loads_json_object`。
- 分页三件套：`page_params` / `sort_params` / `paginate_query` / `apply_sort`（本卡只有 1 个 detail 接口扩展，不需要分页）。
- 测试 FakeSession 样板：`backend/tests/test_mistake_service.py:1-76`（`objects` / `scalar_results` / `rows_results` / `added` / `commits`）。

---

### Task 1: 契约先行 + 迁移 0011 + 模型两列

**Files:**
- Modify: `docs/SCHEMA.md` §5.4（`mistake_analyses` 表加 `secondary_causes`、`confidence`）
- Modify: `docs/API.md` §6（先写 `POST /api/v1/mistakes/{mistake_id}/analyze` 与 `analysis` 新字段）
- Modify: `backend/app/models/mistake_analysis.py`（两列 + 两个 CHECK）
- Create: `backend/alembic/versions/0011_s4_3_mistake_analysis.py`
- Test: `backend/tests/test_mistake_models.py`（追加）

**Interfaces:**
- Produces: `MistakeAnalysis.secondary_causes: list[str] | None`、`MistakeAnalysis.confidence: Decimal | None`；迁移 `revision="0011_s4_3"`, `down_revision="0010_s4_2"`。
- Produces: `ck_mistake_analyses_secondary_causes`、`ck_mistake_analyses_confidence`。

- [x] **Step 1: 先改契约文档（§9.1「契约先行」）**

`docs/SCHEMA.md` §5.4 的两列表格追加到既有列清单后：

```markdown
| secondary_causes | text[] | 是 | — | 次因，至多 2 个，元素属于 `CauseType` 值集 |
| confidence | numeric(3,2) | 是 | — | LLM 自评置信度 0.00–1.00 |
```

并在该节约束清单里追加：

```markdown
- `ck_mistake_analyses_secondary_causes`：`secondary_causes IS NULL OR secondary_causes <@ ARRAY['概念不清','计算失误','审题偏差','方法不当','知识遗忘','时间不足','unknown']::text[]`
- `ck_mistake_analyses_confidence`：`confidence IS NULL OR (confidence >= 0 AND confidence <= 1)`
```

`docs/API.md` §6 在 `POST /api/v1/mistakes/{mistake_id}/review` 之后插入 analyze 端点小节（内容按 spec §8.1：202、query `force` 默认 true、`skipped` 语义、错误码），并把 `GET /mistakes/{id}` 的 `analysis` 示例补上 `secondary_causes` / `confidence` / `model` / `prompt_version`（spec §8.2）。

- [x] **Step 2: 写失败测试**

`backend/tests/test_mistake_models.py` 追加：

```python
def test_mistake_analysis_columns_declared():
    columns = {c.name for c in MistakeAnalysis.__table__.columns}
    assert {"secondary_causes", "confidence"} <= columns
    checks = {c.name for c in MistakeAnalysis.__table__.constraints if isinstance(c, CheckConstraint)}
    assert "ck_mistake_analyses_secondary_causes" in checks
    assert "ck_mistake_analyses_confidence" in checks
    assert MistakeAnalysis.__table__.c.secondary_causes.type.__class__.__name__ == "ARRAY"
    assert isinstance(MistakeAnalysis.__table__.c.confidence.type, Numeric)
```

- [x] **Step 3: 跑测试确认失败**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_models.py -q -k secondary_causes`
Expected: FAIL（`KeyError`/`AssertionError`，两列不存在）

- [x] **Step 4: 改模型**

`backend/app/models/mistake_analysis.py`：

```python
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

_CAUSE_ARRAY = "ARRAY['概念不清','计算失误','审题偏差','方法不当','知识遗忘','时间不足','unknown']::text[]"

__table_args__ = (
    UniqueConstraint("mistake_id", name="uq_mistake_analyses_mistake_id"),
    CheckConstraint(in_check("cause_type", CAUSE_TYPES), name="ck_mistake_analyses_cause_type"),
    CheckConstraint(
        f"secondary_causes IS NULL OR secondary_causes <@ {_CAUSE_ARRAY}",
        name="ck_mistake_analyses_secondary_causes",
    ),
    CheckConstraint(
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
        name="ck_mistake_analyses_confidence",
    ),
    Index("ix_mistake_analyses_kp_ids", "kp_ids", postgresql_using="gin"),
)
```

列定义追加在 `cause_type` 之后：

```python
    secondary_causes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
```

- [x] **Step 5: 写迁移**

`backend/alembic/versions/0011_s4_3_mistake_analysis.py`：

```python
"""S4-3 错题诊断增量列

Revision ID: 0011_s4_3
Revises: 0010_s4_2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_s4_3"
down_revision = "0010_s4_2"
branch_labels = None
depends_on = None

_CAUSES = "ARRAY['概念不清','计算失误','审题偏差','方法不当','知识遗忘','时间不足','unknown']::text[]"


def upgrade() -> None:
    op.add_column("mistake_analyses", sa.Column("secondary_causes", postgresql.ARRAY(sa.Text()), nullable=True))
    op.add_column("mistake_analyses", sa.Column("confidence", sa.Numeric(3, 2), nullable=True))
    op.create_check_constraint(
        "ck_mistake_analyses_secondary_causes",
        "mistake_analyses",
        f"secondary_causes IS NULL OR secondary_causes <@ {_CAUSES}",
    )
    op.create_check_constraint(
        "ck_mistake_analyses_confidence",
        "mistake_analyses",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_mistake_analyses_confidence", "mistake_analyses", type_="check")
    op.drop_constraint("ck_mistake_analyses_secondary_causes", "mistake_analyses", type_="check")
    op.drop_column("mistake_analyses", "confidence")
    op.drop_column("mistake_analyses", "secondary_causes")
```

- [x] **Step 6: 跑测试 + 迁移 + 真库核对**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_mistake_models.py -q
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic heads
..\.venv\Scripts\python.exe -m alembic check
```

Expected: 测试全绿；`heads` 只有 `0011_s4_3 (head)`；`alembic check` 输出 `No new upgrade operations detected.`

真库核对（贴输出）：

```powershell
..\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from sqlalchemy import text; from app.core.db import new_session; s=new_session(); print(s.execute(text(\"select column_name, data_type, numeric_precision, numeric_scale, udt_name from information_schema.columns where table_name='mistake_analyses' and column_name in ('secondary_causes','confidence')\")).all()); s.close()"
```

Expected: 两行；`secondary_causes` 的 `udt_name=_text`，`confidence` 的 `numeric_precision=3`、`numeric_scale=2`。

- [x] **Step 7: 回滚一次再升级（验证可逆）**

```powershell
..\.venv\Scripts\python.exe -m alembic downgrade -1
..\.venv\Scripts\python.exe -m alembic upgrade head
```

Expected: 两次都成功，最终 `0011_s4_3 (head)`。

- [x] **Step 8: Commit**

```bash
git add docs/SCHEMA.md docs/API.md backend/app/models/mistake_analysis.py backend/alembic/versions/0011_s4_3_mistake_analysis.py backend/tests/test_mistake_models.py
git commit -m "feat(s4-3): 迁移 0011 增加次因与置信度列，先补 SCHEMA/API 契约"
```

---

### Task 2: AI 层 `ai/analyze/` + Prompt

**Files:**
- Create: `backend/app/ai/prompts/mistake_analyze_v1.md`
- Create: `backend/app/ai/analyze/__init__.py`、`backend/app/ai/analyze/mistake_analyzer.py`
- Test: `backend/tests/test_mistake_analyzer.py`

**Interfaces:**
- Consumes: `from app.ai.json_utils import loads_json_object`；`from app.ai.llm import LLMClient, LLMMessage, get_llm_client`。
- Produces:
  - `DiagnosisContext`（frozen dataclass）：`stem_md: str`、`options: list[tuple[str, str]]`、`correct_answer_md: str | None`、`my_answer_md: str | None`、`kp_names: list[str]`、`prerequisite_names: list[str]`、`notes: list[tuple[str, str]]`（标题, 片段）
  - `MistakeAnalysisResult(BaseModel)`：`cause_type: CauseType`、`secondary_causes: list[CauseType]`、`error_step: str | None`、`explanation_md: str`、`review_advice_md: str`、`confidence: float`
  - `MistakeAnalysisError(Exception)`
  - `analyze_mistake(context: DiagnosisContext, *, llm_client: LLMClient | None = None, max_retries: int = 2) -> MistakeAnalysisResult`

- [x] **Step 1: 写 Prompt 文件**

`backend/app/ai/prompts/mistake_analyze_v1.md`（Jinja2，使用 `StrictUndefined`，变量必须全部出现）：

```markdown
你是一名高中数学老师，正在给一名学生讲他做错的题。只输出 JSON，不要任何解释文字。

## 题目
{{ stem_md }}
{% if options %}
## 选项
{% for key, text in options %}{{ key }}. {{ text }}
{% endfor %}
{% endif %}
## 标准答案
{{ correct_answer_md or "（题库未提供，请自己解出正确结果）" }}

## 学生作答
{{ my_answer_md or "（学生没有提供作答）" }}

## 本题涉及的知识点
{{ kp_names | join("、") if kp_names else "（题库未挂知识点）" }}

## 前置知识（供复习建议参考）
{{ prerequisite_names | join("、") if prerequisite_names else "（无）" }}

## 学生自己的笔记片段（可能为空，仅供参考，禁止编造未给出内容）
{% if notes %}{% for title, snippet in notes %}-《{{ title }}》{{ snippet }}
{% endfor %}{% else %}（没有检索到相关笔记）
{% endif %}
## 任务
1. 判定错因，主因只能从 [概念不清, 计算失误, 审题偏差, 方法不当, 知识遗忘, 时间不足] 中选 1 个；
   再给至多 2 个次因（可为空），次因不能与主因相同。
2. 指出学生**第一处**出错的位置：写清"你写的是……，第 k 步应为……"，并**引用学生作答原文**；
   如果学生作答里找不到明确错误，error_step 返回 null，不要硬凑。
3. explanation_md：分步骤给出正确解法，公式用 LaTeX 的 $...$，先讲本题再点明易错处（≥ 20 字）。
4. review_advice_md：给 2–3 条可执行的复习建议（≥ 10 字），优先结合上面的知识点与笔记片段；
   没有笔记片段时只讲知识点，不要虚构笔记内容。
5. confidence：0–1，表示你对错因判断的把握；不确定就写低一点，并在建议里说明哪里需要人工确认。
{% if not my_answer_md %}
6. 学生没有提供作答：cause_type 必须是 "unknown"，secondary_causes 为 []，error_step 为 null，
   只讲题、不猜错因。
{% endif %}

## 输出格式（严格 JSON）
{"cause_type": "...", "secondary_causes": ["..."], "error_step": "...",
 "explanation_md": "...", "review_advice_md": "...", "confidence": 0.0}
```

- [x] **Step 2: 写失败测试**

`backend/tests/test_mistake_analyzer.py`：

```python
from decimal import Decimal

import pytest

from app.ai.analyze import (
    DiagnosisContext,
    MistakeAnalysisError,
    MistakeAnalysisResult,
    analyze_mistake,
)
from app.ai.json_utils import loads_json_object


class FakeClient:
    def __init__(self, payloads: list[str]):
        self.payloads = payloads
        self.calls: list[dict] = []

    def chat(self, messages, *, temperature=0.0, max_tokens=None, scene=""):
        self.calls.append({"messages": messages, "scene": scene, "temperature": temperature})
        text = self.payloads.pop(0)

        class _Resp:
            pass

        resp = _Resp()
        resp.text = text
        return resp


def _ctx(**overrides) -> DiagnosisContext:
    base = dict(
        stem_md="已知函数 $f(x)=x^2-4x+3$，求对称轴",
        options=[],
        correct_answer_md="$x=2$",
        my_answer_md="对称轴 x=1",
        kp_names=["一元二次函数"],
        prerequisite_names=["函数"],
        notes=[],
    )
    base.update(overrides)
    return DiagnosisContext(**base)


GOOD = (
    '{"cause_type":"概念不清","secondary_causes":["计算失误"],'
    '"error_step":"你写的是「对称轴 x=1」，应为 x=2",'
    '"explanation_md":"配方得 $f(x)=(x-2)^2-1$，对称轴为 $x=2$。易错点是把顶点横坐标算错。",'
    '"review_advice_md":"复习配方法；对照笔记里的顶点公式。","confidence":0.82}'
)


def test_analyze_mistake_parses_valid_json():
    client = FakeClient([GOOD])
    result = analyze_mistake(_ctx(), llm_client=client)
    assert isinstance(result, MistakeAnalysisResult)
    assert result.cause_type.value == "概念不清"
    assert [c.value for c in result.secondary_causes] == ["计算失误"]
    assert "x=1" in (result.error_step or "")
    assert client.calls[0]["scene"] == "mistake"
    assert len(client.calls) == 1


def test_analyze_mistake_retries_then_raises():
    client = FakeClient(["不是 JSON", "还是不是"])
    with pytest.raises(MistakeAnalysisError):
        analyze_mistake(_ctx(), llm_client=client, max_retries=1)
    assert len(client.calls) == 2


def test_missing_answer_forces_unknown_even_if_model_guesses():
    bad = GOOD  # 模型仍返回「概念不清」
    result = analyze_mistake(_ctx(my_answer_md=None), llm_client=FakeClient([bad]))
    assert result.cause_type.value == "unknown"
    assert result.secondary_causes == []
    assert result.error_step is None


def test_secondary_causes_dedup_and_drop_primary():
    payload = (
        '{"cause_type":"概念不清","secondary_causes":["概念不清","计算失误","计算失误","时间不足"],'
        '"error_step":null,"explanation_md":"配方得 $f(x)=(x-2)^2-1$，对称轴 $x=2$。",'
        '"review_advice_md":"复习配方法。","confidence":0.5}'
    )
    result = analyze_mistake(_ctx(), llm_client=FakeClient([payload]))
    assert [c.value for c in result.secondary_causes] == ["计算失误", "时间不足"]


def test_error_step_without_student_text_is_dropped():
    payload = (
        '{"cause_type":"计算失误","secondary_causes":[],'
        '"error_step":"计算粗心","explanation_md":"配方得 $f(x)=(x-2)^2-1$，对称轴 $x=2$。",'
        '"review_advice_md":"复习配方法。","confidence":0.4}'
    )
    result = analyze_mistake(_ctx(), llm_client=FakeClient([payload]))
    assert result.error_step is None


def test_confidence_out_of_range_is_validation_error():
    payload = GOOD.replace('"confidence":0.82', '"confidence":1.5')
    with pytest.raises(MistakeAnalysisError):
        analyze_mistake(_ctx(), llm_client=FakeClient([payload, payload]), max_retries=1)


def test_unknown_primary_forces_empty_secondary():
    payload = (
        '{"cause_type":"unknown","secondary_causes":["计算失误"],'
        '"error_step":null,"explanation_md":"配方得 $f(x)=(x-2)^2-1$，对称轴 $x=2$。",'
        '"review_advice_md":"复习配方法。","confidence":0.3}'
    )
    result = analyze_mistake(_ctx(), llm_client=FakeClient([payload]))
    assert result.secondary_causes == []


def test_loads_json_object_strips_code_fence():
    # 复用既有工具的行为，防止模型包 ```json
    assert loads_json_object('```json\n{"a":1}\n```') == {"a": 1}
```

- [x] **Step 3: 跑测试确认失败**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_analyzer.py -q`
Expected: FAIL（`ModuleNotFoundError: app.ai.analyze`）

- [x] **Step 4: 写适配器**

`backend/app/ai/analyze/mistake_analyzer.py`：

```python
"""错因诊断适配器（S4-3）：严格 JSON + Pydantic 校验 + 最多 2 次重试。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client
from app.models.enums import CauseType

logger = logging.getLogger(__name__)

SCENE = "mistake"  # 必须在 llm_call_logs 的 CHECK 白名单内（S4-2 C1 的教训）

PROMPT_VERSION = "mistake_analyze_v1"
PROMPT_FILE = "mistake_analyze_v1.md"
MAX_RETRIES = 2
STEM_LIMIT = 2000
ANSWER_LIMIT = 800
STUDENT_LIMIT = 1500
NOTE_LIMIT = 200

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)

ALLOWED_CAUSES = {c.value for c in CauseType}


class MistakeAnalysisError(Exception):
    """诊断失败：JSON 非法、字段非法、重试耗尽。"""


@dataclass(frozen=True)
class DiagnosisContext:
    stem_md: str
    options: list[tuple[str, str]] = field(default_factory=list)
    correct_answer_md: str | None = None
    my_answer_md: str | None = None
    kp_names: list[str] = field(default_factory=list)
    prerequisite_names: list[str] = field(default_factory=list)
    notes: list[tuple[str, str]] = field(default_factory=list)


class MistakeAnalysisResult(BaseModel):
    cause_type: CauseType
    secondary_causes: list[CauseType] = Field(default_factory=list)
    error_step: str | None = None
    explanation_md: str = Field(min_length=20)
    review_advice_md: str = Field(min_length=10)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("secondary_causes", mode="before")
    @classmethod
    def _coerce_causes(cls, value: Any) -> Any:
        return value or []

    @model_validator(mode="after")
    def _normalize(self) -> "MistakeAnalysisResult":
        seen: list[CauseType] = []
        for cause in self.secondary_causes:
            if cause is self.cause_type or cause.value == "unknown":
                continue
            if cause not in seen:
                seen.append(cause)
        self.secondary_causes = seen[:2]
        if self.cause_type.value == "unknown":
            self.secondary_causes = []
        if self.error_step is not None:
            self.error_step = self.error_step.strip() or None
        self.explanation_md = self.explanation_md.strip()
        self.review_advice_md = self.review_advice_md.strip()
        return self
```

**SCENE 用字面量**（不要 `llm_call_logs` 之外的枚举技巧）：

```python
SCENE = "mistake"
```

渲染与调用：

```python
def render_prompt(context: DiagnosisContext) -> str:
    try:
        template = _ENV.get_template(PROMPT_FILE)
        return template.render(
            stem_md=context.stem_md[:STEM_LIMIT],
            options=context.options,
            correct_answer_md=(context.correct_answer_md or "")[:ANSWER_LIMIT] or None,
            my_answer_md=(context.my_answer_md or "")[:STUDENT_LIMIT] or None,
            kp_names=context.kp_names,
            prerequisite_names=context.prerequisite_names,
            notes=[(title, snippet[:NOTE_LIMIT]) for title, snippet in context.notes],
        )
    except Exception as exc:  # 模板变量缺失 / 文件缺失
        raise MistakeAnalysisError(f"prompt 渲染失败：{exc}") from exc


def analyze_mistake(
    context: DiagnosisContext,
    *,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> MistakeAnalysisResult:
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_prompt(context))]

    last_error: Exception | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        response = client.chat(messages, temperature=0.2, max_tokens=2000, scene=SCENE)
        try:
            payload = loads_json_object(response.text)
            result = MistakeAnalysisResult.model_validate(payload)
            return _enforce_rules(result, context)
        except (ValidationError, ValueError) as exc:
            last_error = exc
    raise MistakeAnalysisError(f"诊断失败（已尝试 {attempts} 次）：{last_error}")


def _enforce_rules(result: MistakeAnalysisResult, context: DiagnosisContext) -> MistakeAnalysisResult:
    """把 spec D-4 / D-13 的硬规则放在代码层，不依赖模型自觉。"""
    if not context.my_answer_md:
        if result.cause_type.value != "unknown" or result.error_step is not None:
            logger.info("mistake_analyze_unknown_answer", extra={"forced": True})
        result.cause_type = CauseType.UNKNOWN
        result.secondary_causes = []
        result.error_step = None
        return result
    if result.error_step and not _quotes_student(result.error_step, context.my_answer_md):
        result.error_step = None
    return result


def _quotes_student(error_step: str, my_answer: str) -> bool:
    """error_step 必须包含学生作答里的一个片段（≥2 字），否则视为泛泛而谈。"""
    text = my_answer.strip()
    for size in range(min(12, len(text)), 1, -1):
        for start in range(0, len(text) - size + 1):
            if text[start : start + size] in error_step:
                return True
    return False
```

`backend/app/ai/analyze/__init__.py`：

```python
"""S4-3 诊断门面：业务层只 import 这里。"""
from app.ai.analyze.mistake_analyzer import (
    PROMPT_VERSION,
    DiagnosisContext,
    MistakeAnalysisError,
    MistakeAnalysisResult,
    analyze_mistake,
    render_prompt,
)

__all__ = [
    "PROMPT_VERSION",
    "DiagnosisContext",
    "MistakeAnalysisError",
    "MistakeAnalysisResult",
    "analyze_mistake",
    "render_prompt",
]
```

- [x] **Step 5: 跑测试**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_analyzer.py -q`
Expected: 8 passed

- [x] **Step 6: 全量回归 + Commit**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest -q
```

Expected: ≥ 964 passed（基线 956 + 新增 8）

```bash
git add backend/app/ai/analyze backend/app/ai/prompts/mistake_analyze_v1.md backend/tests/test_mistake_analyzer.py
git commit -m "feat(s4-3): 错因诊断适配器与 Prompt（严格 JSON、unknown 代码强制）"
```
---

### Task 3: 服务层 `mistake_analysis_service.py`

**Files:**
- Create: `backend/app/services/mistake_analysis_service.py`
- Test: `backend/tests/test_mistake_analysis_service.py`

**Interfaces:**
- Consumes: `DiagnosisContext` / `MistakeAnalysisResult` / `MistakeAnalysisError` / `analyze_mistake` / `PROMPT_VERSION`（Task 2）；`retrieval_service.search_chunks`；`task_service.create_task`；`get_settings().llm_model`。
- Produces:
  - `TASK_ANALYZE_MISTAKE = "mistake.analyze"`
  - `has_analysis(session, mistake_id: int) -> bool`
  - `enqueue_analysis(session, *, owner: User, mistake_id: int, queue: TaskQueue, force: bool = False, skip_if_analyzed: bool = True) -> AsyncTask | None`
  - `build_context(session, *, user_id: int, mistake: Mistake, question: Question) -> DiagnosisContext`
  - `analyze(session, *, user_id: int, mistake_id: int) -> tuple[MistakeAnalysis, dict[str, Any]]`
  - `safe_enqueue(session, *, owner: User, mistake_id: int, queue: TaskQueue) -> bool`（best-effort 包装，失败记 WARNING 返回 False）

- [x] **Step 1: 写失败测试**

`backend/tests/test_mistake_analysis_service.py`（FakeSession 复用 `tests/test_mistake_service.py:1-76` 的写法，直接复制该类到本文件顶部即可，不要 import 那个模块的私有类）：

```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import NotFoundError
from app.models.enums import CauseType
from app.models.knowledge_point import KnowledgePoint
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.services import mistake_analysis_service as svc


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None, rows_results=None):
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.rows_results = list(rows_results or [])
        self.added, self.deleted, self.flushed = [], [], 0
        self.commits = 0
        self.commits = 0

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return []

    def execute(self, statement):
        return _Rows(self.rows_results.pop(0) if self.rows_results else [])

    def add(self, instance):
        if getattr(instance, "id", None) is None:
            instance.id = 901
        self.added.append(instance)

    def flush(self):
        self.flushed += 1

    def delete(self, instance):
        self.deleted.append(instance)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _question() -> Question:
    q = Question(subject_id=7, stem_md="已知函数 $f(x)=x^2-4x+3$，求对称轴", stem_hash="h1",
                 qtype="解答", difficulty=2, origin="upload", answer_md="$x=2$", verified=True)
    q.id = 65
    return q


def _mistake(**kw) -> Mistake:
    m = Mistake(user_id=1, question_id=65, status="待订正", correct_streak=0,
                created_at=datetime(2026, 11, 3, tzinfo=timezone.utc), my_answer_md="对称轴 x=1")
    m.id = 12
    for key, value in kw.items():
        setattr(m, key, value)
    return m


def _result(**kw):
    from app.ai.analyze import MistakeAnalysisResult

    base = dict(
        cause_type=CauseType.CONCEPT,
        secondary_causes=[CauseType.CALC],
        error_step="你写的是「对称轴 x=1」，应为 x=2",
        explanation_md="配方得 $f(x)=(x-2)^2-1$，对称轴 $x=2$。易错点：顶点横坐标。",
        review_advice_md="复习配方法，对照笔记里的顶点公式。",
        confidence=0.82,
    )
    base.update(kw)
    return MistakeAnalysisResult(**base)


def test_analyze_inserts_new_analysis(monkeypatch):
    mistake, question = _mistake(), _question()
    session = FakeSession(
        objects={(Mistake, 12): mistake, (Question, 65): question},
        scalar_results=[None],       # 已有诊断查询 → 无
        rows_results=[[(133, "一元二次函数", Decimal("0.750000"))]],  # kp 行
    )
    monkeypatch.setattr(svc, "build_context", lambda *a, **k: svc.DiagnosisContext(
        stem_md=question.stem_md, correct_answer_md="$x=2$", my_answer_md="对称轴 x=1",
        kp_names=["一元二次函数"],
    ))
    monkeypatch.setattr(svc, "analyze_mistake", lambda ctx, **k: _result())

    analysis, summary = svc.analyze(session, user_id=1, mistake_id=12)

    assert isinstance(analysis, MistakeAnalysis)
    assert analysis.cause_type == "概念不清"
    assert analysis.secondary_causes == ["计算失误"]
    assert analysis.kp_ids == [133]
    assert analysis.prompt_version == "mistake_analyze_v1"
    assert summary["confidence"] == pytest.approx(0.82)
    assert session.flushed >= 1 and session.commits == 0


def test_analyze_updates_existing_row_in_place(monkeypatch):
    mistake, question = _mistake(), _question()
    existing = MistakeAnalysis(mistake_id=12, cause_type="计算失误", model="m", prompt_version="v1",
                               created_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    existing.id = 7
    session = FakeSession(
        objects={(Mistake, 12): mistake, (Question, 65): question},
        scalar_results=[existing],
        rows_results=[[]],
    )
    monkeypatch.setattr(svc, "build_context", lambda *a, **k: svc.DiagnosisContext(stem_md="x", my_answer_md="对称轴 x=1"))
    monkeypatch.setattr(svc, "analyze_mistake", lambda ctx, **k: _result())

    analysis, _summary = svc.analyze(session, user_id=1, mistake_id=12)

    assert analysis is existing
    assert existing.cause_type == "概念不清"
    assert existing.created_at != datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert existing.created_at.tzinfo is not None
    assert session.added == []


def test_analyze_other_user_raises_404(monkeypatch):
    session = FakeSession(objects={(Mistake, 12): _mistake(user_id=2)})
    with pytest.raises(NotFoundError):
        svc.analyze(session, user_id=1, mistake_id=12)


def test_build_context_degrades_when_retrieval_fails(monkeypatch):
    mistake, question = _mistake(), _question()
    session = FakeSession(rows_results=[[(133, "一元二次函数", Decimal("0.75"))]])

    def boom(*_a, **_k):
        raise RuntimeError("embedding down")

    monkeypatch.setattr(svc.retrieval_service, "search_chunks", boom)
    ctx = svc.build_context(session, user_id=1, mistake=mistake, question=question)
    assert ctx.notes == []
    assert ctx.kp_names == ["一元二次函数"]


def test_build_context_orders_kp_by_weight(monkeypatch):
    mistake, question = _mistake(), _question()
    session = FakeSession(rows_results=[[(133, "A", Decimal("0.9")), (116, "B", Decimal("0.8"))]])
    monkeypatch.setattr(svc.retrieval_service, "search_chunks", lambda *a, **k: type("R", (), {"hits": []})())
    ctx = svc.build_context(session, user_id=1, mistake=mistake, question=question)
    assert ctx.kp_names == ["A", "B"]


def test_has_analysis_true_and_false():
    assert svc.has_analysis(FakeSession(scalar_results=[1]), 12) is True
    assert svc.has_analysis(FakeSession(scalar_results=[None]), 12) is False

- [x] **Step 2: 跑测试确认失败**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_analysis_service.py -q`
Expected: FAIL（`ModuleNotFoundError: app.services.mistake_analysis_service`）

- [x] **Step 3: 写服务**

`backend/app/services/mistake_analysis_service.py`：

```python
"""错因诊断的触发与执行（S4-3）。

约定：
- 一个用例一个事务；`analyze` 不 commit（由任务 runner 提交）。
- `enqueue_analysis` 内部走 `task_service.create_task`（它自己提交任务行）。
- 诊断失败保留旧诊断，不写半截数据。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analyze import (
    PROMPT_VERSION,
    DiagnosisContext,
    analyze_mistake,
)
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.knowledge_point import KnowledgePoint
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.user import User
from app.services import retrieval_service, task_service
from app.tasks.queue import TaskQueue

logger = logging.getLogger(__name__)

TASK_ANALYZE_MISTAKE = "mistake.analyze"
MAX_KP = 3
MAX_PREREQ = 5
NOTE_TOP_K = 3
NOTE_QUERY_LIMIT = 200


def has_analysis(session: Session, mistake_id: int) -> bool:
    stmt = select(MistakeAnalysis.id).where(MistakeAnalysis.mistake_id == mistake_id).limit(1)
    return session.scalar(stmt) is not None


def enqueue_analysis(
    session: Session,
    *,
    owner: User,
    mistake_id: int,
    queue: TaskQueue,
    force: bool = False,
    skip_if_analyzed: bool = True,
):
    """建诊断任务；`skip_if_analyzed=True` 且已有诊断时返回 None（自动触发用）。"""
    if skip_if_analyzed and has_analysis(session, mistake_id):
        return None
    return task_service.create_task(
        session,
        owner=owner,
        name=TASK_ANALYZE_MISTAKE,
        payload={"user_id": owner.id, "mistake_id": mistake_id, "force": force},
        queue=queue,
    )


def safe_enqueue(session: Session, *, owner: User, mistake_id: int, queue: TaskQueue) -> bool:
    """best-effort：入队失败只记 WARNING，不影响录入/识别主流程。"""
    try:
        enqueue_analysis(session, owner=owner, mistake_id=mistake_id, queue=queue)
    except Exception as exc:  # noqa: BLE001 - 入队失败不该阻断业务
        logger.warning("mistake_analyze_enqueue_failed mistake_id=%s error=%s", mistake_id, exc)
        return False
    return True


def _kp_rows(session: Session, question_id: int) -> list[tuple[int, str, Decimal | None]]:
    stmt = (
        select(KnowledgePoint.id, KnowledgePoint.name, QuestionKp.weight)
        .join(QuestionKp, QuestionKp.kp_id == KnowledgePoint.id)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc(), KnowledgePoint.id)
        .limit(MAX_KP)
    )
    return list(session.execute(stmt).all())


def _prerequisite_names(session: Session, kp_ids: list[int]) -> list[str]:
    """前置知识近似：取这批 KP 的父节点名称（图谱 S4-5 之前的最优近似）。"""
    if not kp_ids:
        return []
    parent_ids = (
        select(KnowledgePoint.parent_id)
        .where(KnowledgePoint.id.in_(kp_ids), KnowledgePoint.parent_id.is_not(None))
        .scalar_subquery()
    )
    stmt = (
        select(KnowledgePoint.name)
        .where(KnowledgePoint.id.in_(parent_ids))
        .order_by(KnowledgePoint.id)
        .limit(MAX_PREREQ)
    )
    return [name for name in session.scalars(stmt).all() if name]


def _note_snippets(session: Session, *, user_id: int, query: str) -> list[tuple[str, str]]:
    try:
        response = retrieval_service.search_chunks(
            session, user_id=user_id, query=query[:NOTE_QUERY_LIMIT], top_k=NOTE_TOP_K
        )
    except Exception as exc:  # noqa: BLE001 - 检索不可用只降级
        logger.warning("mistake_analyze_retrieval_failed error=%s", exc)
        return []
    return [((hit.note_title or "笔记"), hit.snippet) for hit in response.hits]


def build_context(
    session: Session, *, user_id: int, mistake: Mistake, question: Question
) -> DiagnosisContext:
    rows = _kp_rows(session, question.id)
    kp_ids = [row[0] for row in rows]
    kp_names = [row[1] for row in rows]
    return DiagnosisContext(
        stem_md=question.stem_md,
        options=[(item.get("key", ""), item.get("text", "")) for item in (question.options or [])],
        correct_answer_md=mistake.correct_answer_md or question.answer_md,
        my_answer_md=mistake.my_answer_md,
        kp_names=kp_names,
        prerequisite_names=_prerequisite_names(session, kp_ids),
        notes=_note_snippets(session, user_id=user_id, query=question.stem_md),
    )


def analyze(session: Session, *, user_id: int, mistake_id: int) -> tuple[MistakeAnalysis, dict[str, Any]]:
    mistake = session.get(Mistake, mistake_id)
    if mistake is None or mistake.user_id != user_id:
        raise NotFoundError("错题不存在")
    question = session.get(Question, mistake.question_id)
    if question is None:
        raise NotFoundError("题目不存在")

    context = build_context(session, user_id=user_id, mistake=mistake, question=question)
    result = analyze_mistake(context)

    analysis = session.scalar(
        select(MistakeAnalysis).where(MistakeAnalysis.mistake_id == mistake_id)
    )
    if analysis is None:
        analysis = MistakeAnalysis(
            mistake_id=mistake_id,
            cause_type=result.cause_type.value,
            model=get_settings().llm_model,
            prompt_version=PROMPT_VERSION,
        )
        session.add(analysis)
    analysis.cause_type = result.cause_type.value
    analysis.secondary_causes = [cause.value for cause in result.secondary_causes]
    analysis.error_step = result.error_step
    analysis.explanation_md = result.explanation_md
    analysis.review_advice_md = result.review_advice_md
    analysis.confidence = Decimal(str(round(result.confidence, 2)))
    analysis.kp_ids = [row[0] for row in _kp_rows(session, question.id)]
    analysis.model = get_settings().llm_model
    analysis.prompt_version = PROMPT_VERSION
    analysis.created_at = datetime.now(timezone.utc)
    session.flush()

    summary = {
        "mistake_id": mistake_id,
        "cause_type": analysis.cause_type,
        "secondary_causes": list(analysis.secondary_causes or []),
        "confidence": float(analysis.confidence) if analysis.confidence is not None else None,
        "retrieval_hits": len(context.notes),
    }
    return analysis, summary
```

**两个实现细节（易错）：**

1. `MistakeAnalysis.created_at` 是 `server_default=now()`；重跑要覆盖它，所以显式赋值 `datetime.now(timezone.utc)`（spec D-3）。不要用 `func.now()`，测试里断言不到。
2. `analyze` 里取错题用 `session.get(Mistake, mistake_id)` 再判 `mistake.user_id != user_id`，不要用 `select(Mistake).where(...)`——`session.get` 命中 identity map，测试的 FakeSession 只实现 `get`，`select` 版本会逼测试写更复杂的桩。越权判定：

```python
    mistake = session.get(Mistake, mistake_id)
    if mistake is None or mistake.user_id != user_id:
        raise NotFoundError("错题不存在")
```

- [x] **Step 4: 跑测试**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_analysis_service.py -q`
Expected: 6 passed（若 `_prerequisite_names` 的 `session.scalars` 在 FakeSession 里返回 `[]`，`build_context` 的前置为 `[]`，符合断言）

- [x] **Step 5: 全量回归 + Commit**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest -q
```

Expected: ≥ 970 passed

```bash
git add backend/app/services/mistake_analysis_service.py backend/tests/test_mistake_analysis_service.py
git commit -m "feat(s4-3): 诊断服务（上下文构造、检索降级、1:1 覆盖）"
```

---

### Task 4: 任务 `mistake.analyze` + 两个触发点

**Files:**
- Create: `backend/app/tasks/analyze_mistake.py`
- Modify: `backend/app/tasks/__init__.py`（若任务模块需要显式 import 才注册，按现有写法追加）
- Modify: `backend/app/tasks/mistake_recognize.py`（handler 末尾 best-effort 入队）
- Modify: `backend/app/services/mistake_service.py`（`create_from_question` 增加可选 `owner` / `queue` 并入队）
- Test: `backend/tests/test_mistake_analysis_task.py`、`backend/tests/test_mistake_service.py`（追加 1 条）

**Interfaces:**
- Consumes: `TASK_ANALYZE_MISTAKE` / `has_analysis` / `analyze`（Task 3）。
- Produces: 任务名 `"mistake.analyze"`；`result` 形如 `{"mistake_id":12,"cause_type":"概念不清","secondary_causes":["计算失误"],"confidence":0.82,"retrieval_hits":2}` 或 `{"mistake_id":12,"skipped":true}`。
- Produces: `create_from_question(session, *, user_id: int, payload, owner: User | None = None, queue: TaskQueue | None = None)`——`owner`/`queue` 都为 None 时不入队（既有调用零改动）。

- [x] **Step 1: 写失败测试**

`backend/tests/test_mistake_analysis_task.py`：

```python
import pytest

from app.models.enums import CauseType
from app.services import mistake_analysis_service as svc
from app.tasks import registry
from app.tasks.analyze_mistake import run_analyze_mistake


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.flushed = 0

    def commit(self):
        self.commits += 1

    def flush(self):
        self.flushed += 1


def test_task_registered():
    assert "mistake.analyze" in registry.HANDLERS


def test_handler_returns_summary_and_does_not_commit(monkeypatch):
    monkeypatch.setattr(svc, "has_analysis", lambda *a, **k: False)

    analysis = type("A", (), {"id": 3})()
    monkeypatch.setattr(
        svc,
        "analyze",
        lambda session, *, user_id, mistake_id: (
            analysis,
            {"mistake_id": mistake_id, "cause_type": "概念不清",
             "secondary_causes": ["计算失误"], "confidence": 0.82, "retrieval_hits": 2},
        ),
    )
    session = FakeSession()
    result = run_analyze_mistake(session, {"user_id": 1, "mistake_id": 12, "force": True})
    assert result["cause_type"] == "概念不清"
    assert result["retrieval_hits"] == 2
    assert session.commits == 0


def test_handler_skips_when_force_false_and_analysis_exists(monkeypatch):
    monkeypatch.setattr(svc, "has_analysis", lambda *a, **k: True)
    called = []
    monkeypatch.setattr(svc, "analyze", lambda *a, **k: called.append(1))
    result = run_analyze_mistake(FakeSession(), {"user_id": 1, "mistake_id": 12, "force": False})
    assert result == {"mistake_id": 12, "skipped": True}
    assert called == []


def test_handler_propagates_analysis_error(monkeypatch):
    from app.ai.analyze import MistakeAnalysisError

    def boom(*_a, **_k):
        raise MistakeAnalysisError("诊断失败（已尝试 3 次）：bad json")

    monkeypatch.setattr(svc, "has_analysis", lambda *a, **k: False)
    monkeypatch.setattr(svc, "analyze", boom)
    with pytest.raises(MistakeAnalysisError):
        run_analyze_mistake(FakeSession(), {"user_id": 1, "mistake_id": 12, "force": True})
```

`backend/tests/test_mistake_service.py` 追加（完全照抄该文件 `test_create_from_question_new_row_uses_question_answer` 的 FakeSession 构造，只多一个入队断言）：

```python
def test_create_from_question_enqueues_analysis_when_owner_given(monkeypatch):
    from app.services import mistake_service as ms

    calls: list[dict] = []
    monkeypatch.setattr(
        ms, "safe_enqueue", lambda session, **kwargs: calls.append(kwargs) or True
    )

    session = FakeSession(objects={(Question, 65): _question()}, scalar_results=[None])
    detail, created = ms.create_from_question(
        session,
        user_id=1,
        payload=MistakeCreateIn(question_id=65),
        owner=object(),          # 只关心「传了就走入队」
        queue=object(),
    )

    assert created is True
    assert len(calls) == 1
    assert calls[0]["mistake_id"] == detail.id


def test_create_from_question_without_owner_skips_enqueue(monkeypatch):
    from app.services import mistake_service as ms

    calls: list[dict] = []
    monkeypatch.setattr(ms, "safe_enqueue", lambda session, **kwargs: calls.append(kwargs))

    session = FakeSession(objects={(Question, 65): _question()}, scalar_results=[None])
    ms.create_from_question(session, user_id=1, payload=MistakeCreateIn(question_id=65))
    assert calls == []
```

> 传 `owner=object()` 就够：`safe_enqueue` 被 monkeypatch，不会真的用 `owner.id`。真实用户对象只在路由/任务里构造。

- [x] **Step 2: 跑测试确认失败**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_analysis_task.py -q`
Expected: FAIL（`ModuleNotFoundError: app.tasks.analyze_mistake`）

- [x] **Step 3: 写任务**

`backend/app/tasks/analyze_mistake.py`：

```python
"""S4-3 错因诊断任务：不 commit，由 runner 统一提交/回滚。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services import mistake_analysis_service
from app.services.mistake_analysis_service import TASK_ANALYZE_MISTAKE
from app.tasks.registry import register


@register(TASK_ANALYZE_MISTAKE)
def run_analyze_mistake(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = int(payload["user_id"])
    mistake_id = int(payload["mistake_id"])
    if not payload.get("force", True) and mistake_analysis_service.has_analysis(session, mistake_id):
        return {"mistake_id": mistake_id, "skipped": True}
    _analysis, summary = mistake_analysis_service.analyze(
        session, user_id=user_id, mistake_id=mistake_id
    )
    return summary
```

在 `backend/app/tasks/__init__.py` 里按现有 import 风格追加 `from app.tasks import analyze_mistake  # noqa: F401`（先读该文件确认写法，保持字母序）。

- [x] **Step 4: 拍照录入触发诊断**

`backend/app/tasks/mistake_recognize.py` 的 handler，在 `return result` 之前插入：

```python
    # 诊断是 best-effort：入队失败不影响识别结果（spec D-1）
    owner = session.get(User, user_id)  # 变量名按该 handler 现有局部名调整
    if owner is not None:
        from app.services import mistake_analysis_service
        from app.tasks.queue import get_task_queue

        result["analysis_enqueued"] = mistake_analysis_service.safe_enqueue(
            session, owner=owner, mistake_id=mistake_id, queue=get_task_queue()
        )
```

- handler 签名是 `(session, payload)`，**没有** queue 参数：`app/tasks/queue.py::get_task_queue()` 是无参 `@lru_cache` 工厂，任何进程内都能直接调（它就是路由 `Depends(get_task_queue)` 用的同一个函数），handler 里直接 `get_task_queue()` 即可。
- `safe_enqueue` 内部捕获一切异常并记 WARNING，所以这里不需要 try/except；`result["analysis_enqueued"]` 只是给前端/运维看的标记，任务仍算成功。
- 位置：必须放在 `result` 组装完之后、`return result` 之前——这段之后 handler 只剩 return，提前提交（`create_task` 会 commit session）不会留下半写状态。

- [x] **Step 5: 题库录入触发诊断**

`backend/app/services/mistake_service.py`：

1. 函数签名加两个关键字参数（其余不动）：

```python
def create_from_question(
    session: Session,
    *,
    user_id: int,
    payload: MistakeCreateIn,
    owner: User | None = None,
    queue: TaskQueue | None = None,
) -> tuple[MistakeDetailOut, bool]:
```

2. 在**既有** `_commit(session)` 之后、`return` 之前插入（该函数现在最后就是 `return detail, created`，只在它前面加这段，别的行不改）：

```python
    if owner is not None and queue is not None:
        from app.services import mistake_analysis_service

        mistake_analysis_service.safe_enqueue(
            session, owner=owner, mistake_id=detail.id, queue=queue
        )
    return detail, created
```

3. 文件顶部按需补 import：`from app.models.user import User`、`from app.tasks.queue import TaskQueue`、`from app.services import mistake_analysis_service`（若放顶部 import 会循环导入，就用函数内 import；`mistake_analysis_service` 已 import `task_service` 与 `retrieval_service`，不含 `mistake_service`，理论上顶部 import 也安全——**优先顶部**，只有在真的循环导入时才降级为函数内 import，并在提交信息里说明）。

4. 路由 `create_mistake`（`backend/app/api/v1/mistakes.py:103`）补依赖与参数：`queue: TaskQueue = Depends(get_task_queue)`，调用处传 `owner=current_user, queue=queue`。

路由 `create_mistake` 传入 `owner=current_user, queue=queue`（`queue: TaskQueue = Depends(get_task_queue)` 已在该路由的 photo 版本里出现过，照抄依赖）。

- [x] **Step 6: 跑测试**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_mistake_analysis_task.py tests/test_mistake_service.py -q
```

Expected: 新用例全绿，旧 `mistake_service` 用例零改动全绿

- [x] **Step 7: 全量回归 + Commit**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest -q
```

Expected: ≥ 974 passed

```bash
git add backend/app/tasks/analyze_mistake.py backend/app/tasks/mistake_recognize.py backend/app/tasks/__init__.py backend/app/services/mistake_service.py backend/app/services/mistake_analysis_service.py backend/tests/test_mistake_analysis_task.py backend/tests/test_mistake_service.py
git commit -m "feat(s4-3): mistake.analyze 任务与录入后自动入队"
```

---

### Task 5: 接口 `POST /mistakes/{id}/analyze` + DTO 扩展

**Files:**
- Modify: `backend/app/api/v1/mistakes.py`
- Modify: `backend/app/schemas/mistake.py`
- Test: `backend/tests/test_mistakes_api.py`（追加 4 条）

**Interfaces:**
- Consumes: `enqueue_analysis`（`skip_if_analyzed=False`）、`TaskOut`。
- Produces: `POST /api/v1/mistakes/{mistake_id}/analyze?force=true` → `202 Envelope[TaskOut]`；`MistakeAnalysisOut` 增 `secondary_causes` / `confidence` / `model` / `prompt_version`。

- [x] **Step 1: 写失败测试**

`backend/tests/test_mistakes_api.py` 追加：

```python
def test_analyze_mistake_returns_202_and_creates_task(client, auth_headers, seeded_mistake):
    resp = client.post(f"/api/v1/mistakes/{seeded_mistake}/analyze", headers=auth_headers)
    assert resp.status_code == 202
    body = resp.json()["data"]
    assert body["name"] == "mistake.analyze"
    assert body["status"] in {"pending", "running", "succeeded"}


def test_analyze_mistake_other_user_404(client, auth_headers, other_mistake):
    resp = client.post(f"/api/v1/mistakes/{other_mistake}/analyze", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_analyze_mistake_force_false_skips_when_analysis_exists(client, auth_headers, analyzed_mistake):
    resp = client.post(
        f"/api/v1/mistakes/{analyzed_mistake}/analyze?force=false", headers=auth_headers
    )
    assert resp.status_code == 202
    task_id = resp.json()["data"]["id"]
    detail = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers).json()["data"]
    assert detail["status"] == "succeeded"
    assert detail["result"]["skipped"] is True


def test_mistake_detail_exposes_analysis_extended_fields(client, auth_headers, analyzed_mistake):
    resp = client.get(f"/api/v1/mistakes/{analyzed_mistake}", headers=auth_headers)
    analysis = resp.json()["data"]["analysis"]
    assert set(analysis) >= {"cause_type", "secondary_causes", "confidence", "model", "prompt_version"}
```

> `seeded_mistake` / `other_mistake` / `analyzed_mistake` 三个 fixture 放到该文件顶部（照现有 fixture 风格：建 user + subject + question + mistake，`analyzed_mistake` 额外插一行 `mistake_analyses`）。若已有可复用的 fixture 就直接用，不要重复造。

- [x] **Step 2: 跑测试确认失败**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_mistakes_api.py -q -k analyze`
Expected: FAIL（404 / 405）

- [x] **Step 3: 扩 DTO**

`backend/app/schemas/mistake.py` 的 `MistakeAnalysisOut`：

```python
class MistakeAnalysisOut(BaseModel):
    cause_type: str
    secondary_causes: list[str] = Field(default_factory=list)
    error_step: str | None = None
    explanation_md: str | None = None
    review_advice_md: str | None = None
    kp_ids: list[int] | None = None
    confidence: float | None = None
    model: str
    prompt_version: str
    created_at: datetime
```

找到 `MistakeAnalysisOut` 的构造处（`mistake_service` 里 detail 拼装），补：

```python
    analysis=MistakeAnalysisOut(
        cause_type=row.cause_type,
        secondary_causes=list(row.secondary_causes or []),
        error_step=row.error_step,
        explanation_md=row.explanation_md,
        review_advice_md=row.review_advice_md,
        kp_ids=list(row.kp_ids or []) or None,
        confidence=float(row.confidence) if row.confidence is not None else None,
        model=row.model,
        prompt_version=row.prompt_version,
        created_at=row.created_at,
    ) if row else None,
```

- [x] **Step 4: 加路由**

`backend/app/api/v1/mistakes.py`（放在 `review` 之后、`delete` 之前）：

```python
@router.post(
    "/{mistake_id}/analyze",
    status_code=202,
    response_model=Envelope[TaskOut],
    summary="触发错因诊断",
)
def trigger_mistake_analysis(
    mistake_id: int,
    force: bool = Query(True),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    task = mistake_analysis_service.enqueue_analysis(
        session,
        owner=current_user,
        mistake_id=mistake_id,
        queue=queue,
        force=force,
        skip_if_analyzed=False,
    )
    return Envelope(data=TaskOut.model_validate(task))
```

注意 `enqueue_analysis` 之前必须先校验错题归属，否则 202 之后任务才 404。**在 service 里加**：

```python
def _ensure_owned(session: Session, *, user_id: int, mistake_id: int) -> None:
    row = session.scalar(
        select(Mistake.id).where(Mistake.id == mistake_id, Mistake.user_id == user_id)
    )
    if row is None:
        raise NotFoundError("错题不存在")
```

`enqueue_analysis` 的第一行就调用它：

```python
def enqueue_analysis(session, *, owner, mistake_id, queue, force=False, skip_if_analyzed=True):
    _ensure_owned(session, user_id=owner.id, mistake_id=mistake_id)
    if skip_if_analyzed and has_analysis(session, mistake_id):
        return None
    return task_service.create_task(...)
```

语义分工（别弄反）：

- **手动路由**：直接调 `enqueue_analysis(...)`，404 正常透出（错题不属于自己时学生看到 404，与 S4-2 口径一致）。
- **自动触发**：调 `safe_enqueue(...)`，它把（含 404 在内的）异常吞成 WARNING。自动路径不会传别人的 `mistake_id`，这条兜底只是防御。

- [x] **Step 5: 跑测试**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_mistakes_api.py -q`
Expected: 新旧用例全绿

- [x] **Step 6: 全量回归 + Commit**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest -q
```

Expected: ≥ 978 passed

```bash
git add backend/app/api/v1/mistakes.py backend/app/schemas/mistake.py backend/app/services/mistake_service.py backend/app/services/mistake_analysis_service.py backend/tests/test_mistakes_api.py
git commit -m "feat(s4-3): 手动诊断接口与诊断 DTO 字段扩展"
```

---

### Task 6: 前端类型 / API / 诊断区 / 重跑轮询

**Files:**
- Modify: `web/src/types/mistakes.ts`（`MistakeAnalysis` 加 4 个字段）
- Modify: `web/src/api/mistakes.ts`（`analyzeMistake`）
- Modify: `web/src/views/mistakes/MistakeDetailView.vue`（占位替换为诊断区 + 轮询）
- Test: `web/src/views/mistakes/__tests__/MistakeDetailView.spec.ts`（追加 8 条）

**Interfaces:**
- Consumes: `POST /api/v1/mistakes/{id}/analyze`（任务 `mistake.analyze`）、`GET /api/v1/tasks/{id}`（既有 `getTask`）。
- Produces: `analyzeMistake(id: number, force = true): Promise<TaskOut>`；组件内 `analysis` computed 增字段后直接渲染。

- [x] **Step 1: 加类型与 API（先写类型，`npm run build` 会替你抓拼写）**

`web/src/types/mistakes.ts`：

```ts
/** MistakeAnalysisOut */
export interface MistakeAnalysis {
  cause_type: MistakeCauseType
  secondary_causes: MistakeCauseType[]
  error_step: string | null
  explanation_md: string | null
  review_advice_md: string | null
  kp_ids: number[] | null
  confidence: number | null
  model: string
  prompt_version: string
  created_at: string
}
```

`web/src/api/mistakes.ts`（放在 `reviewMistake` 之后）：

```ts
/** 触发错因诊断（异步）；返回 202 的任务，用 getTask 轮询。 */
export async function analyzeMistake(id: number, force = true): Promise<TaskOut> {
  const resp = await http.post<ApiEnvelope<TaskOut>>(
    `${API_PREFIX}/mistakes/${id}/analyze`,
    null,
    { params: { force } },
  )
  return resp.data.data
}
```

- [x] **Step 2: 写失败测试**

`web/src/views/mistakes/__tests__/MistakeDetailView.spec.ts` 追加（沿用文件里已有的 `mountView` / `detailFixture` / fake timers 约定；`vi.mock('@/api/mistakes')` 里补 `analyzeMistake: vi.fn()`，`vi.mock('@/api/tasks')` 补 `getTask: vi.fn()`）：

```ts
it('无诊断时显示立即诊断按钮并在点击后轮询到成功', async () => {
  getMistake.mockResolvedValue(detailFixture({ analysis: null }))
  analyzeMistake.mockResolvedValue({ id: 77, name: 'mistake.analyze', status: 'pending' })
  getTask
    .mockResolvedValueOnce({ id: 77, status: 'running', result: null, error: null })
    .mockResolvedValueOnce({ id: 77, status: 'succeeded', result: { skipped: false }, error: null })
  getMistake.mockResolvedValueOnce(detailFixture({ analysis: analyzedFixture() }))

  const wrapper = await mountView()
  const btn = wrapper.findAll('button').find((b) => b.text().includes('立即诊断'))
  expect(btn).toBeTruthy()
  await btn!.trigger('click')
  await flushPromises()
  expect(analyzeMistake).toHaveBeenCalledWith(12, true)

  await vi.advanceTimersByTimeAsync(4000)
  await flushPromises()
  expect(getTask).toHaveBeenCalledWith(77)
  await vi.advanceTimersByTimeAsync(4000)
  await flushPromises()
  expect(wrapper.text()).toContain('概念不清')
})

it('渲染次因、置信度与第一处错误步骤', async () => {
  getMistake.mockResolvedValue(detailFixture({ analysis: analyzedFixture() }))
  const wrapper = await mountView()
  expect(wrapper.text()).toContain('概念不清')
  expect(wrapper.text()).toContain('计算失误')      // 次因 chip
  expect(wrapper.text()).toContain('82%')            // 置信度
  expect(wrapper.text()).toContain('你写的是')       // error_step 引用原文
})

it('unknown 错因隐藏第一处错误步骤并说明未提供作答', async () => {
  getMistake.mockResolvedValue(
    detailFixture({ analysis: analyzedFixture({ cause_type: 'unknown', error_step: null, secondary_causes: [] }) }),
  )
  const wrapper = await mountView()
  expect(wrapper.text()).toContain('未提供作答')
  expect(wrapper.find('.error-step').exists()).toBe(false)
})

it('置信度低于 0.5 显示把握较低提示', async () => {
  getMistake.mockResolvedValue(detailFixture({ analysis: analyzedFixture({ confidence: 0.3 }) }))
  const wrapper = await mountView()
  expect(wrapper.text()).toContain('把握较低')
})

it('诊断中禁用重新诊断按钮', async () => {
  getMistake.mockResolvedValue(detailFixture({ analysis: analyzedFixture() }))
  analyzeMistake.mockResolvedValue({ id: 78, name: 'mistake.analyze', status: 'pending' })
  getTask.mockResolvedValue({ id: 78, status: 'running', result: null, error: null })
  const wrapper = await mountView()
  const btn = wrapper.findAll('button').find((b) => b.text().includes('重新诊断'))
  await btn!.trigger('click')
  await flushPromises()
  expect(btn!.attributes('disabled')).toBeDefined()
})

it('轮询任务失败时展示错误且不刷新详情', async () => {
  getMistake.mockResolvedValue(detailFixture({ analysis: null }))
  analyzeMistake.mockResolvedValue({ id: 79, name: 'mistake.analyze', status: 'pending' })
  getTask.mockResolvedValue({ id: 79, status: 'failed', result: null, error: '诊断失败' })
  const wrapper = await mountView()
  await wrapper.findAll('button').find((b) => b.text().includes('立即诊断'))!.trigger('click')
  await flushPromises()
  await vi.advanceTimersByTimeAsync(4000)
  await flushPromises()
  expect(wrapper.text()).toContain('诊断失败')
})

it('卸载后迟到的轮询不刷新详情', async () => {
  const pending = deferred<unknown>()
  getMistake.mockResolvedValue(detailFixture({ analysis: null }))
  analyzeMistake.mockResolvedValue({ id: 80, name: 'mistake.analyze', status: 'pending' })
  getTask.mockReturnValue(pending.promise)
  const wrapper = await mountView()
  await wrapper.findAll('button').find((b) => b.text().includes('立即诊断'))!.trigger('click')
  await flushPromises()
  await vi.advanceTimersByTimeAsync(4000)
  wrapper.unmount()
  pending.resolve({ id: 80, status: 'succeeded', result: {}, error: null })
  await flushPromises()
  expect(getMistake).toHaveBeenCalledTimes(1)
})

it('重新诊断不清空未保存的作答草稿', async () => {
  getMistake.mockResolvedValue(detailFixture({ analysis: analyzedFixture() }))
  analyzeMistake.mockResolvedValue({ id: 81, name: 'mistake.analyze', status: 'pending' })
  getTask.mockResolvedValue({ id: 81, status: 'running', result: null, error: null })
  const wrapper = await mountView()
  await wrapper.find('textarea').setValue('我改了一半的作答')
  await wrapper.findAll('button').find((b) => b.text().includes('重新诊断'))!.trigger('click')
  await flushPromises()
  expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('我改了一半的作答')
})
```

- [x] **Step 3: 跑测试确认失败**

```powershell
cd web
$env:NODE_OPTIONS="--require E:\BiShe-AIStudy\.sdd\tools\dsh-exec-patch.cjs"
npm run test:run -- --pool=threads src/views/mistakes/__tests__/MistakeDetailView.spec.ts
```

Expected: FAIL（找不到「立即诊断」按钮 / `analyzeMistake is not a function`）

- [x] **Step 4: 改详情页**

`MistakeDetailView.vue` 的 `<script setup>` 追加：

```ts
import { analyzeMistake } from '@/api/mistakes'
import { getTask } from '@/api/tasks'

const CAUSE_ORDER: MistakeCauseType[] = [
  '概念不清', '计算失误', '审题偏差', '方法不当', '知识遗忘', '时间不足',
]
const analyzing = ref(false)
const analyzeError = ref('')
const analyzeTaskId = ref<number | null>(null)
let analyzeTimer: ReturnType<typeof setInterval> | null = null
let analyzeElapsed = 0
const analyzeSeconds = ref(0)
const analyzePollCount = ref(0)

const lowConfidence = computed(
  () => analysis.value?.confidence !== null && analysis.value?.confidence !== undefined
    && analysis.value.confidence < 0.5,
)

function stopAnalyzePolling(): void {
  if (analyzeTimer !== null) {
    clearInterval(analyzeTimer)
    analyzeTimer = null
  }
}

function resetAnalyzeState(): void {
  stopAnalyzePolling()
  analyzing.value = false
  analyzeElapsed = 0
  analyzeSeconds.value = 0
  analyzePollCount.value = 0
  analyzeTaskId.value = null
}

async function pollAnalyze(): Promise<void> {
  const taskId = analyzeTaskId.value
  if (taskId === null || !analyzing.value) return
  analyzePollCount.value += 1
  try {
    const task = await getTask(taskId)
    if (!analyzing.value) return          // 卸载/重置后迟到的结果丢弃
    if (task.status === 'succeeded') {
      const skipped = Boolean((task.result as Record<string, unknown> | null)?.skipped)
      resetAnalyzeState()
      await load()
      if (skipped) ElMessage.info('已有诊断，未重复调用')
      return
    }
    if (task.status === 'failed') {
      analyzeError.value = task.error || '诊断失败，可重试'
      resetAnalyzeState()
      analyzing.value = false
      return
    }
  } catch {
    // http.ts 已弹错；这里只停轮询，避免无限重试
    resetAnalyzeState()
  }
}

async function startAnalyze(): Promise<void> {
  if (analyzing.value || detail.value === null) return
  analyzeError.value = ''
  analyzing.value = true
  try {
    const task = await analyzeMistake(detail.value.id, true)
    analyzeTaskId.value = task.id
    analyzeTimer = setInterval(() => {
      analyzeSeconds.value += 4
      void pollAnalyze()
    }, 4000)
  } catch {
    analyzing.value = false
    analyzeError.value = '发起诊断失败，请稍后重试'
  }
}

onBeforeUnmount(() => {
  resetAnalyzeState()
})
```

> `onBeforeUnmount` 若已存在，把这段合并进既有回调（不要写两个同名钩子）。

模板里把 `AI 错因诊断将在 S4-3 上线` 的 `el-empty` 段替换为：

```vue
<el-card shadow="never" class="section">
  <template #header>
    <div class="section-head">
      <span>AI 错因诊断</span>
      <el-button
        v-if="analysis"
        size="small"
        :loading="analyzing"
        :disabled="analyzing"
        @click="startAnalyze"
      >重新诊断</el-button>
    </div>
  </template>

  <el-alert v-if="analyzeError" type="error" :title="analyzeError" :closable="false" show-icon />

  <div v-if="analyzing" class="analyzing">
    <el-icon class="is-loading"><Loading /></el-icon>
    诊断中…已等待 {{ analyzeSeconds }} 秒
  </div>

  <template v-else-if="analysis">
    <div class="cause-row">
      <el-tag :type="analysis.cause_type === 'unknown' ? 'info' : 'warning'" size="small">
        {{ analysis.cause_type === 'unknown' ? '错因未知' : analysis.cause_type }}
      </el-tag>
      <el-tag
        v-for="cause in analysis.secondary_causes"
        :key="cause"
        size="small"
        type="info"
        effect="plain"
      >{{ cause }}</el-tag>
      <span v-if="analysis.confidence !== null" class="confidence">置信度 {{ Math.round(analysis.confidence * 100) }}%</span>
    </div>
    <el-alert
      v-if="lowConfidence"
      type="warning"
      title="诊断把握较低，建议人工确认"
      :closable="false"
      show-icon
    />
    <p v-if="analysis.cause_type === 'unknown'" class="hint">未提供作答，仅讲解题目，不推断错因。</p>
    <template v-else>
      <p class="field-label">第一处错误</p>
      <p class="error-step">{{ analysis.error_step || '未定位到明确的错误步骤' }}</p>
    </template>
    <p class="field-label">正确解法</p>
    <MdPreview :model-value="analysis.explanation_md || '（无）'" :preview-theme="'github'" />
    <p class="field-label">复习建议</p>
    <MdPreview :model-value="analysis.review_advice_md || '（无）'" :preview-theme="'github'" />
    <p class="hint">诊断模型：{{ analysis.model }} · Prompt {{ analysis.prompt_version }}</p>
  </template>

  <el-empty v-else description="尚未诊断">
    <el-button type="primary" :loading="analyzing" @click="startAnalyze">立即诊断</el-button>
  </el-empty>
</el-card>
```

样式追加（与文件既有 scoped 风格一致）：

```css
.section-head { display: flex; align-items: center; justify-content: space-between; }
.cause-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.confidence { color: var(--el-text-color-secondary); font-size: 12px; }
.error-step { background: var(--el-fill-color-light); border-left: 3px solid var(--el-color-warning); padding: 8px 12px; margin: 4px 0 12px; white-space: pre-wrap; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; }
.analyzing { display: flex; align-items: center; gap: 6px; color: var(--el-text-color-secondary); }
```

- [x] **Step 5: 跑测试**

```powershell
cd web
$env:NODE_OPTIONS="--require E:\BiShe-AIStudy\.sdd\tools\dsh-exec-patch.cjs"
npm run test:run -- --pool=threads src/views/mistakes/__tests__/MistakeDetailView.spec.ts
```

Expected: 追加的 8 条全绿，旧用例不回归

- [x] **Step 6: 全量前端测试 + build**

```powershell
cd web
$env:NODE_OPTIONS="--require E:\BiShe-AIStudy\.sdd\tools\dsh-exec-patch.cjs"
npm run test:run -- --pool=threads
npm run build
```

Expected: ≥ 188 passed；build 成功

- [x] **Step 7: Commit**

```bash
git add web/src/types/mistakes.ts web/src/api/mistakes.ts web/src/views/mistakes/MistakeDetailView.vue web/src/views/mistakes/__tests__/MistakeDetailView.spec.ts
git commit -m "feat(s4-3): 详情页诊断区与重新诊断轮询"
```

---

### Task 7: 自测集构造脚本（30 条「错题 + 学生作答」）

**Files:**
- Create: `测试数据/_make_s4_3_cases.py`
- Create（运行产物，**不提交**）：`测试数据/s4_3_cases.json`

**Interfaces:**
- Consumes: `POST /auth/register`、`POST /auth/login`、`POST /questions`、`POST /mistakes`、`POST /mistakes/{id}/analyze`、`GET /tasks/{id}`。
- Produces: `测试数据/s4_3_cases.json`——`{"subject_id": 7, "user": "...", "cases": [{"mistake_id": 1, "question_id": 2, "label": "概念不清", "my_answer_md": "...", "stem": "..."}]}`，Task 8 的评分脚本读它。

- [x] **Step 1: 写脚本**

`测试数据/_make_s4_3_cases.py`（**只构造数据，不做判定**；判定在 Task 8）：

```python
"""S4-3 真机验收自测集：造 30 道题 + 30 条「错题 + 学生作答」，覆盖 6 类错因。

注意：这是**人工构造的自测集**，不是真实学生数据（AGENTS §6 / spec D-15）。
用法：cd backend && ..\\.venv\\Scripts\\python.exe E:\\BiShe-AIStudy\\study-agent\\测试数据\\_make_s4_3_cases.py
重跑安全：题目按 stem 判重命中 409 时复用既有题（GET /questions?query= 找），错题按 (user, question) 复用。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8031/api/v1"
SUBJECT_ID = 7  # 高中数学
USER, PWD = "s43_accept_20261103", "accept-pass-2026"
OUT_PATH = Path(__file__).with_name("s4_3_cases.json")

# (题干, 选项, 标答, 学生作答, 人工标注错因)
CASES: list[dict] = [
    # —— 概念不清 ×5 ——
    {"stem": "已知函数 $f(x)=x^2-4x+3$，求其对称轴。", "options": None,
     "answer": "$x=2$", "my_answer": "对称轴 x=1", "label": "概念不清"},
    {"stem": "求函数 $y=2x^2+4x-1$ 的最小值。", "options": None,
     "answer": "$-3$", "my_answer": "最小值是 -1", "label": "概念不清"},
    {"stem": "判断函数 $f(x)=\\frac{1}{x}$ 在 $(0,+\\infty)$ 上的单调性。", "options": None,
     "answer": "单调递减", "my_answer": "单调递增", "label": "概念不清"},
    {"stem": "若 $\\log_a 2 < 1$，求 $a$ 的取值范围（$a>0$ 且 $a\\neq1$）。", "options": None,
     "answer": "$a>2$", "my_answer": "$0<a<2$", "label": "概念不清"},
    {"stem": "等差数列 $\\{a_n\\}$ 中 $a_1=2$，公差 $d=3$，求 $a_5$。", "options": None,
     "answer": "$14$", "my_answer": "$17$", "label": "概念不清"},
    # —— 计算失误 ×5 ——
    {"stem": "计算 $\\int_0^1 (2x+1)\\,dx$。", "options": None,
     "answer": "$2$", "my_answer": "1", "label": "计算失误"},
    {"stem": "解方程 $x^2-5x+6=0$。", "options": None,
     "answer": "$x=2$ 或 $x=3$", "my_answer": "x=2 或 x=-3", "label": "计算失误"},
    {"stem": "计算 $\\sin 30^\\circ + \\cos 60^\\circ$。", "options": None,
     "answer": "$1$", "my_answer": "0.5", "label": "计算失误"},
    {"stem": "化简 $(a+b)^2-(a-b)^2$。", "options": None,
     "answer": "$4ab$", "my_answer": "$2ab$", "label": "计算失误"},
    {"stem": "求等比数列 $2,4,8,\\dots$ 的前 5 项和。", "options": None,
     "answer": "$62$", "my_answer": "58", "label": "计算失误"},
    # —— 审题偏差 ×5 ——
    {"stem": "已知 $a=3$，$b=-2$，求 $a^2-b$ 的值。", "options": None,
     "answer": "$11$", "my_answer": "7", "label": "审题偏差"},
    {"stem": "某商品先涨价 10% 再降价 10%，现价与原价相比如何？", "options": None,
     "answer": "下降 1%", "my_answer": "不变", "label": "审题偏差"},
    {"stem": "求函数 $y=x^2$ 在区间 $[-2,1]$ 上的最大值。", "options": None,
     "answer": "$4$", "my_answer": "1", "label": "审题偏差"},
    {"stem": "若 $x>0$，求 $x+\\frac{4}{x}$ 的最小值。", "options": None,
     "answer": "$4$", "my_answer": "最小值 2", "label": "审题偏差"},
    {"stem": "集合 $A=\\{1,2,3\\}$，$B=\\{2,3,4\\}$，求 $A\\cap B$ 的元素个数。", "options": None,
     "answer": "$2$", "my_answer": "3", "label": "审题偏差"},
    # —— 方法不当 ×5 ——
    {"stem": "求函数 $f(x)=x^3-3x$ 的极值点。", "options": None,
     "answer": "$x=-1$ 为极大值点，$x=1$ 为极小值点",
     "my_answer": "令 f'(x)=0 得 x=±1，所以极值点是 ±1", "label": "方法不当"},
    {"stem": "证明：对任意实数 $x$，$x^2+2x+3>0$。", "options": None,
     "answer": "配方得 $(x+1)^2+2>0$",
     "my_answer": "取 x=0 代入成立，所以对任意 x 都成立", "label": "方法不当"},
    {"stem": "求 $\\sqrt{12}+\\sqrt{27}$ 的值。", "options": None,
     "answer": "$5\\sqrt{3}$", "my_answer": "\\sqrt{39}", "label": "方法不当"},
    {"stem": "已知 $\\sin\\alpha=\\frac{3}{5}$，$\\alpha$ 为第二象限角，求 $\\cos\\alpha$。", "options": None,
     "answer": "$-\\frac{4}{5}$", "my_answer": "直接写 4/5", "label": "方法不当"},
    {"stem": "解不等式 $\\frac{x-1}{x+2}>0$。", "options": None,
     "answer": "$x>1$ 或 $x<-2$", "my_answer": "两边乘 x+2 得 x-1>0，即 x>1", "label": "方法不当"},
    # —— 知识遗忘 ×5 ——
    {"stem": "写出两角和正弦公式 $\\sin(\\alpha+\\beta)=$。", "options": None,
     "answer": "$\\sin\\alpha\\cos\\beta+\\cos\\alpha\\sin\\beta$",
     "my_answer": "sinαcosβ-cosαsinβ", "label": "知识遗忘"},
    {"stem": "写出等差数列前 $n$ 项和公式 $S_n=$。", "options": None,
     "answer": "$\\frac{n(a_1+a_n)}{2}$", "my_answer": "n(a1+an)", "label": "知识遗忘"},
    {"stem": "写出 $\\log_a(MN)=$（$a>0,a\\neq1$）。", "options": None,
     "answer": "$\\log_a M+\\log_a N$", "my_answer": "log_a M · log_a N", "label": "知识遗忘"},
    {"stem": "写出余弦定理 $c^2=$。", "options": None,
     "answer": "$a^2+b^2-2ab\\cos C$", "my_answer": "a^2+b^2", "label": "知识遗忘"},
    {"stem": "写出导数的幂函数法则 $(x^n)'=$。", "options": None,
     "answer": "$nx^{n-1}$", "my_answer": "x^{n-1}", "label": "知识遗忘"},
    # —— 时间不足 ×5（作答明显截断）——
    {"stem": "求函数 $f(x)=x^2-2x+3$ 在 $[0,3]$ 上的值域。", "options": None,
     "answer": "$[2,6]$", "my_answer": "配方得 (x-1)^2+2，所以最小 2", "label": "时间不足"},
    {"stem": "求过点 $(1,2)$ 且斜率为 3 的直线方程。", "options": None,
     "answer": "$y=3x-1$", "my_answer": "y-2=3(x-1)，展开", "label": "时间不足"},
    {"stem": "求数列 $1,\\frac{1}{2},\\frac{1}{4},\\dots$ 的前 4 项和。", "options": None,
     "answer": "$\\frac{15}{8}$", "my_answer": "1+1/2+1/4", "label": "时间不足"},
    {"stem": "已知 $A(1,2)$，$B(4,6)$，求 $|AB|$。", "options": None,
     "answer": "$5$", "my_answer": "√(9+16)=√25", "label": "时间不足"},
    {"stem": "求 $\\lim_{x\\to 0}\\frac{\\sin x}{x}$。", "options": None,
     "answer": "$1$", "my_answer": "用洛必达，cos x / 1", "label": "时间不足"},
]


def login(c: httpx.Client) -> dict[str, str]:
    c.post(
        f"{BASE}/auth/register",
        json={"username": USER, "password": PWD, "nickname": "S4-3验收",
              "grade": "高二", "role": "student"},
    )
    resp = c.post(f"{BASE}/auth/login", json={"username": USER, "password": PWD})
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


def ensure_question(c: httpx.Client, h: dict[str, str], case: dict) -> int:
    body = {
        "subject_id": SUBJECT_ID,
        "stem_md": case["stem"],
        "qtype": "解答",
        "difficulty": 3,
        "origin": "upload",
        "answer_md": case["answer"],
    }
    if case["options"]:
        body["options"] = case["options"]
        body["qtype"] = "单选"
    resp = c.post(f"{BASE}/questions", headers=h, json=body)
    if resp.status_code == 201:
        return resp.json()["data"]["id"]
    if resp.status_code == 409:
        # 重复跑：题干判重命中 → 从题库按题干片段找回
        page = c.get(
            f"{BASE}/questions", headers=h,
            params={"subject_id": SUBJECT_ID, "query": case["stem"][:20]},
        ).json()["data"]["items"]
        for item in page:
            if item["stem_md"] == case["stem"]:
                return item["id"]
    raise SystemExit(f"建题失败 {resp.status_code}: {resp.text[:300]}")


def main() -> int:
    cases_out: list[dict] = []
    with httpx.Client(timeout=120.0) as c:
        h = login(c)
        for index, case in enumerate(CASES, start=1):
            question_id = ensure_question(c, h, case)
            resp = c.post(
                f"{BASE}/mistakes", headers=h,
                json={"question_id": question_id, "my_answer_md": case["my_answer"]},
            )
            if resp.status_code not in (200, 201):
                raise SystemExit(f"建错题失败 {resp.status_code}: {resp.text[:300]}")
            mistake_id = resp.json()["data"]["mistake"]["id"]
            cases_out.append({
                "index": index,
                "mistake_id": mistake_id,
                "question_id": question_id,
                "label": case["label"],
                "my_answer_md": case["my_answer"],
                "stem": case["stem"],
            })
            print(f"[{index:02d}/30] mistake={mistake_id} label={case['label']}")

    OUT_PATH.write_text(
        json.dumps({"subject_id": SUBJECT_ID, "user": USER, "cases": cases_out},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"写出 {OUT_PATH}（{len(cases_out)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 2: 起服务并跑脚本**

```powershell
# 终端 1（backend\）：uvicorn 8031
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8031
# 终端 2（backend\）：ARQ worker
..\.venv\Scripts\python.exe -m arq app.tasks.worker.WorkerSettings
# 终端 3：造数据
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe E:\BiShe-AIStudy\study-agent\测试数据\_make_s4_3_cases.py
```

Expected: 30 行 `[NN/30] mistake=… label=…`，最后写出 `测试数据/s4_3_cases.json`；重跑 30 条全部走复用分支（不新建题）。

- [x] **Step 3: 抽查自动入队是否真的发生**

```powershell
..\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from sqlalchemy import text; from app.core.db import new_session; s=new_session(); print(s.execute(text(\"select name, status, count(*) from async_tasks where name='mistake.analyze' group by 1,2 order by 2\")).all()); s.close()"
```

Expected: 至少 30 行 `mistake.analyze` 的 `succeeded`（worker 在跑）；若为 `pending` 说明 worker 没起或 Redis 不通。

- [x] **Step 4: Commit（只提交脚本，不提交产物）**

```bash
git add 测试数据/_make_s4_3_cases.py
git commit -m "test(s4-3): 30 条错因自测集构造脚本（人工标注，非真实学生数据）"
```

---

### Task 8: 真机验收——跑 30 条 + 人工核对准确率

**Files:**
- Create: `E:\BiShe-AIStudy\.sdd\s4-3\accept_s4_3.py`
- Create: `E:\BiShe-AIStudy\.sdd\s4-3\accept_s4_3.out.txt`（脚本输出）
- Create: `E:\BiShe-AIStudy\.sdd\s4-3\acceptance-evidence.md`（准确率表 + 混淆矩阵 + 边界证据）

**Interfaces:**
- Consumes: `测试数据/s4_3_cases.json`（Task 7）、`GET /mistakes/{id}`、`POST /mistakes/{id}/analyze`、`GET /tasks/{id}`。
- Produces: 准确率数字，Task 9 写进 `PROGRESS.md` 与任务卡实施记录。

- [x] **Step 1: 写验收脚本**

`.sdd/s4-3/accept_s4_3.py`：

```python
"""S4-3 真机验收：强制重跑 30 条诊断、收集输出、算主因准确率与混淆矩阵。"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8031/api/v1"
USER, PWD = "s43_accept_20261103", "accept-pass-2026"
CASES = Path(r"E:\BiShe-AIStudy\study-agent\测试数据\s4_3_cases.json")

CAUSES = ["概念不清", "计算失误", "审题偏差", "方法不当", "知识遗忘", "时间不足"]


def login(c: httpx.Client) -> dict[str, str]:
    resp = c.post(f"{BASE}/auth/login", json={"username": USER, "password": PWD})
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


def wait_task(c: httpx.Client, h: dict[str, str], task_id: int, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = c.get(f"{BASE}/tasks/{task_id}", headers=h).json()["data"]
        if data["status"] in {"succeeded", "failed"}:
            return data
        time.sleep(2)
    raise SystemExit(f"任务 {task_id} 超时")


def main() -> int:
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    rows: list[dict] = []
    with httpx.Client(timeout=240.0) as c:
        h = login(c)
        for case in payload["cases"]:
            started = time.time()
            task = c.post(
                f"{BASE}/mistakes/{case['mistake_id']}/analyze?force=true", headers=h
            ).json()["data"]
            settled = wait_task(c, h, task["id"])
            elapsed = round(time.time() - started, 1)
            if settled["status"] != "succeeded":
                rows.append({**case, "error": settled.get("error"), "elapsed": elapsed})
                print(f"[{case['index']:02d}] FAILED {settled.get('error')}")
                continue
            detail = c.get(f"{BASE}/mistakes/{case['mistake_id']}", headers=h).json()["data"]
            a = detail.get("analysis") or {}
            row = {
                **case,
                "cause_type": a.get("cause_type"),
                "secondary_causes": a.get("secondary_causes") or [],
                "confidence": a.get("confidence"),
                "error_step": a.get("error_step"),
                "hits_preview": (a.get("review_advice_md") or "")[:40],
                "elapsed": elapsed,
            }
            rows.append(row)
            mark = "OK " if row["cause_type"] == case["label"] else "MISS"
            print(f"[{case['index']:02d}] {mark} label={case['label']} got={row['cause_type']} "
                  f"secondary={row['secondary_causes']} conf={row['confidence']} {elapsed}s")

    total = len([r for r in rows if "error" not in r])
    exact = len([r for r in rows if r.get("cause_type") == r["label"]])
    soft = len([
        r for r in rows
        if r.get("cause_type") == r["label"] or r["label"] in (r.get("secondary_causes") or [])
    ])
    matrix: dict[str, Counter] = {}
    for r in rows:
        if "error" in r:
            continue
        matrix.setdefault(r["label"], Counter())[r.get("cause_type")] += 1
    summary = {
        "cases": len(rows),
        "diagnosed": total,
        "primary_accuracy": round(exact / total, 3) if total else 0,
        "primary_or_secondary_accuracy": round(soft / total, 3) if total else 0,
        "avg_elapsed_s": round(sum(r["elapsed"] for r in rows) / len(rows), 1),
        "error_step_quoted": len([r for r in rows if r.get("error_step")]),
        "matrix": {k: dict(v) for k, v in matrix.items()},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    Path(r"E:\BiShe-AIStudy\.sdd\s4-3\accept_s4_3.out.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0 if summary["primary_accuracy"] >= 0.7 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 2: 跑**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe E:\BiShe-AIStudy\.sdd\s4-3\accept_s4_3.py 2>&1 | Tee-Object -FilePath E:\BiShe-AIStudy\.sdd\s4-3\accept_s4_3.out.txt
```

Expected: 30 行 `OK`/`MISS`，末尾 summary JSON；`primary_accuracy ≥ 0.7` 才 exit 0。

- [x] **Step 3: 人工逐条核对（这是验收的核心，不许跳过）**

打开 `accept_s4_3.out.json`，逐条看 `explanation_md` / `error_step` / `review_advice_md` 是否真的讲了这道题，把**模型判错但人工认为可接受**（如「概念不清 vs 方法不当」）与**真的离谱**（如答非所问、编造笔记）分开计数，记进 `acceptance-evidence.md`：

```markdown
# S4-3 真机验收证据（2026-11-0X）

## 数据来源
30 条自测集（`测试数据/_make_s4_3_cases.py` 构造，6 类错因各 5 条），**非真实学生数据**。

## 主结果
- 已诊断：30/30，失败 0
- 主因准确率：XX%（目标 ≥70%）
- 主因或次因命中率：XX%
- 平均耗时：XX.X s
- error_step 非空：XX/30

## 混淆矩阵
| 人工标注 \ 模型 | 概念不清 | 计算失误 | 审题偏差 | 方法不当 | 知识遗忘 | 时间不足 |
|---|---|---|---|---|---|---|
| 概念不清 | … | | | | | |

## 逐条备注（分歧原因）
- #14 标注「方法不当」，模型「概念不清」：可接受（学生用了代入特值的伪证，属方法论错，但也可视为不理解恒成立）
- #27 标注「时间不足」，模型「计算失误」：不可接受？→ 如实写清
```

- [x] **Step 4: 跑边界用例（4 条，必须真跑）**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
# 1) 缺作答 → unknown
..\.venv\Scripts\python.exe -c "import httpx,json; c=httpx.Client(base_url='http://127.0.0.1:8031/api/v1'); h={'Authorization':'Bearer '+c.post('/auth/login',json={'username':'s43_accept_20261103','password':'accept-pass-2026'}).json()['data']['access_token']}; q=c.get('/questions',headers=h,params={'subject_id':7,'page_size':1}).json()['data']['items'][0]['id']; m=c.post('/mistakes',headers=h,json={'question_id':q}); mid=m.json()['data']['mistake']['id']; t=c.post(f'/mistakes/{mid}/analyze',headers=h).json()['data']['id']; import time; [time.sleep(2) for _ in range(20) if c.get(f'/tasks/{t}',headers=h).json()['data']['status'] not in ('succeeded','failed')]; print(json.dumps(c.get(f'/mistakes/{mid}',headers=h).json()['data']['analysis'],ensure_ascii=False))"
```

Expected: `cause_type=unknown`、`error_step=null`、`secondary_causes=[]`，`explanation_md` 仍有内容。

```powershell
# 2) 他人错题 404 / 3) force=false 已诊断 skipped / 4) 诊断失败时旧诊断保留
```

后 3 条直接写进 `accept_s4_3.py` 的 `--edges` 分支（或另写 `accept_s4_3_edges.py`），输出贴进 `acceptance-evidence.md`。`force=false` 的期望：任务 `succeeded` 且 `result.skipped=true`，诊断行 `created_at` 不变。

- [x] **Step 5: 重复性抽查（3 条 × 2 次）**

对 #1 / #10 / #20 再跑一次 `force=true`，记录两次 `cause_type` 是否一致，写进证据文档。Expected: 3/3 一致；不一致要如实记录。

- [x] **Step 6: 不提交（`.sdd/` 是否跟踪按仓库现状：S4-2 的 `.sdd` 未跟踪，继续不跟踪）**

---

### Task 9: 文档同步 + 全量回归

**Files:**
- Modify: `docs/API.md`（若 T1 已写全，只核对）
- Modify: `docs/SCHEMA.md`（核对 T1）
- Modify: `docs/DECISIONS.md`（新增 D-046）
- Modify: `docs/PROGRESS.md`（S4-3 条目 + 测试计数 + 验收数字 + 遗留）
- Modify: `AGENTS.md` §9.2（错因诊断一条）+ §9.6（锚点）
- Modify: `docs/AI协作开发实施计划.md`（S4-3 勾选 + 实施记录）

- [x] **Step 1: DECISIONS.md 追加 D-046**

```markdown
### D-046 错因诊断（S4-3）

- **诊断与录入解耦**：录入后 best-effort 入队 `mistake.analyze`，入队失败只 WARNING；`POST /mistakes/{id}/analyze` 手动重跑（`force` 默认 true）。
- **1:1 覆盖**：重跑 UPDATE 同一行，`created_at` 刷新为最近一次诊断时间（不新增 `analyzed_at`）。
- **unknown 代码强制**：`my_answer_md` 为空时 `cause_type=unknown`、`secondary_causes=[]`、`error_step=null`，不看模型输出。
- **error_step 必须有证据**：不含学生作答片段（≥2 字）时置 `null`，宁缺毋滥。
- **复习建议可降级**：笔记检索失败只 WARNING，诊断照跑；前置知识用 KP 父节点近似（图谱 S4-5 之前）。
- **验收口径**：30 条自测集（构造数据，非真实学生），主因准确率 = 命中/总数，目标 ≥70%；文档如实标注数据来源。
```

- [x] **Step 2: PROGRESS.md 增 S4-3 条目**

```markdown
### S4-3 错因诊断服务（2026-11-0X）
- spec / plan：`docs/spec/s4-3-mistake-analysis.md`、`docs/plan/s4-3-mistake-analysis.md`
- 迁移 `0011_s4_3`：`mistake_analyses` 加 `secondary_causes`（`<@` CHECK）与 `confidence`（0–1 CHECK）
- AI 层：`ai/analyze/mistake_analyzer.py` + `ai/prompts/mistake_analyze_v1.md`（严格 JSON + Pydantic + 2 次重试 + unknown 代码强制 + error_step 证据校验）
- 服务：`services/mistake_analysis_service.py`（上下文 = 题干/标答/学生作答/题目 KP/前置父节点/笔记 top-3；检索失败降级）
- 任务：`mistake.analyze`（不 commit）；题库录入与拍照识别各自 best-effort 入队；`POST /mistakes/{id}/analyze` 手动重跑
- 前端：详情页诊断区（主因/次因/置信度/第一处错误/正确解法/复习建议）+ 立即诊断/重新诊断 + 4s 轮询
- 测试：后端 **XXX passed**（基线 956），前端 **XXX passed**（基线 180）
- 真机验收：30 条自测集（非真实学生数据），主因准确率 **XX%**，主因或次因 **XX%**，平均 **XX.Xs**；见 `.sdd/s4-3/acceptance-evidence.md`
- 遗留：（按实回填，例如「概念不清 vs 方法不当」混淆、`confidence` 未校准）
```

- [x] **Step 3: AGENTS.md**

§9.2 追加「错因诊断（S4-3）」条目（口径按实现回填，至少含：仅入口 `mistake_analysis_service`、1:1 覆盖、unknown 代码强制、error_step 证据校验、检索降级、任务不 commit、`scene="mistake"`）；§9.6 追加锚点行：

```markdown
- 错因诊断样例：backend/app/ai/analyze/mistake_analyzer.py + backend/app/services/mistake_analysis_service.py + backend/app/tasks/analyze_mistake.py（诊断上下文六块；strict JSON + 2 次重试；缺作答强制 unknown；重跑 1:1 覆盖并刷新 created_at；笔记检索失败降级；任务不 commit）
```

- [x] **Step 4: 任务卡勾选 + 实施记录**

`docs/AI协作开发实施计划.md`：`- [ ] S4-3 错因诊断服务 ★关键` → `- [x]`，并在 S4-3 小节末追加「实施记录（2026-11-0X）」一行（测试数、准确率、遗留）。

- [x] **Step 5: 全量回归（贴输出）**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m alembic heads
..\.venv\Scripts\python.exe -m alembic check
cd ..\web
$env:NODE_OPTIONS="--require E:\BiShe-AIStudy\.sdd\tools\dsh-exec-patch.cjs"
npm run test:run -- --pool=threads
npm run build
```

Expected: 后端 ≥ 978 passed 1 warning；`0011_s4_3 (head)`；`No new upgrade operations detected.`；前端 ≥ 188 passed；build 成功。

- [x] **Step 6: Commit**

```bash
git add docs/API.md docs/SCHEMA.md docs/DECISIONS.md docs/PROGRESS.md AGENTS.md docs/AI协作开发实施计划.md
git commit -m "docs(s4-3): 契约与决策同步（D-046）、PROGRESS 与任务卡回填"
```

---

### Task 10: 终审与收尾

**Files:**（按评审结论）

- [x] **Step 1: 请求一次整支评审**

用 `superpowers:requesting-code-review` 起一个评审 subagent，范围 `git diff 655d464..HEAD`（S4-3 全部提交），要求按 Critical / Important / Minor 分级，重点看：

- 事务时序：拍照 handler 里 `create_task` 的提前提交是否会留下半写状态；
- `analyze` 的 upsert 是否真能在重跑时避免 `IntegrityError`；
- `unknown` 强制规则是否绕过了 Pydantic 校验（如 `error_step` 仍写入）；
- 前端轮询的卸载/重置竞态；
- `secondary_causes` 的 `<@` CHECK 是否真在库上生效（用真库验一次非法插入被拒）。

- [x] **Step 2: 修 Critical / Important**

每条修复配一条回归测试；修完重跑后端 + 前端全量。

- [x] **Step 3: 真库验证 CHECK**

```powershell
cd backend
..\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from sqlalchemy import text; from app.core.db import new_session; s=new_session(); 
try:
    s.execute(text(\"insert into mistake_analyses (mistake_id, cause_type, secondary_causes, model, prompt_version) values (-1,'概念不清',ARRAY['乱写'],'m','v')\"))
    print('BUG: 非法次因未被拒')
except Exception as e:
    print('OK 拒收:', type(e).__name__)
finally:
    s.rollback(); s.close()"
```

Expected: `OK 拒收: IntegrityError`

- [x] **Step 4: 收尾**

按 `superpowers:finishing-a-development-branch` 合并回 `main`（fast-forward）、删分支、更新 `.sdd/s4-3/progress.md` 的收尾记录。**不 push**（用户自己推）。

---

## 附：任务依赖与验收顺序

| Task | 依赖 | 关键产出 |
|---|---|---|
| 1 | — | 迁移 0011 + 契约 |
| 2 | 1 | `analyze_mistake()` |
| 3 | 2 | `analyze()` / `enqueue_analysis()` |
| 4 | 3 | `mistake.analyze` + 自动入队 |
| 5 | 4 | `POST /analyze` + DTO |
| 6 | 5 | 详情页诊断区 |
| 7 | 5 | 30 条自测集 |
| 8 | 7 | 准确率证据 |
| 9 | 8 | 文档与数字回填 |
| 10 | 9 | 评审修复 + 合并 |
