# S4-2 错题录入 + 状态机 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让学生能把错题（从题库选或拍照识别）记入错题本，并通过「复习记录」驱动 `待订正 → 已订正 → 已掌握` 状态机，列表可按状态/错因/知识点/时间筛选并出统计。

**Architecture:** 新增 `mistakes` / `mistake_analyses` 两表（后者只建表，S4-3 写入）；拍照链路 = 上传图片（`files`, `parse=false`）→ ARQ 任务 `mistake.recognize` → Qwen-VL 单图识别（`ai/vision/`）→ 复用 `question_service.create_question` 建/复用题目 → 建错题；所有读写经 `services/mistake_service.py`，路由只做参数校验与 `Envelope`。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic / Pydantic v2 / ARQ；Qwen-VL（DashScope OpenAI 兼容接口，`httpx`，不引新依赖）；Vue 3 + TS + Element Plus + md-editor-v3。

**Spec:** `docs/spec/s4-2-mistakes.md`（本 plan 的依据；两者冲突时以 spec 为准，spec 与契约文档冲突时以 `docs/SCHEMA.md`/`docs/API.md` 为准）

## Global Constraints

- 枚举一律 `TEXT + CHECK`，值集常量放 `app/models/enums.py`，CHECK 文本由 `in_check()` 生成（D-021）。`mistakes.status` 的中文三值来自 `SCHEMA.md` §10.7，**不许改成英文**。
- 表/约束命名：`uq_mistakes_user_question`、`ck_mistakes_status`、`ix_mistakes_user_status`、`fk_mistakes_question_id`；迁移文件名 `0010_s4_2_mistakes.py`，`down_revision="0009_s4_1"`。
- 所有 `mistakes` 查询**显式** `where(Mistake.user_id == viewer_id)`；他人记录与不存在统一 `NotFoundError`（404/40400），不泄露存在性。
- 路由函数 ≤30 行；service 一个用例一个事务（`_commit()`）；业务错误抛 `AppError` 子类（`NotFoundError`/`InvalidParamError`/`ConflictError`），禁止 `HTTPException`。
- 分页/排序只用 `page_params` / `sort_params` / `paginate_sa` / `apply_sort`；排序字段来自白名单；列表必须带 `id DESC` 兜底。
- 外部调用：LLM 只能经 `app/ai/` 适配器；每次调用落 `llm_call_logs`（`scene`/`model`/tokens/耗时/费用）；结构化输出 Pydantic 校验 + 最多 2 次重试。
- Prompt 存 `app/ai/prompts/*.md`，Jinja2 `StrictUndefined` 渲染；禁止硬编码长 prompt。
- 任务 handler 是同步 `(Session, payload)`，**不得自行 commit**；重试由 runner 决定。
- 测试：外部 LLM 一律 mock，套件内零真实网络调用；service 公共函数至少 1 条 happy + 1 条失败路径。
- 命令（Windows）：后端在 `backend\` 下用 `..\.venv\Scripts\python.exe -m pytest ...`；前端在 `web\` 下 `npm run test:run`（若 shell 报 `spawn EPERM`，加 `$env:NODE_OPTIONS="--require E:\BiShe-AIStudy\.sdd\tools\dsh-exec-patch.cjs"` 与 `--pool=threads`）。
- 提交信息用 Conventional Commits 且带任务号：`feat(s4-2): ...` / `fix(s4-2): ...` / `docs(s4-2): ...`。
- 基线：后端 `865 passed`，前端 `30 files / 125 passed`。每个 task 结束都必须全绿。

## File Structure

| 文件 | 职责 |
|---|---|
| `backend/app/models/enums.py`（改） | `MistakeStatus`、`CauseType` 两个 StrEnum |
| `backend/app/models/mistake.py`（新） | `mistakes` 表映射 |
| `backend/app/models/mistake_analysis.py`（新） | `mistake_analyses` 表映射（S4-2 只建表） |
| `backend/alembic/versions/0010_s4_2_mistakes.py`（新） | 两张表 + 索引 + 约束 |
| `backend/app/ai/llm/base.py`（改） | `LLMMessage.images` |
| `backend/app/ai/llm/openai_compat.py`（改） | 视觉消息组装（无图路径逐字不变） |
| `backend/app/ai/vision/__init__.py`（新） | 门面导出 `extract_mistake` / `VisionError` / `VisionExtract` |
| `backend/app/ai/vision/mistake_ocr.py`（新） | 单图识别（严格 JSON + 校验 + 2 次重试） |
| `backend/app/ai/prompts/mistake_ocr_v1.md`（新） | 识别 prompt |
| `backend/app/schemas/mistake.py`（新） | 出入参模型 |
| `backend/app/services/mistake_service.py`（新） | 唯一业务入口 |
| `backend/app/tasks/mistake_recognize.py`（新） | `mistake.recognize` handler |
| `backend/app/tasks/__init__.py`（改） | 注册副作用 import |
| `backend/app/api/v1/mistakes.py`（新） | 8 个路由 |
| `backend/app/api/router.py`（改） | 挂载 `mistakes` |
| `backend/app/core/config.py` + `.env.example`（改） | `VISION_MODEL` |
| `web/src/types/mistakes.ts`、`web/src/api/mistakes.ts`（新） | 前端契约与调用 |
| `web/src/views/mistakes/{MistakeListView,MistakeCaptureView,MistakeDetailView}.vue`（新） | 三页 |
| `web/src/router/index.ts`、`web/src/components/layout/nav.ts`（改） | 路由与侧栏 06 |
| `测试数据/_make_s4_2_mistake_photos.py`（新） | 合成验收图（Pillow） |

---

### Task 1: 技术探针 + 合成验收图

先验证 spec §14 的假设：DashScope OpenAI 兼容接口是否接受 **base64 data URL** 的 `image_url`。探针不过，后面 `ai/vision` 的形态要换，所以它是第一件事。

**Files:**
- Create: `测试数据/_make_s4_2_mistake_photos.py`
- Create: `E:\BiShe-AIStudy\.sdd\s4-2-mistakes\probe_vision.py`（仓库外临时脚本，不入库）
- Modify: `backend/app/core/config.py`（加 `vision_model`）、`backend/.env.example`（加 `VISION_MODEL=`）

**Interfaces:**
- Consumes: `app.core.config.get_settings()`（已有 `dashscope_api_key`、`_fallback_dashscope_key`）
- Produces: `vision_model: str`（默认 `"qwen-vl-max-latest"`）；`测试数据/mistake_photo_{clean,rotated,answered}.png` 三张图；一条结论文档

- [ ] **Step 1: 加配置项**

`backend/app/core/config.py` 在 `llm_model` 附近加：

```python
    vision_model: str = Field(
        default="qwen-vl-max-latest",
        description="多模态模型（S4-2 拍照错题识别），需支持 OpenAI 兼容的 image_url",
    )
```

`backend/.env.example` 对应位置加一行注释与变量：

```dotenv
# 拍照错题识别用的多模态模型（走同一 DASHSCOPE_API_KEY）
VISION_MODEL=qwen-vl-max-latest
```

- [ ] **Step 2: 写合成图脚本**

`测试数据/_make_s4_2_mistake_photos.py`（用 Pillow 渲染，输出三张图；图题内容取自 S4-1 的验收卷第一题，保证与题库可比对）：

```python
"""生成 S4-2 拍照录入的合成验收图（印刷体，非真实拍摄）。

三张图：
  clean     纯净白底题目图
  rotated   旋转 7° + 高斯噪声（模拟手持拍摄）
  answered  带「我的作答」手写体风格文本（用系统字体模拟，不冒充真实笔迹）
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).with_name("mistake_photo")
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
STEM = "1．已知函数 $f(x)=x^{2}-4x+3$。\n（1）求函数的对称轴；\n（2）当 $x\\in[0,3]$ 时，求 $f(x)$ 的最大值与最小值。"
ANSWER = "我的作答：对称轴 x=2；最大值 3，最小值 -1。"


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("找不到可用中文字体，请手工指定 FONT_CANDIDATES")


def _draw(text: str, *, answer: bool) -> Image.Image:
    image = Image.new("RGB", (1000, 620), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((60, 60), text, fill="black", font=_font(30), spacing=18)
    if answer:
        draw.multiline_text((60, 380), ANSWER, fill=(30, 60, 160), font=_font(26), spacing=14)
    return image


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clean = _draw(STEM, answer=False)
    clean.save(OUT / "clean.png")
    rotated = clean.rotate(7, resample=Image.BICUBIC, expand=True, fillcolor="white")
    rotated = rotated.filter(ImageFilter.GaussianBlur(0.6))
    rotated.save(OUT / "rotated.png")
    _draw(STEM, answer=True).save(OUT / "answered.png")
    for path in sorted(OUT.glob("*.png")):
        print(path.name, Image.open(path).size)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 生成图片并确认**

Run: `cd E:\BiShe-AIStudy\study-agent && .\.venv\Scripts\python.exe "测试数据\_make_s4_2_mistake_photos.py"`
Expected: 打印三行 `clean.png (1000, 620)` / `rotated.png (1098, 731)` / `answered.png (1000, 620)`（旋转后尺寸略大属正常）

- [ ] **Step 4: 写并跑视觉探针**

`E:\BiShe-AIStudy\.sdd\s4-2-mistakes\probe_vision.py`：

```python
"""探针：DashScope OpenAI 兼容接口是否接受 base64 data URL 的 image_url。"""
import base64, json, sys
from pathlib import Path

import httpx

sys.path.insert(0, r"E:\BiShe-AIStudy\study-agent\backend")
from app.core.config import get_settings

settings = get_settings()
key = settings.llm_api_key or settings.dashscope_api_key
img = Path(r"E:\BiShe-AIStudy\study-agent\测试数据\mistake_photo\clean.png").read_bytes()
data_url = "data:image/png;base64," + base64.b64encode(img).decode()

payload = {
    "model": settings.vision_model,
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "把图中的题目原样转写成文本，只输出文本。"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }],
    "max_tokens": 512,
}
resp = httpx.post(
    f"{settings.llm_base_url.rstrip('/')}/chat/completions",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    json=payload, timeout=90.0,
)
print("HTTP", resp.status_code)
print(resp.text[:1200])
json.dump({"status": resp.status_code, "body": resp.text[:4000]},
          open(r"E:\BiShe-AIStudy\.sdd\s4-2-mistakes\probe_vision_result.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
```

Run: `cd E:\BiShe-AIStudy\study-agent\backend && ..\.venv\Scripts\python.exe "E:\BiShe-AIStudy\.sdd\s4-2-mistakes\probe_vision.py"`
Expected: `HTTP 200`，正文里能读到题干（含 `x^{2}-4x+3` 或等价写法）

若 `HTTP 400` 且报 `image_url` 格式不支持 → **停**，按 spec §14 降级方案 1（改用 DashScope 原生 `multimodal-generation` 接口），把结论与改法写进 `docs/DECISIONS.md` 后再继续 Task 4；Task 2/3 不受影响可先做。

- [ ] **Step 5: 记录探针结论**

在 `E:\BiShe-AIStudy\.sdd\s4-2-mistakes\progress.md` 追加一段：HTTP 状态、模型名、首轮 token 数与耗时、是否接受 base64、识别文本与原文的差异（人工比对一句）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/.env.example "测试数据/_make_s4_2_mistake_photos.py"
git commit -m "feat(s4-2): 视觉模型配置项与合成验收图生成脚本"
```

---

### Task 2: 枚举 + 模型 + 迁移 `0010_s4_2`

**Files:**
- Modify: `backend/app/models/enums.py`（文件末尾追加两个枚举）
- Create: `backend/app/models/mistake.py`
- Create: `backend/app/models/mistake_analysis.py`
- Create: `backend/alembic/versions/0010_s4_2_mistakes.py`
- Test: `backend/tests/test_mistake_models.py`

**Interfaces:**
- Consumes: `app/models/question.py` 的写法（`in_check`、`Identity(always=True)`、`created_at` server_default）、`app/models/file.py`
- Produces:
  - `MistakeStatus.TODO/.CORRECTED/.MASTERED`（值 `"待订正"/"已订正"/"已掌握"`）
  - `CauseType.CONCEPT/.CALC/.READING/.METHOD/.FORGET/.TIME/.UNKNOWN`
  - `MISTAKE_STATUSES: tuple[str, ...]`、`CAUSE_TYPES: tuple[str, ...]`
  - `app.models.mistake.Mistake`：`id, user_id, question_id, my_answer_md, correct_answer_md, image_file_id, status, correct_streak, created_at, last_review_at`
  - `app.models.mistake_analysis.MistakeAnalysis`：`id, mistake_id, kp_ids, cause_type, error_step, explanation_md, similar_questions_json, review_advice_md, model, prompt_version, created_at`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_mistake_models.py`：

```python
from app.models.enums import CAUSE_TYPES, MISTAKE_STATUSES, CauseType, MistakeStatus


def test_mistake_status_values_match_schema():
    assert MISTAKE_STATUSES == ("待订正", "已订正", "已掌握")
    assert MistakeStatus.MASTERED.value == "已掌握"


def test_cause_types_include_unknown_for_missing_answer():
    assert set(CAUSE_TYPES) == {
        "概念不清", "计算失误", "审题偏差", "方法不当", "知识遗忘", "时间不足", "unknown",
    }
    assert CauseType.UNKNOWN.value == "unknown"


def test_mistake_table_columns_and_constraints():
    from app.models.mistake import Mistake

    assert Mistake.__tablename__ == "mistakes"
    names = {c.name for c in Mistake.__table__.constraints}
    assert "uq_mistakes_user_question" in names
    assert "ck_mistakes_status" in names
    assert "ck_mistakes_correct_streak" in names
    # 默认值走 server_default（与 questions 表一致），不是 Python 端 default
    assert "待订正" in str(Mistake.__table__.c.status.server_default.arg)
    assert str(Mistake.__table__.c.correct_streak.server_default.arg) == "0"


def test_mistake_analysis_unique_and_cascade():
    from app.models.mistake_analysis import MistakeAnalysis

    assert MistakeAnalysis.__tablename__ == "mistake_analyses"
    fk = next(iter(MistakeAnalysis.__table__.foreign_keys))
    assert fk.ondelete == "CASCADE"
    names = {c.name for c in MistakeAnalysis.__table__.constraints}
    assert "uq_mistake_analyses_mistake_id" in names
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_models.py -q`
Expected: FAIL —— `ImportError: cannot import name 'MistakeStatus'` 或 `No module named 'app.models.mistake'`

- [ ] **Step 3: 加枚举**

`backend/app/models/enums.py` 末尾追加：

```python
class MistakeStatus(StrEnum):
    """错题状态机（SCHEMA §10.7 固定中文值）。"""

    TODO = "待订正"
    CORRECTED = "已订正"
    MASTERED = "已掌握"


class CauseType(StrEnum):
    """错因分类（方案 6.3 六类 + 作答缺失时的 unknown）。"""

    CONCEPT = "概念不清"
    CALC = "计算失误"
    READING = "审题偏差"
    METHOD = "方法不当"
    FORGET = "知识遗忘"
    TIME = "时间不足"
    UNKNOWN = "unknown"


MISTAKE_STATUSES: tuple[str, ...] = tuple(item.value for item in MistakeStatus)
CAUSE_TYPES: tuple[str, ...] = tuple(item.value for item in CauseType)
```

- [ ] **Step 4: 写两个模型**

`backend/app/models/mistake.py`：

```python
"""错题（SCHEMA §5.3）。

user_id + question_id 唯一：同一学生对同一题只保留一条错题，再错一次是
「复用并重置」，不是新增一条（spec D-1）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import MISTAKE_STATUSES, MistakeStatus, in_check


class Mistake(Base):
    __tablename__ = "mistakes"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_mistakes_user_question"),
        CheckConstraint(in_check("status", MISTAKE_STATUSES), name="ck_mistakes_status"),
        CheckConstraint("correct_streak >= 0", name="ck_mistakes_correct_streak"),
        Index("ix_mistakes_user_status", "user_id", "status"),
        Index("ix_mistakes_user_created", "user_id", "created_at"),
        Index("ix_mistakes_question_id", "question_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_mistakes_user_id"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("questions.id", name="fk_mistakes_question_id", ondelete="RESTRICT"),
        nullable=False,
    )
    my_answer_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    correct_answer_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_file_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("files.id", name="fk_mistakes_image_file_id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{MistakeStatus.TODO.value}'")
    )
    correct_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

`backend/app/models/mistake_analysis.py`：

```python
"""错题诊断结果（SCHEMA §5.4）。S4-2 只建表，写入在 S4-3。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import CAUSE_TYPES, in_check


class MistakeAnalysis(Base):
    __tablename__ = "mistake_analyses"
    __table_args__ = (
        UniqueConstraint("mistake_id", name="uq_mistake_analyses_mistake_id"),
        CheckConstraint(in_check("cause_type", CAUSE_TYPES), name="ck_mistake_analyses_cause_type"),
        Index("ix_mistake_analyses_kp_ids", "kp_ids", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    mistake_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mistakes.id", name="fk_mistake_analyses_mistake_id", ondelete="CASCADE"),
        nullable=False,
    )
    kp_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger), nullable=True)
    cause_type: Mapped[str] = mapped_column(Text, nullable=False)
    error_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    similar_questions_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    review_advice_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

> 若 `app/models/base.py` 的基类名不是 `Base`，按实际名字改（`grep -n "class .*Base" app/models/base.py`）。

- [ ] **Step 5: 写迁移**

`backend/alembic/versions/0010_s4_2_mistakes.py`（**手写**，不要 autogenerate 后不回看）：

```python
"""S4-2 错题与错题诊断表

Revision ID: 0010_s4_2
Revises: 0009_s4_1
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_s4_2"
down_revision = "0009_s4_1"
branch_labels = None
depends_on = None

_STATUSES = ("待订正", "已订正", "已掌握")
_CAUSES = ("概念不清", "计算失误", "审题偏差", "方法不当", "知识遗忘", "时间不足", "unknown")


def upgrade() -> None:
    op.create_table(
        "mistakes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("my_answer_md", sa.Text(), nullable=True),
        sa.Column("correct_answer_md", sa.Text(), nullable=True),
        sa.Column("image_file_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'待订正'"), nullable=False),
        sa.Column("correct_streak", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_mistakes_user_id"),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], name="fk_mistakes_question_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["image_file_id"], ["files.id"], name="fk_mistakes_image_file_id", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("user_id", "question_id", name="uq_mistakes_user_question"),
        sa.CheckConstraint(
            "status IN ({})".format(", ".join(f"'{v}'" for v in _STATUSES)), name="ck_mistakes_status"
        ),
        sa.CheckConstraint("correct_streak >= 0", name="ck_mistakes_correct_streak"),
    )
    op.create_index("ix_mistakes_user_status", "mistakes", ["user_id", "status"])
    op.create_index("ix_mistakes_user_created", "mistakes", ["user_id", "created_at"])
    op.create_index("ix_mistakes_question_id", "mistakes", ["question_id"])

    op.create_table(
        "mistake_analyses",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("mistake_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("cause_type", sa.Text(), nullable=False),
        sa.Column("error_step", sa.Text(), nullable=True),
        sa.Column("explanation_md", sa.Text(), nullable=True),
        sa.Column("similar_questions_json", postgresql.JSONB(), nullable=True),
        sa.Column("review_advice_md", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["mistake_id"], ["mistakes.id"], name="fk_mistake_analyses_mistake_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("mistake_id", name="uq_mistake_analyses_mistake_id"),
        sa.CheckConstraint(
            "cause_type IN ({})".format(", ".join(f"'{v}'" for v in _CAUSES)),
            name="ck_mistake_analyses_cause_type",
        ),
    )
    op.create_index(
        "ix_mistake_analyses_kp_ids", "mistake_analyses", ["kp_ids"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_mistake_analyses_kp_ids", table_name="mistake_analyses")
    op.drop_table("mistake_analyses")
    op.drop_index("ix_mistakes_question_id", table_name="mistakes")
    op.drop_index("ix_mistakes_user_created", table_name="mistakes")
    op.drop_index("ix_mistakes_user_status", table_name="mistakes")
    op.drop_table("mistakes")
```

- [ ] **Step 6: 迁移上/下各跑一次**

Run: `cd backend && ..\.venv\Scripts\python.exe -m alembic upgrade head && ..\.venv\Scripts\python.exe -m alembic current`
Expected: `0010_s4_2 (head)`

Run: `..\.venv\Scripts\python.exe -m alembic downgrade 0009_s4_1 && ..\.venv\Scripts\python.exe -m alembic upgrade head`
Expected: 两次都无报错（证明 downgrade 可用）

- [ ] **Step 7: 跑模型测试**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_mistake_models.py -q`
Expected: `4 passed`

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/enums.py backend/app/models/mistake.py \
        backend/app/models/mistake_analysis.py backend/alembic/versions/0010_s4_2_mistakes.py \
        backend/tests/test_mistake_models.py
git commit -m "feat(s4-2): 错题与错题诊断两表（迁移 0010）与状态/错因枚举"
```

---

### Task 3: `LLMMessage` 支持图片（无图路径逐字不变）

**Files:**
- Modify: `backend/app/ai/llm/base.py:12-16`
- Modify: `backend/app/ai/llm/openai_compat.py:152-172`（`_build_payload`）
- Test: `backend/tests/test_llm_vision_message.py`

**Interfaces:**
- Consumes: `LLMMessage(role, content)` 现有全部调用方（QA/改写/对齐/切题）—— 它们不传 `images`，必须零改动
- Produces:
  - `LLMMessage(role: Role, content: str, images: tuple[str, ...] | None = None)`（用 tuple 保持 `frozen=True` 可哈希）
  - `_build_payload` 生成的消息：`images` 为空 → `{"role":..., "content": str}`；非空 → `{"role":..., "content": [{"type":"text","text":...}, {"type":"image_url","image_url":{"url":...}}]}`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_llm_vision_message.py`：

```python
import pytest

from app.ai.llm import LLMMessage, OpenAICompatibleLLMClient


def _client() -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        api_key="test-key", base_url="http://127.0.0.1:9/v1", model="qwen-vl-max-latest",
        timeout=5.0, max_retries=0, temperature=0.0, max_output_tokens=256,
        price_input_per_million=0.0, price_output_per_million=0.0, log_calls=False,
    )


def test_text_only_payload_unchanged():
    payload = _client()._build_payload(
        [LLMMessage(role="user", content="你好")], temperature=0.0, max_tokens=8, stream=False
    )
    # 这是既有行为：content 是字符串，不是数组
    assert payload["messages"] == [{"role": "user", "content": "你好"}]


def test_single_image_becomes_content_parts():
    payload = _client()._build_payload(
        [LLMMessage(role="user", content="识图", images=("data:image/png;base64,AAA",))],
        temperature=0.0, max_tokens=8, stream=False,
    )
    content = payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "识图"}
    assert content[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}


def test_multiple_images_are_appended_in_order():
    payload = _client()._build_payload(
        [LLMMessage(role="user", content="看图", images=("data:image/png;base64,1", "data:image/png;base64,2"))],
        temperature=0.0, max_tokens=8, stream=False,
    )
    urls = [part["image_url"]["url"] for part in payload["messages"][0]["content"][1:]]
    assert urls == ["data:image/png;base64,1", "data:image/png;base64,2"]


def test_system_message_with_images_is_rejected():
    with pytest.raises(ValueError):
        LLMMessage(role="system", content="规则", images=("data:image/png;base64,AAA",))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_llm_vision_message.py -q`
Expected: FAIL —— `TypeError: LLMMessage.__init__() got an unexpected keyword argument 'images'`

- [ ] **Step 3: 改 `LLMMessage`**

`backend/app/ai/llm/base.py` 第 12–16 行替换为：

```python
@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str
    # 图片只允许挂在 user 消息上（OpenAI 兼容协议的系统消息不接受多模态内容）；
    # 用 tuple 而不是 list，保持 dataclass 可哈希（缓存/去重可能用到）。
    images: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.images and self.role != "user":
            raise ValueError("只有 user 消息可以携带图片")
        for item in self.images or ():
            if not item.startswith("data:image/"):
                raise ValueError("图片必须是 data URL（data:image/...;base64,...）")
```

- [ ] **Step 4: 改 `_build_payload`**

`backend/app/ai/llm/openai_compat.py` 的 `_build_payload` 中 `messages` 列表推导替换为：

```python
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_build_message(message) for message in messages],
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_output_tokens if max_tokens is None else max_tokens,
        }
```

在同文件模块级（`_build_payload` 之前）加：

```python
def _build_message(message: LLMMessage) -> dict[str, Any]:
    """无图消息保持字符串 content（与 S1-6 起的既有行为逐字一致）。"""
    if not message.images:
        return {"role": message.role, "content": message.content}
    parts: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
    parts.extend({"type": "image_url", "image_url": {"url": url}} for url in message.images)
    return {"role": message.role, "content": parts}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_llm_vision_message.py -q`
Expected: `4 passed`

- [ ] **Step 6: 跑相关既有测试确认零回归**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_llm_openai_compat.py tests/test_llm_client.py -q`
（文件名按实际存在者）；若不存在则跑 `..\.venv\Scripts\python.exe -m pytest -q -k "llm"`
Expected: 全绿（无图路径未变）

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai/llm/base.py backend/app/ai/llm/openai_compat.py backend/tests/test_llm_vision_message.py
git commit -m "feat(s4-2): LLMMessage 支持 data URL 图片，纯文本路径保持原样"
```

---

### Task 4: 视觉识别器 `ai/vision` + prompt

**Files:**
- Create: `backend/app/ai/prompts/mistake_ocr_v1.md`
- Create: `backend/app/ai/vision/__init__.py`
- Create: `backend/app/ai/vision/mistake_ocr.py`
- Test: `backend/tests/test_mistake_vision.py`

**Interfaces:**
- Consumes: `LLMClient.chat(messages, *, temperature, max_tokens, scene) -> LLMResponse`（Task 3 的 `images`）、`app.ai.json_utils.loads_json_object`、`app.ai.extract.question_extractor.ExtractedOption`
- Produces: `ai/vision/__init__.py` 导出 `extract_mistake(image_bytes: bytes, mime: str, *, subject_name: str, llm_client: LLMClient | None = None, max_retries: int = 2) -> VisionExtract`、`VisionExtract`、`VisionError`

- [ ] **Step 1: 写 prompt**

`backend/app/ai/prompts/mistake_ocr_v1.md`（Jinja2，变量只有 `subject_name`）：

```markdown
你是{{ subject_name }}老师，负责把学生发来的一道错题照片转成结构化 JSON。

【要求】
1. 只识别照片里**完整的一道题**。若照片里有多个题号，只取最完整的那一道，并在 warnings 里说明。
2. stem_md：题干原文（保留公式，用 $...$ / $$...$$ 的 LaTeX）。**不要**改写、不要补全、不要加解释。
3. options：选择题的选项数组，`{"key": "A", "text": "..."}`；非选择题为 null。
4. qtype：单选 | 多选 | 填空 | 解答 —— 按题目实际判断。
5. correct_answer_md：照片里**印刷**的答案或解析（常见于教辅）。没有就 null，绝不允许自己解题。
6. my_answer_md：学生**手写**的作答。只抄可以辨认的部分；有涂改或看不清就整段 null，并在 warnings 说明「作答无法辨认」。
   **禁止猜测或补全学生写了什么** —— 宁可 null。
7. confidence：你对题干识别准确度的自评，0–1。
8. warnings：字符串数组，记录题号不全、图片模糊、疑似多题等问题；没有就空数组。

严格输出 JSON，不要代码围栏，不要解释：

{
  "stem_md": "...",
  "options": null,
  "qtype": "解答",
  "correct_answer_md": null,
  "my_answer_md": null,
  "confidence": 0.9,
  "warnings": []
}
```

- [ ] **Step 2: 写失败测试**

`backend/tests/test_mistake_vision.py`：

```python
import json

import pytest

from app.ai.llm.base import LLMResponse
from app.ai.vision import VisionError, extract_mistake


class FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.model = "qwen-vl-max-latest"

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls.append({"messages": messages, "scene": scene, "max_tokens": max_tokens})
        text = self.replies.pop(0)
        return LLMResponse(text=text, model=self.model, total_tokens=100, latency_ms=10)


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 64


GOOD = {
    "stem_md": "已知函数 $f(x)=x^{2}-4x+3$，求对称轴。",
    "options": None,
    "qtype": "解答",
    "correct_answer_md": None,
    "my_answer_md": "对称轴 x=2",
    "confidence": 0.86,
    "warnings": [],
}


def test_extract_mistake_returns_parsed_fields():
    client = FakeLLM([json.dumps(GOOD, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.stem_md.startswith("已知函数")
    assert result.my_answer_md == "对称轴 x=2"
    assert result.confidence == 0.86
    assert client.calls[0]["scene"] == "mistake_ocr"
    # 图片以 data URL 挂在 user 消息上
    assert client.calls[0]["messages"][-1].images[0].startswith("data:image/png;base64,")


def test_extract_mistake_retries_on_broken_json():
    client = FakeLLM(["not json", json.dumps(GOOD, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.qtype == "解答"
    assert len(client.calls) == 2


def test_extract_mistake_raises_after_two_retries():
    client = FakeLLM(["bad", "still bad", "nope"])
    with pytest.raises(VisionError) as excinfo:
        extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert len(client.calls) == 3  # 首次 + 2 次重试
    assert "3" in str(excinfo.value)


def test_extract_mistake_rejects_non_image_mime():
    with pytest.raises(VisionError):
        extract_mistake(_png_bytes(), "application/pdf", subject_name="高中数学", llm_client=FakeLLM([]))


def test_extract_mistake_rejects_oversized_image():
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (8 * 1024 * 1024)
    with pytest.raises(VisionError):
        extract_mistake(big, "image/png", subject_name="高中数学", llm_client=FakeLLM([]))


def test_choice_question_requires_two_options():
    bad = dict(GOOD, qtype="单选", options=[{"key": "A", "text": "1"}])
    client = FakeLLM([json.dumps(bad, ensure_ascii=False)] * 3)
    with pytest.raises(VisionError):
        extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)


def test_empty_answer_becomes_none():
    payload = dict(GOOD, my_answer_md=None)
    client = FakeLLM([json.dumps(payload, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.my_answer_md is None


def test_warnings_surface_on_result():
    payload = dict(GOOD, warnings=["作答无法辨认"])
    client = FakeLLM([json.dumps(payload, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.warnings == ["作答无法辨认"]
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_vision.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.ai.vision'`

- [ ] **Step 4: 写实现**

`backend/app/ai/vision/mistake_ocr.py`：

```python
"""S4-2 拍照错题识别：一张图 → 结构化的一道题（spec §5.2）。

学生作答宁可为 null 也不猜（spec D-14）：错因诊断（S4-3）会把
my_answer_md 当证据，编造的作答会直接污染诊断结论。
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.ai.extract.question_extractor import ExtractedOption
from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client

SCENE = "mistake_ocr"
PROMPT_FILE = "mistake_ocr_v1.md"
MAX_RETRIES = 2
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_ENV = Environment(loader=FileSystemLoader(_PROMPTS_DIR), undefined=StrictUndefined, autoescape=False)


class VisionError(Exception):
    """识别失败：mime 不支持、超限、JSON 非法、字段非法。"""


class VisionExtract(BaseModel):
    stem_md: str = Field(min_length=5)
    options: list[ExtractedOption] | None = None
    qtype: Literal["单选", "多选", "填空", "解答"]
    correct_answer_md: str | None = None
    my_answer_md: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_shape(self) -> "VisionExtract":
        if self.qtype in {"单选", "多选"}:
            options = self.options or []
            if len(options) < 2:
                raise ValueError("选择题至少需要 2 个选项")
            keys = [option.key for option in options]
            if len(set(keys)) != len(keys):
                raise ValueError("选项 key 重复")
        elif self.options:
            raise ValueError("填空/解答题不应有选项")
        return self


def render_prompt(*, subject_name: str) -> str:
    template = _ENV.get_template(PROMPT_FILE)
    return template.render(subject_name=subject_name)


def extract_mistake(
    image_bytes: bytes,
    mime: str,
    *,
    subject_name: str,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> VisionExtract:
    if mime not in ALLOWED_MIMES:
        raise VisionError(f"不支持的图片类型：{mime}")
    if not image_bytes:
        raise VisionError("图片为空")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise VisionError("图片超过 8MB，请压缩后重试")

    client = llm_client or get_llm_client()
    data_url = f"data:{mime};base64," + base64.b64encode(image_bytes).decode()
    messages = [
        LLMMessage(role="user", content=render_prompt(subject_name=subject_name), images=(data_url,))
    ]

    last_error: Exception | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        response = client.chat(messages, temperature=0.0, max_tokens=1500, scene=SCENE)
        try:
            payload = loads_json_object(response.text)
            return VisionExtract.model_validate(payload)
        except (ValidationError, ValueError) as exc:
            last_error = exc
    raise VisionError(f"识别失败（已尝试 {attempts} 次）：{last_error}")
```

`backend/app/ai/vision/__init__.py`：

```python
"""S4-2 视觉门面：业务层只 import 这里。"""
from app.ai.vision.mistake_ocr import VisionError, VisionExtract, extract_mistake

__all__ = ["VisionError", "VisionExtract", "extract_mistake"]
```

> `get_llm_client()` 的模型名来自 `Settings.llm_model`（文本模型）。**识别必须用视觉模型**：在 `mistake_ocr.py` 里改为
> `client = llm_client or OpenAICompatLLMClient(...)` 不划算——直接在 `app/ai/llm/__init__.py` 加一个
> `get_vision_client()` 工厂（`model=get_settings().vision_model`），本任务一并加，并在测试里断言 `extract_mistake`
> 在未注入 client 时调用的是 `get_vision_client`。

- [ ] **Step 5: 加 `get_vision_client()` 工厂**

`backend/app/ai/llm/__init__.py` 追加（与 `get_llm_client` 并列，走同一 key/base_url，仅模型不同）：

```python
def get_vision_client() -> LLMClient:
    """S4-2：视觉模型与文本模型是不同能力，模型名分开放配置。"""
    settings = get_settings()
    return OpenAICompatibleLLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.vision_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        price_input_per_million=settings.llm_price_input_per_million,
        price_output_per_million=settings.llm_price_output_per_million,
        log_calls=True,
    )
```

（与现有 `get_llm_client()` 逐项一致，**只有 `model` 换成 `settings.vision_model`**；类名是 `OpenAICompatibleLLMClient`，不是 `OpenAICompatLLMClient`。Task 3 测试里的 `_client()` 也要用这个名字。）`mistake_ocr.py` 里 `client = llm_client or get_vision_client()`，并把 `get_vision_client` 加进 `__all__`。

- [ ] **Step 6: 跑测试确认通过**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_mistake_vision.py -q`
Expected: `8 passed`

- [ ] **Step 7: 全量回归**

Run: `..\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿（应为 877 passed 左右：865 + 4 + 8）

- [ ] **Step 8: Commit**

```bash
git add backend/app/ai/prompts/mistake_ocr_v1.md backend/app/ai/vision \
        backend/app/ai/llm/__init__.py backend/tests/test_mistake_vision.py
git commit -m "feat(s4-2): 拍照错题识别器（单图严格 JSON + 2 次重试 + 视觉模型工厂）"
```

---

### Task 5: 服务层骨架 + 录入 / 详情 / 更新

**Files:**
- Create: `backend/app/schemas/mistake.py`
- Create: `backend/app/services/mistake_service.py`
- Test: `backend/tests/test_mistake_service.py`

**Interfaces:**
- Consumes: `Mistake`/`MistakeAnalysis`（Task 2）、`Question`、`QuestionKp`、`KnowledgePoint`、`NotFoundError`/`InvalidParamError`、`MISTAKE_STATUSES`
- Produces（后续 task 全部依赖这些名字）：
  - `TASK_MISTAKE_RECOGNIZE = "mistake.recognize"`、`MASTERY_STREAK = 2`、`LOW_CONFIDENCE = 0.5`
  - `MistakeFilters(status, cause_type, kp_id, created_from, created_to)`
  - `_load_owned(session, *, user_id: int, mistake_id: int) -> Mistake`
  - `_detail(session, *, mistake: Mistake) -> MistakeDetailOut`
  - `create_from_question(session, *, user_id: int, payload: MistakeCreateIn) -> tuple[MistakeDetailOut, bool]`
  - `update_mistake(session, *, user_id: int, mistake_id: int, payload: MistakeUpdateIn) -> MistakeDetailOut`
  - `_commit(session) -> None`

- [ ] **Step 1: 写出入参模型**

`backend/app/schemas/mistake.py`：

```python
"""S4-2 错题出入参（API.md §5.6）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import MISTAKE_STATUSES, CauseType, MistakeStatus

StatusLiteral = Literal["待订正", "已订正", "已掌握"]


class MistakeCreateIn(BaseModel):
    question_id: int = Field(gt=0)
    my_answer_md: str | None = None
    correct_answer_md: str | None = None


class MistakeUpdateIn(BaseModel):
    my_answer_md: str | None = None
    correct_answer_md: str | None = None
    status: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_null_status(cls, data: object) -> object:
        # status 是 NOT NULL 列：显式传 null 与「不传」必须区分开，
        # 否则会把 500（DB 约束）暴露给前端。与 S4-1 PATCH 的 I1 口径一致。
        if isinstance(data, dict) and "status" in data and data["status"] is None:
            raise ValueError("status 不能为 null")
        return data

    @model_validator(mode="after")
    def _validate_status_value(self) -> "MistakeUpdateIn":
        if self.status is not None and self.status not in MISTAKE_STATUSES:
            options = "、".join(MISTAKE_STATUSES)
            raise ValueError(f"非法的错题状态：{self.status}（可选：{options}）")
        return self


class MistakeReviewIn(BaseModel):
    correct: bool


class OptionOut(BaseModel):
    key: str
    text: str


class MistakeAnalysisOut(BaseModel):
    cause_type: str
    error_step: str | None = None
    explanation_md: str | None = None
    review_advice_md: str | None = None
    kp_ids: list[int] | None = None
    created_at: datetime


class MistakeSummaryOut(BaseModel):
    id: int
    question_id: int
    status: str
    correct_streak: int
    stem_excerpt: str
    subject_id: int
    qtype: str
    difficulty: int
    kp_names: list[str] = Field(default_factory=list)
    cause_type: str | None = None
    has_image: bool = False
    created_at: datetime
    last_review_at: datetime | None = None


class MistakeDetailOut(MistakeSummaryOut):
    stem_md: str
    options: list[OptionOut] | None = None
    my_answer_md: str | None = None
    correct_answer_md: str | None = None
    image_url: str | None = None
    analysis: MistakeAnalysisOut | None = None


class MistakeCreateOut(MistakeDetailOut):
    created: bool


class StatusCountOut(BaseModel):
    status: str
    count: int


class CauseCountOut(BaseModel):
    cause_type: str
    count: int


class KpCountOut(BaseModel):
    kp_id: int
    kp_name: str
    count: int


class MistakeStatsOut(BaseModel):
    total: int
    by_status: list[StatusCountOut]
    by_cause: list[CauseCountOut]
    top_kps: list[KpCountOut]
```

- [ ] **Step 2: 写失败测试（含 FakeSession）**

`backend/tests/test_mistake_service.py` 顶部（**照 S4-1 `tests/test_question_service.py` 的 FakeSession 仿写**，额外加 `execute` 供 Task 6 的统计用）：

```python
"""S4-2 错题服务：录入幂等、状态机、权限隔离、筛选 SQL、统计。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.enums import MistakeStatus
from app.models.mistake import Mistake
from app.models.question import Question
from app.schemas.mistake import MistakeCreateIn, MistakeUpdateIn
from app.services import mistake_service


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None, scalars_results=None, rows_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.rows_results = list(rows_results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.scalar_statements: list[object] = []
        self.execute_statements: list[object] = []
        self._next_id = 500

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return self.scalars_results.pop(0) if self.scalars_results else []

    def execute(self, statement):
        self.execute_statements.append(statement)
        return _Rows(self.rows_results.pop(0) if self.rows_results else [])

    def add(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            self._next_id += 1
            instance.id = self._next_id
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def delete(self, instance) -> None:
        self.deleted.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _question(question_id: int = 65, *, answer: str | None = "B") -> Question:
    question = Question(
        subject_id=7, stem_md="已知函数 $f(x)=x^2-4x+3$", stem_hash="h1", qtype="解答",
        difficulty=2, origin="upload", answer_md=answer, verified=True,
    )
    question.id = question_id
    return question


def _mistake(mistake_id: int = 12, *, user_id: int = 1, status: str = "待订正", streak: int = 0) -> Mistake:
    mistake = Mistake(
        user_id=user_id, question_id=65, status=status, correct_streak=streak,
        created_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    mistake.id = mistake_id
    return mistake


def test_create_from_question_new_row_uses_question_answer():
    question = _question()
    session = FakeSession(objects={(Question, 65): question}, scalar_results=[None])
    detail, created = mistake_service.create_from_question(
        session, user_id=1, payload=MistakeCreateIn(question_id=65)
    )
    assert created is True
    assert session.commits == 1
    saved = session.added[0]
    assert isinstance(saved, Mistake)
    assert saved.correct_answer_md == "B"
    assert saved.status == MistakeStatus.TODO.value
    assert detail.question_id == 65


def test_create_from_question_reuses_existing_and_resets():
    existing = _mistake(status="已掌握", streak=2)
    session = FakeSession(
        objects={(Question, 65): _question(), (Mistake, 12): existing}, scalar_results=[existing]
    )
    detail, created = mistake_service.create_from_question(
        session, user_id=1, payload=MistakeCreateIn(question_id=65, my_answer_md="我又错了")
    )
    assert created is False
    assert existing.status == MistakeStatus.TODO.value
    assert existing.correct_streak == 0
    assert existing.last_review_at is not None
    assert existing.my_answer_md == "我又错了"
    assert session.commits == 1


def test_create_from_question_missing_question_raises_404():
    session = FakeSession(objects={})
    with pytest.raises(NotFoundError):
        mistake_service.create_from_question(session, user_id=1, payload=MistakeCreateIn(question_id=404))


def test_get_detail_other_user_raises_404():
    session = FakeSession(objects={(Mistake, 12): _mistake(user_id=2)})
    with pytest.raises(NotFoundError):
        mistake_service.get_detail(session, user_id=1, mistake_id=12)


def test_update_mistake_rejects_null_status():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MistakeUpdateIn(status=None)


def test_update_mistake_rejects_unknown_status():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MistakeUpdateIn(status="已通关")


def test_update_mistake_changes_answer_only():
    mistake = _mistake()
    session = FakeSession(
        objects={(Mistake, 12): mistake},
        scalars_results=[[], []],  # kp 名 + cause 各一次（_detail 内部）
    )
    mistake_service.update_mistake(
        session, user_id=1, mistake_id=12, payload=MistakeUpdateIn(my_answer_md="x=2")
    )
    assert mistake.my_answer_md == "x=2"
    assert mistake.status == MistakeStatus.TODO.value
    assert session.commits == 1
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_service.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.mistake_service'`

- [ ] **Step 4: 写服务骨架（`_load_owned` / `_detail` / `_commit` / `create_from_question` / `get_detail` / `update_mistake`）**

`backend/app/services/mistake_service.py`（本任务先写这些；Task 6/7 继续往里加）：

```python
"""S4-2 错题服务：唯一业务入口（spec §6）。

错题是学生私有数据，所有查询显式带 user_id；他人记录一律 404，
不泄露存在性（spec D-8）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.enums import MistakeStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.schemas.mistake import (
    MistakeAnalysisOut,
    MistakeCreateIn,
    MistakeDetailOut,
    MistakeSummaryOut,
    MistakeUpdateIn,
    OptionOut,
)

TASK_MISTAKE_RECOGNIZE = "mistake.recognize"
MASTERY_STREAK = 2
LOW_CONFIDENCE = 0.5
EXCERPT_LEN = 120


@dataclass(frozen=True)
class MistakeFilters:
    status: str | None = None
    cause_type: str | None = None
    kp_id: int | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _load_owned(session: Session, *, user_id: int, mistake_id: int) -> Mistake:
    mistake = session.get(Mistake, mistake_id)
    if mistake is None or mistake.user_id != user_id:
        raise NotFoundError("错题不存在")
    return mistake


def _kp_names(session: Session, question_id: int) -> list[str]:
    rows = session.scalars(
        select(KnowledgePoint.name)
        .join(QuestionKp, QuestionKp.kp_id == KnowledgePoint.id)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc())
    )
    return list(rows)


def _analysis_of(session: Session, mistake_id: int) -> MistakeAnalysisOut | None:
    analysis = session.scalar(
        select(MistakeAnalysis).where(MistakeAnalysis.mistake_id == mistake_id)
    )
    if analysis is None:
        return None
    return MistakeAnalysisOut(
        cause_type=analysis.cause_type,
        error_step=analysis.error_step,
        explanation_md=analysis.explanation_md,
        review_advice_md=analysis.review_advice_md,
        kp_ids=analysis.kp_ids,
        created_at=analysis.created_at,
    )


def _detail(session: Session, *, mistake: Mistake) -> MistakeDetailOut:
    question = session.get(Question, mistake.question_id)
    if question is None:
        raise NotFoundError("错题关联的题目不存在")
    options = (
        [OptionOut(**item) for item in question.options_json] if question.options_json else None
    )
    return MistakeDetailOut(
        id=mistake.id,
        question_id=mistake.question_id,
        status=mistake.status,
        correct_streak=mistake.correct_streak,
        stem_excerpt=question.stem_md[:EXCERPT_LEN],
        subject_id=question.subject_id,
        qtype=question.qtype,
        difficulty=question.difficulty,
        kp_names=_kp_names(session, mistake.question_id),
        cause_type=(analysis.cause_type if (analysis := _analysis_of(session, mistake.id)) else None),
        has_image=mistake.image_file_id is not None,
        created_at=mistake.created_at,
        last_review_at=mistake.last_review_at,
        stem_md=question.stem_md,
        options=options,
        my_answer_md=mistake.my_answer_md,
        correct_answer_md=mistake.correct_answer_md,
        image_url=(
            f"/api/v1/files/{mistake.image_file_id}/image" if mistake.image_file_id else None
        ),
        analysis=analysis,
    )


def create_from_question(
    session: Session, *, user_id: int, payload: MistakeCreateIn
) -> tuple[MistakeDetailOut, bool]:
    """题库选题录入。同 (user, question) 已存在时复用并重置（spec D-1）。"""
    question = session.get(Question, payload.question_id)
    if question is None:
        raise NotFoundError("题目不存在")
    existing = session.scalar(
        select(Mistake).where(
            Mistake.user_id == user_id, Mistake.question_id == payload.question_id
        )
    )
    answer = payload.correct_answer_md if payload.correct_answer_md is not None else question.answer_md
    if existing is not None:
        existing.status = MistakeStatus.TODO.value
        existing.correct_streak = 0
        existing.last_review_at = datetime.now(timezone.utc)
        if payload.my_answer_md is not None:
            existing.my_answer_md = payload.my_answer_md
        if answer is not None:
            existing.correct_answer_md = answer
        mistake, created = existing, False
    else:
        mistake = Mistake(
            user_id=user_id,
            question_id=payload.question_id,
            my_answer_md=payload.my_answer_md,
            correct_answer_md=answer,
            status=MistakeStatus.TODO.value,
            correct_streak=0,
        )
        session.add(mistake)
        created = True
    _commit(session)
    return _detail(session, mistake=mistake), created


def get_detail(session: Session, *, user_id: int, mistake_id: int) -> MistakeDetailOut:
    return _detail(session, mistake=_load_owned(session, user_id=user_id, mistake_id=mistake_id))


def update_mistake(
    session: Session, *, user_id: int, mistake_id: int, payload: MistakeUpdateIn
) -> MistakeDetailOut:
    mistake = _load_owned(session, user_id=user_id, mistake_id=mistake_id)
    if payload.my_answer_md is not None:
        mistake.my_answer_md = payload.my_answer_md
    if payload.correct_answer_md is not None:
        mistake.correct_answer_md = payload.correct_answer_md
    if payload.status is not None:
        mistake.status = payload.status
    _commit(session)
    return _detail(session, mistake=mistake)
```

> `Question.options_json` 的字段名以 `app/models/question.py` 实际为准（S4-1 里是 `options_json`），存的形状是 `[{"key": "...", "text": "..."}]`。

- [ ] **Step 5: 跑测试确认通过**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_mistake_service.py -q`
Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/mistake.py backend/app/services/mistake_service.py backend/tests/test_mistake_service.py
git commit -m "feat(s4-2): 错题服务骨架与题库选题录入（重复录入复用重置）"
```

---

### Task 6: 状态机、删除、统计

**Files:**
- Modify: `backend/app/services/mistake_service.py`（追加 `record_review` / `delete_mistake` / `stats`）
- Modify: `backend/tests/test_mistake_service.py`（追加用例）

**Interfaces:**
- Consumes: Task 5 的 `_load_owned` / `_detail` / `_commit` / `MASTERY_STREAK`
- Produces:
  - `record_review(session, *, user_id: int, mistake_id: int, correct: bool) -> MistakeDetailOut`
  - `delete_mistake(session, *, user_id: int, mistake_id: int) -> None`
  - `stats(session, *, user_id: int, created_from: datetime | None = None, created_to: datetime | None = None) -> MistakeStatsOut`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_mistake_service.py`：

```python
def test_record_review_first_correct_marks_corrected():
    mistake = _mistake()
    session = FakeSession(objects={(Question, 65): _question(), (Mistake, 12): mistake},
                          scalar_results=[None], scalars_results=[[]])
    detail = mistake_service.record_review(session, user_id=1, mistake_id=12, correct=True)
    assert mistake.correct_streak == 1
    assert mistake.status == MistakeStatus.CORRECTED.value
    assert mistake.last_review_at is not None
    assert detail.correct_streak == 1


def test_record_review_second_correct_marks_mastered():
    mistake = _mistake(status="已订正", streak=1)
    session = FakeSession(objects={(Question, 65): _question(), (Mistake, 12): mistake},
                          scalar_results=[None], scalars_results=[[]])
    mistake_service.record_review(session, user_id=1, mistake_id=12, correct=True)
    assert mistake.correct_streak == 2
    assert mistake.status == MistakeStatus.MASTERED.value


def test_record_review_wrong_resets_to_todo():
    mistake = _mistake(status="已掌握", streak=2)
    session = FakeSession(objects={(Question, 65): _question(), (Mistake, 12): mistake},
                          scalar_results=[None], scalars_results=[[]])
    mistake_service.record_review(session, user_id=1, mistake_id=12, correct=False)
    assert mistake.correct_streak == 0
    assert mistake.status == MistakeStatus.TODO.value


def test_record_review_other_user_raises_404():
    session = FakeSession(objects={(Mistake, 12): _mistake(user_id=2)})
    with pytest.raises(NotFoundError):
        mistake_service.record_review(session, user_id=1, mistake_id=12, correct=True)


def test_delete_mistake_removes_analysis_too():
    mistake = _mistake()
    session = FakeSession(objects={(Mistake, 12): mistake}, scalar_results=[None])
    mistake_service.delete_mistake(session, user_id=1, mistake_id=12)
    assert mistake in session.deleted
    assert session.commits == 1


def test_stats_fills_zero_for_missing_statuses():
    session = FakeSession(
        rows_results=[
            [("已订正", 2)],                       # by_status
            [("计算失误", 1)],                     # by_cause
            [(137, "函数的单调性", 3)],            # top_kps
        ]
    )
    result = mistake_service.stats(session, user_id=1)
    assert result.total == 2
    assert {item.status: item.count for item in result.by_status} == {
        "待订正": 0, "已订正": 2, "已掌握": 0,
    }
    assert result.by_cause[0].cause_type == "计算失误"
    assert result.top_kps[0].kp_name == "函数的单调性"


def test_stats_queries_always_filter_owner():
    session = FakeSession(rows_results=[[], [], []])
    mistake_service.stats(session, user_id=7)
    for statement in session.execute_statements:
        assert "user_id" in str(statement.compile(compile_kwargs={"literal_binds": False}))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_service.py -q`
Expected: FAIL —— `AttributeError: module 'app.services.mistake_service' has no attribute 'record_review'`

- [ ] **Step 3: 实现三个函数**

追加到 `backend/app/services/mistake_service.py`：

```python
def record_review(
    session: Session, *, user_id: int, mistake_id: int, correct: bool
) -> MistakeDetailOut:
    """复习结果驱动状态机（spec §6.1）：连续答对 MASTERY_STREAK 次算掌握。"""
    mistake = _load_owned(session, user_id=user_id, mistake_id=mistake_id)
    if correct:
        mistake.correct_streak += 1
        mistake.status = (
            MistakeStatus.MASTERED.value
            if mistake.correct_streak >= MASTERY_STREAK
            else MistakeStatus.CORRECTED.value
        )
    else:
        mistake.correct_streak = 0
        mistake.status = MistakeStatus.TODO.value
    mistake.last_review_at = datetime.now(timezone.utc)
    _commit(session)
    return _detail(session, mistake=mistake)


def delete_mistake(session: Session, *, user_id: int, mistake_id: int) -> None:
    """硬删；诊断行同事务删掉，不留孤儿（spec D-12）。"""
    mistake = _load_owned(session, user_id=user_id, mistake_id=mistake_id)
    analysis = session.scalar(
        select(MistakeAnalysis).where(MistakeAnalysis.mistake_id == mistake_id)
    )
    if analysis is not None:
        session.delete(analysis)
        session.flush()
    session.delete(mistake)
    _commit(session)


def stats(
    session: Session,
    *,
    user_id: int,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> MistakeStatsOut:
    """三个维度的 SQL 聚合（spec D-10）；缺的状态补 0，前端不用自己做占位。"""
    base_where = [Mistake.user_id == user_id]
    if created_from is not None:
        base_where.append(Mistake.created_at >= created_from)
    if created_to is not None:
        base_where.append(Mistake.created_at <= created_to)

    status_rows = session.execute(
        select(Mistake.status, func.count()).where(*base_where).group_by(Mistake.status)
    ).all()
    counts = {status: int(count) for status, count in status_rows}
    by_status = [
        StatusCountOut(status=status, count=counts.get(status, 0))
        for status in MISTAKE_STATUSES
    ]

    cause_rows = session.execute(
        select(MistakeAnalysis.cause_type, func.count())
        .join(Mistake, Mistake.id == MistakeAnalysis.mistake_id)
        .where(*base_where)
        .group_by(MistakeAnalysis.cause_type)
    ).all()
    by_cause = [CauseCountOut(cause_type=cause, count=int(count)) for cause, count in cause_rows]

    kp_rows = session.execute(
        select(QuestionKp.kp_id, KnowledgePoint.name, func.count())
        .join(Mistake, Mistake.question_id == QuestionKp.question_id)
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKp.kp_id)
        .where(*base_where)
        .group_by(QuestionKp.kp_id, KnowledgePoint.name)
        .order_by(func.count().desc(), QuestionKp.kp_id)
        .limit(10)
    ).all()
    top_kps = [
        KpCountOut(kp_id=kp_id, kp_name=name, count=int(count)) for kp_id, name, count in kp_rows
    ]

    return MistakeStatsOut(
        total=sum(item.count for item in by_status),
        by_status=by_status,
        by_cause=by_cause,
        top_kps=top_kps,
    )
```

同时补 import：

```python
from sqlalchemy import Select, func, select
from app.models.enums import CAUSE_TYPES, MISTAKE_STATUSES, MistakeStatus
from app.schemas.mistake import (
    CauseCountOut,
    KpCountOut,
    MistakeStatsOut,
    StatusCountOut,
)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_mistake_service.py -q`
Expected: `14 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/mistake_service.py backend/tests/test_mistake_service.py
git commit -m "feat(s4-2): 错题状态机（连续答对 2 次自动掌握）、删除与统计聚合"
```

---

### Task 7: 列表查询与筛选

**Files:**
- Modify: `backend/app/services/mistake_service.py`（追加 `build_mistakes_query` / `list_mistakes`）
- Modify: `backend/tests/test_mistake_service.py`（追加 SQL 与分页用例）

**Interfaces:**
- Consumes: `apply_sort`、`paginate_sa`、`Params`、`PageData`、Task 5 的 `MistakeFilters`
- Produces:
  - `SORTABLE: dict[str, object]`（`created_at` / `last_review_at` / `status` / `correct_streak`）
  - `build_mistakes_query(*, user_id: int, filters: MistakeFilters) -> Select`
  - `list_mistakes(session, *, user_id: int, filters: MistakeFilters, page: PageParams, sort: SortParams) -> PageData[MistakeSummaryOut]`

- [ ] **Step 1: 写失败测试**

```python
def _compiled(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": False}))


def test_build_query_always_filters_owner():
    stmt = mistake_service.build_mistakes_query(user_id=7, filters=mistake_service.MistakeFilters())
    assert "mistakes.user_id" in _compiled(stmt)


def test_build_query_cause_filter_uses_exists_not_join():
    stmt = mistake_service.build_mistakes_query(
        user_id=1, filters=mistake_service.MistakeFilters(cause_type="计算失误")
    )
    sql = _compiled(stmt)
    assert "EXISTS" in sql.upper()
    assert "JOIN mistake_analyses" not in sql


def test_build_query_kp_filter_uses_exists():
    stmt = mistake_service.build_mistakes_query(
        user_id=1, filters=mistake_service.MistakeFilters(kp_id=137)
    )
    sql = _compiled(stmt)
    assert "EXISTS" in sql.upper()
    assert "question_kps" in sql


def test_build_query_date_range_bounds():
    session_from = datetime(2026, 11, 1, tzinfo=timezone.utc)
    session_to = datetime(2026, 11, 30, tzinfo=timezone.utc)
    stmt = mistake_service.build_mistakes_query(
        user_id=1,
        filters=mistake_service.MistakeFilters(created_from=session_from, created_to=session_to),
    )
    sql = _compiled(stmt)
    assert sql.count("mistakes.created_at") == 2


def test_list_mistakes_rejects_unknown_sort_field():
    session = FakeSession()
    with pytest.raises(InvalidParamError):
        mistake_service.list_mistakes(
            session, user_id=1, filters=mistake_service.MistakeFilters(),
            page=PageParams(page=1, page_size=20), sort=SortParams(sort_by="hack", order="desc"),
        )


def test_list_mistakes_returns_rows_with_kp_names(monkeypatch):
    mistake = _mistake()
    question = _question()
    monkeypatch.setattr(
        mistake_service, "paginate_sa",
        lambda session, stmt, params: type(
            "Page", (), {"items": [(mistake, question)], "total": 1, "page": 1, "size": 20}
        )(),
    )
    session = FakeSession(scalars_results=[["函数的单调性"]], scalar_results=[None])
    data = mistake_service.list_mistakes(
        session, user_id=1, filters=mistake_service.MistakeFilters(),
        page=PageParams(page=1, page_size=20), sort=SortParams(),
    )
    assert data.total == 1
    assert data.items[0].kp_names == ["函数的单调性"]
    assert data.items[0].stem_excerpt.startswith("已知函数")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_service.py -q`
Expected: FAIL —— `AttributeError: ... has no attribute 'build_mistakes_query'`

- [ ] **Step 3: 实现查询与列表**

追加到 `backend/app/services/mistake_service.py`：

```python
SORTABLE: dict[str, object] = {
    "created_at": Mistake.created_at,
    "last_review_at": Mistake.last_review_at,
    "status": Mistake.status,
    "correct_streak": Mistake.correct_streak,
}


def build_mistakes_query(*, user_id: int, filters: MistakeFilters) -> Select:
    """错题列表查询。

    cause_type / kp_id 都用 EXISTS：JOIN 会在一条错题命中多个知识点时
    产生重复行，分页与 count 一起失真（与 S4-1 build_questions_query 同因）。
    """
    stmt = (
        select(Mistake, Question)
        .join(Question, Question.id == Mistake.question_id)
        .where(Mistake.user_id == user_id)
    )
    if filters.status:
        stmt = stmt.where(Mistake.status == filters.status)
    if filters.cause_type:
        stmt = stmt.where(
            exists().where(
                MistakeAnalysis.mistake_id == Mistake.id,
                MistakeAnalysis.cause_type == filters.cause_type,
            )
        )
    if filters.kp_id is not None:
        stmt = stmt.where(
            exists().where(QuestionKp.question_id == Mistake.question_id,
                           QuestionKp.kp_id == filters.kp_id)
            | exists().where(MistakeAnalysis.mistake_id == Mistake.id,
                             MistakeAnalysis.kp_ids.contains([filters.kp_id]))
        )
    if filters.created_from is not None:
        stmt = stmt.where(Mistake.created_at >= filters.created_from)
    if filters.created_to is not None:
        stmt = stmt.where(Mistake.created_at <= filters.created_to)
    return stmt


def list_mistakes(
    session: Session,
    *,
    user_id: int,
    filters: MistakeFilters,
    page: PageParams,
    sort: SortParams,
) -> PageData[MistakeSummaryOut]:
    stmt = apply_sort(
        build_mistakes_query(user_id=user_id, filters=filters),
        sort_by=sort.sort_by,
        order=sort.order,
        allowed=SORTABLE,
        default_sort="created_at",
    )
    # 同一秒录入的错题没有唯一 tiebreaker 时翻页会重复/漏行（S4-1 踩过）。
    stmt = stmt.order_by(Mistake.id.desc())
    result = paginate_sa(session, stmt, params=Params(page=page.page, size=page.page_size))
    items: list[MistakeSummaryOut] = []
    for mistake, question in result.items:
        analysis = _analysis_of(session, mistake.id)
        items.append(
            MistakeSummaryOut(
                id=mistake.id,
                question_id=mistake.question_id,
                status=mistake.status,
                correct_streak=mistake.correct_streak,
                stem_excerpt=question.stem_md[:EXCERPT_LEN],
                subject_id=question.subject_id,
                qtype=question.qtype,
                difficulty=question.difficulty,
                kp_names=_kp_names(session, question.id),
                cause_type=(analysis.cause_type if analysis else None),
                has_image=mistake.image_file_id is not None,
                created_at=mistake.created_at,
                last_review_at=mistake.last_review_at,
            )
        )
    return PageData(
        items=items, total=result.total, page=result.page, page_size=result.size
    )
```

补 import：

```python
from fastapi_pagination import Params
from fastapi_pagination.ext.sqlalchemy import paginate as paginate_sa
from sqlalchemy import Select, exists, func, select

from app.schemas.common import PageData
from app.utils.pagination import PageParams, SortParams, apply_sort
```

- [ ] **Step 4: 跑测试确认通过**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_mistake_service.py -q`
Expected: `20 passed`

- [ ] **Step 5: 全量回归 + Commit**

Run: `..\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿

```bash
git add backend/app/services/mistake_service.py backend/tests/test_mistake_service.py
git commit -m "feat(s4-2): 错题列表筛选（错因/知识点 EXISTS）与排序分页"
```

---

### Task 8: 异步任务 `mistake.recognize`

**Files:**
- Create: `backend/app/tasks/mistake_recognize.py`
- Modify: `backend/app/tasks/__init__.py`（注册副作用 import）
- Modify: `backend/app/services/mistake_service.py`（加 `start_photo_recognize` 与 `task_create_mistake`）
- Test: `backend/tests/test_mistake_task.py`

**Interfaces:**
- Consumes: `file_service.upload_file`（路由侧）、`task_service.create_task`、`ai.vision.extract_mistake`、`question_service.create_extracted_question(session, *, extracted, subject_id, origin, created_by, source_file_id, vec) -> tuple[Question, bool]`、`get_embedding_client()`、`get_storage()`
- Produces:
  - `start_photo_recognize(session, *, owner: User, subject_id: int, upload: UploadFile, storage: ObjectStorage, queue: TaskQueue) -> AsyncTask`
  - `task_create_mistake(session, *, user_id: int, question_id: int, my_answer_md: str | None, correct_answer_md: str | None, image_file_id: int | None) -> tuple[Mistake, bool]`（**不 commit**，任务内用）
  - `tasks/mistake_recognize.py::mistake_recognize_task(session, payload) -> dict`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_mistake_task.py`：

```python
"""S4-2 拍照错题任务：建题→建错题、复用、作答优先级、失败不吞、不 commit。"""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from app.ai.vision import VisionExtract
from app.models.mistake import Mistake
from app.models.question import Question
from app.services import mistake_service
from app.tasks import mistake_recognize as task_module


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.added: list[object] = []
        self.commits = 0

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        return self.scalar_results.pop(0) if self.scalar_results else None

    def add(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 900
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


class FakeStorage:
    def download_to(self, key: str, target: BytesIO) -> None:
        target.write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)


class FakeFile:
    def __init__(self) -> None:
        self.id = 41
        self.user_id = 1
        self.mime = "image/png"
        self.filename = "photo.png"
        self.storage_path = "obj/41"


class FakeEmbedder:
    dim = 2
    model = "fake-embed"

    def encode(self, texts, *, on_batch=None):
        return [[0.1, 0.9] for _ in texts]


def _vision(**overrides) -> VisionExtract:
    payload = {
        "stem_md": "已知函数 $f(x)=x^{2}-4x+3$，求对称轴。",
        "options": None,
        "qtype": "解答",
        "correct_answer_md": None,
        "my_answer_md": "对称轴 x=2",
        "confidence": 0.9,
        "warnings": [],
    }
    payload.update(overrides)
    return VisionExtract.model_validate(payload)


@pytest.fixture()
def patched(monkeypatch):
    calls = {}

    def fake_extract(image_bytes, mime, *, subject_name, llm_client=None):
        calls["subject_name"] = subject_name
        calls["mime"] = mime
        return _vision()

    def fake_create_extracted(session, *, extracted, subject_id, origin, created_by,
                             source_file_id, vec):
        calls["extracted_stem"] = extracted.stem_md
        calls["origin"] = origin
        calls["source_file_id"] = source_file_id
        question = Question(
            subject_id=subject_id, stem_md=extracted.stem_md, stem_hash="h-photo",
            qtype=extracted.qtype, difficulty=extracted.difficulty, origin=origin,
            answer_md=extracted.answer_md, verified=True,
        )
        question.id = 65
        return question, False

    monkeypatch.setattr(task_module, "extract_mistake", fake_extract)
    monkeypatch.setattr(task_module.question_service, "create_extracted_question", fake_create_extracted)
    monkeypatch.setattr(task_module, "get_embedding_client", lambda: FakeEmbedder())
    monkeypatch.setattr(task_module, "get_storage", lambda: FakeStorage())
    return calls


def _payload(**overrides) -> dict:
    payload = {"file_id": 41, "subject_id": 7, "user_id": 1, "my_answer_md": None}
    payload.update(overrides)
    return payload


def test_task_creates_question_and_mistake(patched):
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])
    result = task_module.mistake_recognize_task(session, _payload())
    assert result["question_id"] == 65
    assert result["created"] is True
    assert result["reused_question"] is False
    assert result["low_confidence"] is False
    assert session.commits == 0  # handler 不 commit（runner 统一提交）
    assert patched["origin"] == "upload"
    assert patched["source_file_id"] == 41
    assert isinstance(session.added[0], Mistake)


def test_task_prefers_student_answer_over_vision(patched):
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])
    result = task_module.mistake_recognize_task(session, _payload(my_answer_md="我自己写的"))
    assert result["used_answer_source"] == "student"
    assert session.added[0].my_answer_md == "我自己写的"


def test_task_marks_low_confidence(monkeypatch, patched):
    monkeypatch.setattr(
        task_module, "extract_mistake",
        lambda *a, **kw: _vision(confidence=0.3),
    )
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])
    result = task_module.mistake_recognize_task(session, _payload())
    assert result["low_confidence"] is True


def test_task_rejects_missing_file():
    session = FakeSession(objects={})
    with pytest.raises(Exception):
        task_module.mistake_recognize_task(session, _payload())


def test_task_rejects_foreign_file():
    file = FakeFile()
    file.user_id = 2
    session = FakeSession(objects={(task_module.File, 41): file})
    with pytest.raises(Exception):
        task_module.mistake_recognize_task(session, _payload())


def test_start_photo_recognize_uploads_and_enqueues(monkeypatch):
    captured = {}

    class FakeQueue:
        pass

    def fake_create_task(session, *, owner, name, payload, queue):
        captured.update({"name": name, "payload": payload})
        return type("Task", (), {"id": 98, "name": name, "status": "pending"})()

    monkeypatch.setattr(mistake_service.task_service, "create_task", fake_create_task)
    monkeypatch.setattr(
        mistake_service.file_service, "upload_file",
        lambda session, *, owner, upload, storage, parse: (type("F", (), {"id": 41, "mime": "image/png"})(), False),
    )
    session = FakeSession()
    owner = type("U", (), {"id": 1})()
    task = mistake_service.start_photo_recognize(
        session, owner=owner, subject_id=7, upload=object(), storage=object(), queue=FakeQueue()
    )
    assert captured["name"] == "mistake.recognize"
    assert captured["payload"]["file_id"] == 41
    assert captured["payload"]["user_id"] == 1
    assert task.id == 98
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_mistake_task.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.tasks.mistake_recognize'`

- [ ] **Step 3: 服务侧两个函数**

追加到 `backend/app/services/mistake_service.py`：

```python
def start_photo_recognize(
    session: Session,
    *,
    owner: User,
    subject_id: int,
    upload: UploadFile,
    storage: ObjectStorage,
    queue: TaskQueue,
) -> AsyncTask:
    """拍照录入入口：存图（不解析）→ 入队识别（spec D-5）。"""
    question_service.ensure_subject_exists(session, subject_id)
    record, _ = file_service.upload_file(
        session, owner=owner, upload=upload, storage=storage, parse=False
    )
    if record.mime not in IMAGE_MIMES:
        raise InvalidParamError("只能上传 PNG/JPEG/WebP 图片")
    return task_service.create_task(
        session,
        owner=owner,
        name=TASK_MISTAKE_RECOGNIZE,
        payload={"file_id": record.id, "subject_id": subject_id, "user_id": owner.id,
                 "my_answer_md": None},
        queue=queue,
    )


def task_create_mistake(
    session: Session,
    *,
    user_id: int,
    question_id: int,
    my_answer_md: str | None,
    correct_answer_md: str | None,
    image_file_id: int | None,
) -> tuple[Mistake, bool]:
    """任务内建错题：不 commit（runner 统一提交），复用语义同 create_from_question。"""
    existing = session.scalar(
        select(Mistake).where(Mistake.user_id == user_id, Mistake.question_id == question_id)
    )
    if existing is not None:
        existing.status = MistakeStatus.TODO.value
        existing.correct_streak = 0
        existing.last_review_at = datetime.now(timezone.utc)
        existing.my_answer_md = my_answer_md
        existing.correct_answer_md = correct_answer_md
        if image_file_id is not None:
            existing.image_file_id = image_file_id
        return existing, False
    mistake = Mistake(
        user_id=user_id,
        question_id=question_id,
        my_answer_md=my_answer_md,
        correct_answer_md=correct_answer_md,
        image_file_id=image_file_id,
        status=MistakeStatus.TODO.value,
        correct_streak=0,
    )
    session.add(mistake)
    return mistake, True
```

补常量与 import：

```python
IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
from fastapi import UploadFile
from app.core.storage import ObjectStorage
from app.models.task import AsyncTask   # 以实际类名为准
from app.models.user import User
from app.services import file_service, task_service
from app.tasks.queue import TaskQueue  # 以 api/deps.py 里的类型为准
from app.services import question_service
```

- [ ] **Step 4: 写 handler**

`backend/app/tasks/mistake_recognize.py`：

```python
"""S4-2 拍照错题识别任务（spec §7）。

handler 不 commit：题目与错题由 runner 在同一事务里提交，
识别失败就让整条任务失败、图片仍留在 files（spec D-13）。
"""
from __future__ import annotations

import logging
import time
from io import BytesIO
from typing import Any

from sqlalchemy.orm import Session

from app.ai.embedding import get_embedding_client
from app.ai.extract.question_extractor import ExtractedQuestion
from app.ai.vision import extract_mistake
from app.core.exceptions import ForbiddenError, InvalidParamError
from app.core.storage import get_storage
from app.models.file import File
from app.models.subject import Subject
from app.services import mistake_service, question_service
from app.tasks.registry import register

logger = logging.getLogger(__name__)

TASK_MISTAKE_RECOGNIZE = mistake_service.TASK_MISTAKE_RECOGNIZE


@register(TASK_MISTAKE_RECOGNIZE)
def mistake_recognize_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    file_id = int(payload["file_id"])
    subject_id = int(payload["subject_id"])
    user_id = int(payload["user_id"])
    student_answer = payload.get("my_answer_md")

    file = session.get(File, file_id)
    if file is None:
        raise InvalidParamError("文件不存在")
    if file.user_id != user_id:
        raise ForbiddenError("文件不属于当前用户")

    buffer = BytesIO()
    get_storage().download_to(file.storage_path, buffer)
    extracted_vision = extract_mistake(
        buffer.getvalue(), file.mime, subject_name=_subject_name(session, subject_id)
    )

    extracted = ExtractedQuestion(
        stem_md=extracted_vision.stem_md,
        options=extracted_vision.options,
        answer_md=extracted_vision.correct_answer_md,
        analysis_md=None,
        qtype=extracted_vision.qtype,
        difficulty=3,
        kp_names=[],
        answer_source="paper" if extracted_vision.correct_answer_md else "none",
    )
    vec = get_embedding_client().encode([question_service.embedding_text(extracted.stem_md)])[0]
    question, reused = question_service.create_extracted_question(
        session,
        extracted=extracted,
        subject_id=subject_id,
        origin="upload",
        created_by=user_id,
        source_file_id=file_id,
        vec=vec,
    )

    if student_answer:
        my_answer, source = student_answer, "student"
    elif extracted_vision.my_answer_md:
        my_answer, source = extracted_vision.my_answer_md, "vision"
    else:
        my_answer, source = None, "none"

    mistake, created = mistake_service.task_create_mistake(
        session,
        user_id=user_id,
        question_id=question.id,
        my_answer_md=my_answer,
        correct_answer_md=extracted_vision.correct_answer_md or question.answer_md,
        image_file_id=file_id,
    )
    return {
        "mistake_id": mistake.id,
        "question_id": question.id,
        "created": created,
        "reused_question": reused,
        "confidence": extracted_vision.confidence,
        "low_confidence": extracted_vision.confidence < mistake_service.LOW_CONFIDENCE,
        "used_answer_source": source,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _subject_name(session: Session, subject_id: int) -> str:
    subject = session.get(Subject, subject_id)
    if subject is None:
        logger.warning("mistake_recognize_subject_missing", extra={"subject_id": subject_id})
        return "高中数学"
    return subject.name
```

`backend/app/tasks/__init__.py` 追加（照 `question_extract` 的注册方式）：

```python
from app.tasks import mistake_recognize  # noqa: F401  （注册 mistake.recognize）
```

- [ ] **Step 5: 跑测试确认通过**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_mistake_task.py -q`
Expected: `6 passed`

- [ ] **Step 6: 全量回归 + Commit**

Run: `..\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿

```bash
git add backend/app/tasks/mistake_recognize.py backend/app/tasks/__init__.py \
        backend/app/services/mistake_service.py backend/tests/test_mistake_task.py
git commit -m "feat(s4-2): mistake.recognize 任务（拍照→识别→建题→建错题，不自行提交）"
```

---

### Task 9: 8 个接口 + 路由挂载

**Files:**
- Create: `backend/app/api/v1/mistakes.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_mistakes_api.py`

**Interfaces:**
- Consumes: `app.schemas.common.Envelope`、`TaskOut`、`get_current_user`/`get_db`/`get_storage`/`get_task_queue`、Task 5–8 的全部 service 函数
- Produces: `mistakes.router`（`prefix="/mistakes"`），8 个路由；`/photo` 与 `/stats` 必须在 `/{mistake_id}` 之前声明

- [ ] **Step 1: 写测试（TestClient + 依赖覆盖）**

`backend/tests/test_mistakes_api.py`（照 S4-1 `tests/test_questions_api.py` 的写法；若该文件用 `app.dependency_overrides`，沿用同一套 fixture）：

```python
def test_photo_and_stats_routes_declared_before_path_param():
    from app.api.v1.mistakes import router

    paths = [route.path for route in router.routes]
    assert paths.index("/mistakes/photo") < paths.index("/mistakes/{mistake_id}")
    assert paths.index("/mistakes/stats") < paths.index("/mistakes/{mistake_id}")


def test_list_requires_auth(client):
    assert client.get("/api/v1/mistakes").status_code == 401


def test_create_from_question_returns_201(client, auth_headers, fake_question):
    response = client.post(
        "/api/v1/mistakes", json={"question_id": fake_question}, headers=auth_headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["created"] is True


def test_photo_rejects_non_image(client, auth_headers):
    files = {"file": ("a.txt", b"hello", "text/plain")}
    response = client.post(
        "/api/v1/mistakes/photo", files=files, params={"subject_id": 7}, headers=auth_headers
    )
    assert response.status_code == 422


def test_review_requires_correct_field(client, auth_headers, fake_mistake):
    response = client.post(f"/api/v1/mistakes/{fake_mistake}/review", json={}, headers=auth_headers)
    assert response.status_code == 422


def test_delete_returns_204(client, auth_headers, fake_mistake):
    assert client.delete(f"/api/v1/mistakes/{fake_mistake}", headers=auth_headers).status_code == 204


def test_stats_returns_three_dimensions(client, auth_headers):
    body = client.get("/api/v1/mistakes/stats", headers=auth_headers).json()
    assert set(body["data"]) == {"total", "by_status", "by_cause", "top_kps"}
```

> fixture 名以 `tests/test_questions_api.py` 实际提供的为准（S4-1 已有一套登录/session 覆盖），**先读那个文件再写**；本任务只新增错题相关用例，不新建 fixture 体系。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_mistakes_api.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.api.v1.mistakes'`

- [ ] **Step 3: 写路由**

`backend/app/api/v1/mistakes.py`（**注意声明顺序**）：

```python
"""S4-2 错题本路由：只做参数校验与 Envelope；权限与规则在 mistake_service。

`/photo` 与 `/stats` 必须声明在 `/{mistake_id}` 之前，否则会被路径参数吞掉
（与 S4-1 `/questions/import` 同款坑）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_storage, get_task_queue
from app.core.storage import ObjectStorage
from app.models.enums import MISTAKE_STATUSES
from app.models.user import User
from app.schemas.common import Envelope, PageData
from app.schemas.mistake import (
    MistakeCreateIn,
    MistakeCreateOut,
    MistakeDetailOut,
    MistakeReviewIn,
    MistakeStatsOut,
    MistakeSummaryOut,
    MistakeUpdateIn,
)
from app.schemas.task import TaskOut
from app.services import mistake_service
from app.tasks.queue import TaskQueue
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

router = APIRouter(prefix="/mistakes", tags=["mistakes"])


@router.post("/photo", status_code=202, response_model=Envelope[TaskOut], summary="拍照录入错题")
def create_from_photo(
    file: UploadFile | None = File(default=None, description="题目照片（PNG/JPEG/WebP）"),
    subject_id: int = Query(..., description="学科 id"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    if file is None or not file.filename:
        raise InvalidParamError("请求缺少 file 字段")
    task = mistake_service.start_photo_recognize(
        session, owner=current_user, subject_id=subject_id, upload=file, storage=storage, queue=queue
    )
    return Envelope(data=TaskOut.model_validate(task))


@router.get("/stats", response_model=Envelope[MistakeStatsOut], summary="错题统计")
def get_stats(
    created_from: datetime | None = Query(None),
    created_to: datetime | None = Query(None),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeStatsOut]:
    data = mistake_service.stats(
        session, user_id=current_user.id, created_from=created_from, created_to=created_to
    )
    return Envelope(data=data)


@router.get("", response_model=Envelope[PageData[MistakeSummaryOut]], summary="错题列表")
def list_mistakes(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    status: str | None = Query(None, description="状态：待订正/已订正/已掌握"),
    cause_type: str | None = Query(None, description="错因（S4-3 起才有数据）"),
    kp_id: int | None = Query(None),
    created_from: datetime | None = Query(None),
    created_to: datetime | None = Query(None),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[MistakeSummaryOut]]:
    if status is not None and status not in MISTAKE_STATUSES:
        raise InvalidParamError(f"非法的错题状态：{status}")
    filters = mistake_service.MistakeFilters(
        status=status, cause_type=cause_type, kp_id=kp_id,
        created_from=created_from, created_to=created_to,
    )
    data = mistake_service.list_mistakes(
        session, user_id=current_user.id, filters=filters, page=params, sort=sort
    )
    return Envelope(data=data)


@router.post("", status_code=201, response_model=Envelope[MistakeCreateOut], summary="从题库录入错题")
def create_mistake(
    payload: MistakeCreateIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeCreateOut]:
    detail, created = mistake_service.create_from_question(
        session, user_id=current_user.id, payload=payload
    )
    return Envelope(data=MistakeCreateOut(**detail.model_dump(), created=created))


@router.get("/{mistake_id}", response_model=Envelope[MistakeDetailOut], summary="错题详情")
def get_mistake(
    mistake_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeDetailOut]:
    return Envelope(data=mistake_service.get_detail(session, user_id=current_user.id, mistake_id=mistake_id))


@router.patch("/{mistake_id}", response_model=Envelope[MistakeDetailOut], summary="更新错题")
def update_mistake(
    mistake_id: int,
    payload: MistakeUpdateIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeDetailOut]:
    return Envelope(
        data=mistake_service.update_mistake(
            session, user_id=current_user.id, mistake_id=mistake_id, payload=payload
        )
    )


@router.post("/{mistake_id}/review", response_model=Envelope[MistakeDetailOut], summary="复习记录")
def review_mistake(
    mistake_id: int,
    payload: MistakeReviewIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeDetailOut]:
    return Envelope(
        data=mistake_service.record_review(
            session, user_id=current_user.id, mistake_id=mistake_id, correct=payload.correct
        )
    )


@router.delete("/{mistake_id}", status_code=204, summary="删除错题")
def delete_mistake(
    mistake_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> None:
    mistake_service.delete_mistake(session, user_id=current_user.id, mistake_id=mistake_id)
```

补 `InvalidParamError` import：`from app.core.exceptions import InvalidParamError`。

- [ ] **Step 4: 挂载路由**

`backend/app/api/router.py` 在 `questions.include_router` 之后加：

```python
api_router.include_router(mistakes.router)
```

并在顶部 import 里加 `mistakes`。

- [ ] **Step 5: 跑测试确认通过**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_mistakes_api.py -q`
Expected: 全绿（≤10 条）

- [ ] **Step 6: 全量回归 + Commit**

Run: `..\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿

```bash
git add backend/app/api/v1/mistakes.py backend/app/api/router.py backend/tests/test_mistakes_api.py
git commit -m "feat(s4-2): 错题 8 个接口（拍照/列表/统计/详情/更新/复习/删除）"
```

---

### Task 10: 前端契约、API、路由与导航

**Files:**
- Create: `web/src/types/mistakes.ts`
- Create: `web/src/api/mistakes.ts`
- Modify: `web/src/router/index.ts`
- Modify: `web/src/components/layout/nav.ts`
- Test: `web/src/views/layout/__tests__/MainLayout.spec.ts`（导航条数断言 7 → 10）

**Interfaces:**
- Consumes: `web/src/api/http.ts` 的 `http`（统一错误提示）、`PageData`/`Envelope` 类型（`web/src/types/common.ts`）
- Produces:
  - `types/mistakes.ts`：`MistakeSummary`、`MistakeDetail`、`MistakeStats`、`MistakeStatus`（`'待订正' | '已订正' | '已掌握'`）、`MistakeFilters`
  - `api/mistakes.ts`：`listMistakes(params)`、`getMistakeStats(params?)`、`createMistake(body)`、`createMistakeFromPhoto(file, subjectId)`、`getMistake(id)`、`updateMistake(id, body)`、`reviewMistake(id, correct)`、`deleteMistake(id)`
  - 路由：`/mistakes`、`/mistakes/capture`、`/mistakes/:id`；导航「06 错题本」

- [ ] **Step 1: 写类型**

`web/src/types/mistakes.ts`：

```ts
export type MistakeStatus = '待订正' | '已订正' | '已掌握'

export interface MistakeSummary {
  id: number
  question_id: number
  status: MistakeStatus
  correct_streak: number
  stem_excerpt: string
  subject_id: number
  qtype: string
  difficulty: number
  kp_names: string[]
  cause_type: string | null
  has_image: boolean
  created_at: string
  last_review_at: string | null
}

export interface MistakeAnalysis {
  cause_type: string
  error_step: string | null
  explanation_md: string | null
  review_advice_md: string | null
  kp_ids: number[] | null
  created_at: string
}

export interface MistakeDetail extends MistakeSummary {
  stem_md: string
  options: { key: string; text: string }[] | null
  my_answer_md: string | null
  correct_answer_md: string | null
  image_url: string | null
  analysis: MistakeAnalysis | null
}

export interface MistakeCreateResult extends MistakeDetail {
  created: boolean
}

export interface MistakeStats {
  total: number
  by_status: { status: MistakeStatus; count: number }[]
  by_cause: { cause_type: string; count: number }[]
  top_kps: { kp_id: number; kp_name: string; count: number }[]
}

export interface MistakeFilters {
  status?: MistakeStatus | ''
  cause_type?: string
  kp_id?: number | null
  created_from?: string
  created_to?: string
  page?: number
  page_size?: number
  sort_by?: string
  order?: 'asc' | 'desc'
}
```

- [ ] **Step 2: 写 API 封装（照 `api/questions.ts` 的写法）**

`web/src/api/mistakes.ts`：

```ts
import { http } from './http'
import type { PageData } from '@/types/common'
import type {
  MistakeCreateResult, MistakeDetail, MistakeFilters, MistakeStats, MistakeSummary,
} from '@/types/mistakes'
import type { TaskOut } from '@/types/tasks'

export function listMistakes(params: MistakeFilters) {
  return http.get<PageData<MistakeSummary>>('/mistakes', { params })
}

export function getMistakeStats(params?: { created_from?: string; created_to?: string }) {
  return http.get<MistakeStats>('/mistakes/stats', { params })
}

export function createMistake(body: {
  question_id: number
  my_answer_md?: string | null
  correct_answer_md?: string | null
}) {
  return http.post<MistakeCreateResult>('/mistakes', body)
}

export function createMistakeFromPhoto(file: File, subjectId: number) {
  const form = new FormData()
  form.append('file', file)
  return http.post<TaskOut>('/mistakes/photo', form, { params: { subject_id: subjectId } })
}

export function getMistake(id: number) {
  return http.get<MistakeDetail>(`/mistakes/${id}`)
}

export function updateMistake(
  id: number,
  body: { my_answer_md?: string; correct_answer_md?: string; status?: string },
) {
  return http.patch<MistakeDetail>(`/mistakes/${id}`, body)
}

export function reviewMistake(id: number, correct: boolean) {
  return http.post<MistakeDetail>(`/mistakes/${id}/review`, { correct })
}

export function deleteMistake(id: number) {
  return http.delete<void>(`/mistakes/${id}`)
}
```

- [ ] **Step 3: 加路由与导航**

`web/src/router/index.ts`（照 `/questions` 的写法，含角色守卫）：

```ts
  {
    path: '/mistakes',
    component: MainLayout,
    children: [
      { path: '', name: 'mistakes', component: () => import('@/views/mistakes/MistakeListView.vue') },
      {
        path: 'capture',
        name: 'mistake-capture',
        component: () => import('@/views/mistakes/MistakeCaptureView.vue'),
      },
      {
        path: ':id',
        name: 'mistake-detail',
        component: () => import('@/views/mistakes/MistakeDetailView.vue'),
      },
    ],
  },
```

`web/src/components/layout/nav.ts` 在题库后插入：

```ts
  { index: '/mistakes', label: '06 错题本', icon: Notebook },
```

（`icon` 用文件里已 import 的元素图标，如 `Collection`/`Notebook`；导出数组的名字按现有结构。）

同时把后续条目的编号顺延（原「06 智能问答」→「07」等），并**同步改** `MainLayout.spec.ts` 里的导航条数断言。

- [ ] **Step 4: 跑前端测试确认导航断言**

Run: `cd web && npm run test:run -- --pool=threads`
Expected: 若 `MainLayout.spec.ts` 断言条数，需要更新为新的条数后全绿

- [ ] **Step 5: Commit**

```bash
git add web/src/types/mistakes.ts web/src/api/mistakes.ts web/src/router/index.ts \
        web/src/components/layout/nav.ts web/src/views/layout/__tests__/MainLayout.spec.ts
git commit -m "feat(s4-2): 前端错题契约/API/路由与侧栏入口"
```

---

### Task 11: 错题列表页（统计卡 + 筛选）

**Files:**
- Create: `web/src/views/mistakes/MistakeListView.vue`
- Test: `web/src/views/mistakes/__tests__/MistakeListView.spec.ts`

**Interfaces:**
- Consumes: Task 10 的 `listMistakes`/`getMistakeStats`/`reviewMistake`/`deleteMistake`、`MdPreview` 不用于列表（只用纯文本摘录）、`ElMessageBox`
- Produces: 页面组件（无导出 API）；`data-testid="mistake-list"` 容器

- [ ] **Step 1: 写失败测试**

`web/src/views/mistakes/__tests__/MistakeListView.spec.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ElMessageBox } from 'element-plus'

import MistakeListView from '../MistakeListView.vue'

const listMistakes = vi.fn()
const getMistakeStats = vi.fn()
const reviewMistake = vi.fn()
const deleteMistake = vi.fn()

vi.mock('@/api/mistakes', () => ({
  listMistakes: (...args: unknown[]) => listMistakes(...args),
  getMistakeStats: (...args: unknown[]) => getMistakeStats(...args),
  reviewMistake: (...args: unknown[]) => reviewMistake(...args),
  deleteMistake: (...args: unknown[]) => deleteMistake(...args),
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

function summary(overrides: Record<string, unknown> = {}) {
  return {
    id: 1, question_id: 65, status: '待订正', correct_streak: 0,
    stem_excerpt: '已知函数 f(x)=x^2-4x+3', subject_id: 7, qtype: '解答', difficulty: 2,
    kp_names: ['函数的单调性'], cause_type: null, has_image: false,
    created_at: '2026-11-03T00:00:00Z', last_review_at: null, ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  listMistakes.mockResolvedValue({ items: [summary(), summary({ id: 2, status: '已掌握' })], total: 2, page: 1, page_size: 20 })
  getMistakeStats.mockResolvedValue({
    total: 2,
    by_status: [{ status: '待订正', count: 1 }, { status: '已订正', count: 0 }, { status: '已掌握', count: 1 }],
    by_cause: [],
    top_kps: [{ kp_id: 137, kp_name: '函数的单调性', count: 1 }],
  })
  reviewMistake.mockResolvedValue({})
  deleteMistake.mockResolvedValue(undefined)
})

describe('MistakeListView', () => {
  it('renders rows and stats', async () => {
    const wrapper = mount(MistakeListView, { global: { stubs: { Teleport: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('已知函数')
    expect(wrapper.text()).toContain('函数的单调性')
    expect(getMistakeStats).toHaveBeenCalled()
  })

  it('sends status filter to api', async () => {
    const wrapper = mount(MistakeListView, { global: { stubs: { Teleport: true } } })
    await flushPromises()
    listMistakes.mockClear()
    await wrapper.find('[data-testid="filter-status"]').trigger('change')
    // 直接调用组件方法更稳（Element Plus 下拉的 DOM 交互成本高）
    await (wrapper.vm as unknown as { reload: (filters?: Record<string, unknown>) => Promise<void> })
      .reload({ status: '待订正' })
    expect(listMistakes).toHaveBeenCalledWith(expect.objectContaining({ status: '待订正' }))
  })

  it('hides review buttons for mastered rows', async () => {
    const wrapper = mount(MistakeListView, { global: { stubs: { Teleport: true } } })
    await flushPromises()
    const mastered = wrapper.findAll('[data-testid="row-2"] [data-testid="review-correct"]')
    expect(mastered.length).toBe(0)
  })

  it('calls reviewMistake with true on 答对', async () => {
    const wrapper = mount(MistakeListView, { global: { stubs: { Teleport: true } } })
    await flushPromises()
    await wrapper.find('[data-testid="row-1"] [data-testid="review-correct"]').trigger('click')
    await flushPromises()
    expect(reviewMistake).toHaveBeenCalledWith(1, true)
  })

  it('confirms before deleting', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = mount(MistakeListView, { global: { stubs: { Teleport: true } } })
    await flushPromises()
    await wrapper.find('[data-testid="row-1"] [data-testid="delete"]').trigger('click')
    await flushPromises()
    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(deleteMistake).toHaveBeenCalledWith(1)
  })

  it('shows diagnosis placeholder text', async () => {
    const wrapper = mount(MistakeListView, { global: { stubs: { Teleport: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('待 S4-3 诊断')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- --pool=threads src/views/mistakes`
Expected: FAIL —— 组件不存在

- [ ] **Step 3: 写组件**

`web/src/views/mistakes/MistakeListView.vue` 要点（完整实现，约 200 行）：

- `const filters = reactive<MistakeFilters>({ status: '', cause_type: '', kp_id: null, created_from: '', created_to: '', page: 1, page_size: 20 })`
- `async function reload(next: Partial<MistakeFilters> = {})`：合并 `next` → `listMistakes({...filters})` 与 `getMistakeStats()` 并发取数 → 写入 `rows`/`stats`/`total`；**必须导出到组件实例**（`defineExpose({ reload })`）供测试调用
- 统计卡：`stats.by_status` 三项 + 总数
- 筛选区：`data-testid="filter-status"`（`el-select`，选项三态 + 全部）、`data-testid="filter-cause"`（选项来自 `by_cause`，为空时提示「错因待 S4-3 诊断」）、知识点树 `el-tree-select` 取 `GET /kp/tree`、`el-date-picker` 区间
- 表格列：题干摘录（`el-tooltip`）、题型、知识点标签、状态徽标、连续答对、录入时间、操作
- 行动作：`data-testid="row-{id}"`；「复习答对」`data-testid="review-correct"`（已掌握行不渲染）、「复习答错」`review-wrong`、「删除」`delete`（`ElMessageBox.confirm` 后调 `deleteMistake`）
- 空态与 `cause_type === null` 时显示「待 S4-3 诊断」
- 顶部按钮：「从题库选题」（`$router.push('/mistakes?pick=1')` 或直接嵌 `el-dialog` 列表选择）、「拍照录入」→ `/mistakes/capture`

- [ ] **Step 4: 跑测试确认通过**

Run: `npm run test:run -- --pool=threads src/views/mistakes`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add web/src/views/mistakes/MistakeListView.vue web/src/views/mistakes/__tests__/MistakeListView.spec.ts
git commit -m "feat(s4-2): 错题列表页（统计卡 + 四维筛选 + 复习/删除操作）"
```

---

### Task 12: 拍照录入页 + 详情页

**Files:**
- Create: `web/src/views/mistakes/MistakeCaptureView.vue`
- Create: `web/src/views/mistakes/MistakeDetailView.vue`
- Test: `web/src/views/mistakes/__tests__/MistakeCaptureView.spec.ts`、`MistakeDetailView.spec.ts`

**Interfaces:**
- Consumes: `createMistakeFromPhoto`、`getMistake`、`updateMistake`、`reviewMistake`；任务轮询复用 `web/src/api/tasks.ts::getTask`
- Produces: 两页组件

- [ ] **Step 1: 写失败测试（两页各 2–3 条）**

`MistakeCaptureView.spec.ts` 关键断言：

```ts
it('uploads the chosen image and polls the task', async () => {
  // 选文件 → 点「开始识别」→ createMistakeFromPhoto 收到 File 与 subjectId
})
it('shows retry and fallback exits when the task fails', async () => {
  // getTask 返回 failed → 页面出现「重试」与「改用题库选题」
})
```

`MistakeDetailView.spec.ts` 关键断言：

```ts
it('renders stem with markdown preview and answer fields', async () => {
  // getMistake 返回含 stem_md/options/my_answer_md → 断言文本渲染
})
it('calls reviewMistake when clicking 答对了', async () => {
  // reviewMistake(12, true)
})
it('shows the S4-3 placeholder when analysis is null', async () => {
  // 断言文案「AI 错因诊断将在 S4-3 上线」
})
```

（测试写法照 Task 11：`vi.mock('@/api/mistakes')` + `flushPromises`；任务 API mock `@/api/tasks`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- --pool=threads src/views/mistakes`
Expected: FAIL —— 组件不存在

- [ ] **Step 3: 写两个组件**

`MistakeCaptureView.vue` 要点：
- `<input type="file" accept="image/*" capture="environment">`（手机直接调起相机）
- 选学科（`el-select`，来自 `GET /subjects` 或现有 store）
- 可选手填「我的作答」（提示：手填优先于识别结果）
- 提交 → `createMistakeFromPhoto` → 4s 一次轮询 `getTask(task.id)` 直到 `succeeded/failed`
- 成功 → `router.push('/mistakes/' + task.result.mistake_id)`；`low_confidence` 时先 `ElMessage.warning('识别置信度偏低，请在详情页核对题干')`
- 失败 → 显示「重试」（重新提交同一文件）与「改用题库选题」（跳列表页并打开选题弹窗）

`MistakeDetailView.vue` 要点：
- `MdPreview` 渲染 `stem_md`（KaTeX 已在 S4-1 配好）
- 选项列表、我的作答编辑器（`el-input type=textarea` + 保存 `updateMistake`）、正确答案（只读）
- 状态徽标 + `correct_streak`；「答对了」/「答错了」按钮 → `reviewMistake(id, true/false)` → 用返回值刷新
- `image_url` 存在时显示缩略图（`<img :src="detail.image_url">`，带 token 由 `http.ts` 的拦截器处理——若图片请求不能带 header，则由前端改用 `fetch` + blob，实现时验证一次并在注释里写明）
- 诊断区：`analysis === null` → 文案「AI 错因诊断将在 S4-3 上线」；否则渲染五维

- [ ] **Step 4: 跑测试确认通过**

Run: `npm run test:run -- --pool=threads src/views/mistakes`
Expected: 全绿（列表 6 + 拍照 2 + 详情 3 = 11）

- [ ] **Step 5: build 验证**

Run: `cd web && npm run build`
Expected: `0 error`

- [ ] **Step 6: Commit**

```bash
git add web/src/views/mistakes/MistakeCaptureView.vue web/src/views/mistakes/MistakeDetailView.vue \
        web/src/views/mistakes/__tests__/MistakeCaptureView.spec.ts \
        web/src/views/mistakes/__tests__/MistakeDetailView.spec.ts
git commit -m "feat(s4-2): 拍照录入页（轮询/重试/兜底）与错题详情页（复习操作 + 诊断占位）"
```

---

### Task 13: 文档同步 + 真机验收

**Files:**
- Modify: `docs/API.md`（新增 §5.6）
- Modify: `docs/SCHEMA.md`（§5.3/§5.4 补唯一键、索引、CHECK 名）
- Modify: `docs/DECISIONS.md`（新增 D-045：拍照异步链路 / 重复录入复用 / 错题仅本人）
- Modify: `docs/PROGRESS.md`（S4-2 状态、验收数字、遗留）
- Modify: `docs/AI协作开发实施计划.md`（S4-2 勾选）
- Modify: `AGENTS.md`（§9.2「错题（S4-2）」条目 + §9.6 锚点）
- Create: `E:\BiShe-AIStudy\.sdd\s4-2-mistakes\accept_s4_2.py`（仓库外验收脚本）

**Interfaces:**
- Consumes: 前面所有 task 的产物 + 真实 PG/Redis/MinIO/Qwen-VL
- Produces: 文档与验收证据（数字必须来自实跑）

- [ ] **Step 1: 起服务（隔离 Redis 库，避免旧 worker 抢任务）**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:REDIS_URL="redis://127.0.0.1:6379/6"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8024 --log-level info
# 另一个窗口
$env:REDIS_URL="redis://127.0.0.1:6379/6"
..\.venv\Scripts\python.exe -m app.tasks.worker
```

- [ ] **Step 2: 题库选录入 10 道 + 重复 1 道**

脚本内：登录 → `GET /questions?subject_id=7&page_size=10` → 逐题 `POST /mistakes` → 断言 10 个 201；再对第 1 题重复 POST → 断言 `created=false` 且 `status='待订正'`。
Expected 输出：`created=10 duplicated=0` 与 `reuse: created=false status=待订正 streak=0`

- [ ] **Step 3: 拍照录入 3 张（真调 Qwen-VL）**

对 `测试数据/mistake_photo/{clean,rotated,answered}.png` 各 `POST /mistakes/photo`（`parse=false` 上传）→ 轮询 `GET /tasks/{id}` 至 `succeeded`。
Expected：3 个任务 `succeeded`，记录每个的 `elapsed_ms`、`confidence`、`reused_question`；
人工逐字比对识别出的 `stem_md` 与原题文字（记录差异字符数/总字符数），把数字写进 PROGRESS。

- [ ] **Step 4: 状态机 + 筛选 + 统计 + 引用保护**

- 取 1 道错题：`review(true)` → 断言 `已订正/streak=1`；再 `review(true)` → `已掌握/streak=2`；`review(false)` → `待订正/streak=0`；
- `GET /mistakes?status=待订正`、`?kp_id=<某知识点>`、`?created_from=...`、`?cause_type=概念不清`（应为 0 条）各查一次，`total` 与人工统计一致；
- `GET /mistakes/stats` → `by_status` 三项之和 = `total`；`top_kps` 与人工统计一致；
- `DELETE /questions/{被错题引用的题号}` → 断言 **409/40900**（S4-2 建表后 S4-1 的守卫首次生效）。

- [ ] **Step 5: 浏览器走一遍**

`/mistakes` 筛选 + 复习 + 删除二次确认；`/mistakes/capture` 上传一张图 → 轮询 → 跳详情；详情页「答对了」→ 徽标变化；诊断区显示 S4-3 占位文案。贴路径与现象。

- [ ] **Step 6: 写文档**

- `docs/API.md` §5.6：8 个接口（表格 + 请求/响应示例 + 错误码 404/40400、422/42200，明确「重复录入返回 201 且 `created=false`」）；
- `docs/SCHEMA.md` §5.3：补 `UNIQUE(user_id, question_id)`、`ix_`/`ck_` 名、`question_id` RESTRICT；§5.4：补 CASCADE 与 GIN；
- `docs/DECISIONS.md` D-045：三条决策（拍照走异步 + 视觉适配器扩 images；重复录入复用重置；错题仅本人可见）+ 实测数字；
- `docs/PROGRESS.md`：S4-2 状态行（基线 865→实测数、前端 125→实测数）、验收表、遗留（手写体未验证、confidence 未校准、一图一题、错因待 S4-3）；
- `AGENTS.md` §9.2 新增 S4-2 条目、§9.6 新增错题锚点；
- 实施计划 S4-2 勾选 + 实施记录。

- [ ] **Step 7: 全量回归（最终提交前）**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest -q
cd ..\web; npm run test:run -- --pool=threads
cd ..\backend; ..\.venv\Scripts\python.exe -m alembic current
```
Expected：后端 ≥905 passed、前端 ≥136 passed、`0010_s4_2 (head)`

- [ ] **Step 8: Commit**

```bash
git add docs AGENTS.md
git commit -m "docs(s4-2): 错题录入与状态机文档同步（API/SCHEMA/决策/进度/规范）"
```

---

## 自检清单（写完 plan 后逐条核对）

- [x] spec §1–§13 每条要求都有对应 task：数据模型 → T2；视觉适配器 → T3/T4；服务 → T5/T6/T7；任务 → T8；接口 → T9；前端三页 → T10/T11/T12；验收与文档 → T13
- [x] 跨 task 的签名一致：`MistakeFilters`、`_load_owned`、`_detail`、`create_from_question`、`record_review`、`build_mistakes_query`、`list_mistakes`、`start_photo_recognize`、`task_create_mistake`、`TASK_MISTAKE_RECOGNIZE`、`MASTERY_STREAK`、`LOW_CONFIDENCE` 在各 task 的 Consumes/Produces 里同名同参
- [x] 无占位符：每个代码步骤都给了可粘贴的实现或明确的「照哪个文件写」
- [x] 既有事实已核对：`Base` 在 `app.core.db`、`in_check` 在 `app.models.enums`、类名 `OpenAICompatibleLLMClient`、`files.mime` 存在、`GET /files/{id}/image` 已存在、`paginate_sa` 来自 `fastapi_pagination.ext.sqlalchemy`、`Question.options_json` 字段名
- [x] 每个 task 都以「跑测试/跑命令 → Commit」收尾，可独立评审