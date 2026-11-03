# S4-4 变式题生成 + 复算自检 实施计划

> **给执行者**：按任务顺序做，每个 Step 都是「一个动作 + 一条可执行验证」。不要跳过验证步骤，也不要把多个 Step 合成一次提交。
> 工具：后端命令一律在 `backend\` 下用 `..\.venv\Scripts\python.exe`；前端命令在 `web\` 下执行。

**目标**：给一道已诊断的错题按需生成 3 道同知识点变式题，用**独立复算 + 确定性比对**自检，通过的写入 `mistake_analyses.similar_questions_json`，用户确认后存入题库（`origin=ai`、`verified=false`）。

**架构**：AI 层 `ai/gen/`（生成器 / 复算器 / 纯函数比对）→ 服务层 `question_gen_service`（触发、任务内编排、入库）→ 任务 `mistake.variants` → 接口 2 个 → 前端详情页「变式训练」区。无迁移（`similar_questions_json` 是 S4-2 建好的 JSONB 列）。

**技术栈**：Python 3.11 / FastAPI / SQLAlchemy 2.0 / Pydantic v2 / ARQ / Jinja2 文件型 Prompt / Vue 3 + TS + Element Plus。

**Spec**：`docs/spec/s4-4-variant-generation.md`（每个任务的「为什么」都在那份文档里，实现前先读对应章节）

**上游任务**：S4-1（题库判重、`validate_question_shape`）、S4-2（`mistakes`、`similar_questions_json` 列）、S4-3（`mistake_analyses`、`mistake.analyze`）

## 全局约束

- 枚举一律 TEXT + CHECK，值集常量在 `app/models/enums.py`（本卡不新增枚举）。
- service 一个用例一个事务；任务 handler **不 commit**（runner 统一提交/回滚）。
- 路由函数 ≤30 行，只做「参数校验 → service → `Envelope`」。
- 业务错误只抛 `AppError` 子类：`NotFoundError`(404/40400)、`ConflictError`(409/40900)、`TaskQueueUnavailableError`(500/50000)。
- LLM 调用只走 `app/ai/llm` 适配器；Prompt 只放 `app/ai/prompts/*.md`（禁止代码里硬编码长 Prompt）；`scene` 必须在 `llm_call_logs.scene` 白名单内（本卡用 `gen`）。
- 测试禁止真实外部调用（LLM 一律 mock）；不新增依赖（不加 `requirements.txt` / `package.json`）。
- 提交前缀：`feat(s4-4):` / `test(s4-4):` / `fix(s4-4):` / `docs(s4-4):`。
- 前端**没有** `@element-plus/icons-vue`：加载态用既有 `.spinner`（CSS），不要写 `<el-icon><Loading /></el-icon>`。
- 不提交生成物：`.sdd/` 下的脚本与证据不进 git；`测试数据/s4_3_cases.json` 已在 `.gitignore`。

---

### Task 1: 答案比对纯函数 `ai/gen/compare.py`

**Files:**
- Create: `backend/app/ai/gen/__init__.py`（本任务先只导出 compare）
- Create: `backend/app/ai/gen/compare.py`
- Test: `backend/tests/test_variant_compare.py`

**Interfaces:**
- Produces:
  - `normalize_answer(text: str) -> str`
  - `parse_number(text: str) -> Decimal | None`
  - `match_answers(expected: str, actual: str) -> tuple[bool, str]`（第二个值是原因说明，一致时给 `"一致（数值）"` 这类短句）
  - `REL_TOL: Decimal = Decimal("1e-6")`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_variant_compare.py`：

```python
"""S4-4 答案比对：规范化、数值容差、选择题 key、多解集合、同义词组。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.gen.compare import match_answers, normalize_answer, parse_number


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$31$", "31"),
        ("$$\\frac{3}{5}$$", "\\frac{3}{5}"),
        (" 答案：$x=2$ 。", "x=2"),
        ("８０％", "80%"),
        ("（２，３）", "(2,3)"),
        ("\\left( x \\right)", "(x)"),
        ("\\dfrac{1}{2}", "\\frac{1}{2}"),
        ("\\text{无解}", "无解"),
        ("3×4", "3*4"),
    ],
)
def test_normalize_answer_variants(raw, expected):
    assert normalize_answer(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("31", Decimal("31")),
        ("-4/5", Decimal("-0.8")),
        ("\\frac{3}{5}", Decimal("0.6")),
        ("80\\%", Decimal("0.8")),
        ("80%", Decimal("0.8")),
        ("0.8", Decimal("0.8")),
        ("\\sqrt{25}", Decimal("5")),
    ],
)
def test_parse_number_supported_forms(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw", ["x=2", "\\sqrt{3}", "3\\sqrt{3}", ""])
def test_parse_number_rejects_non_numeric(raw):
    assert parse_number(raw) is None


def test_match_answers_numbers_with_tolerance():
    assert match_answers("$0.8$", "$0.8000001$")[0] is True


def test_match_answers_numbers_different():
    ok, reason = match_answers("$31$", "$30$")
    assert ok is False
    assert "31" in reason and "30" in reason


def test_match_answers_choice_keys_sets():
    assert match_answers("AC", "A、C")[0] is True
    assert match_answers("AC", "A,C")[0] is True
    assert match_answers("AC", "A")[0] is False


def test_match_answers_multi_solution_sets_ignoring_order():
    assert match_answers("$x=2$ 或 $x=3$", "$x=3$，$x=2$")[0] is True


def test_match_answers_synonyms():
    assert match_answers("无解", "没有解")[0] is True
    assert match_answers("全体实数", "R")[0] is True
    assert match_answers("无解", "全体实数")[0] is False


def test_match_answers_plain_text():
    assert match_answers("单调递减", "单调 递减")[0] is True
    assert match_answers("单调递减", "单调递增")[0] is False
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_variant_compare.py -q
```

预期：`ModuleNotFoundError: No module named 'app.ai.gen'`。

- [ ] **Step 3: 实现 compare.py**

`backend/app/ai/gen/compare.py`：

```python
"""S4-4 复算自检的比对层：只做"确定等价"的规范化，不做数学变形。

判定顺序（spec §5.3）：选择题 key 集合 → 数值容差 → 同义词组 → 多解集合 → 字符串。
一致即放行；不一致返回原因，写进 `rejected[].reason` 供验收追查。
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

REL_TOL = Decimal("1e-6")

_FENCE = re.compile(r"```[a-zA-Z]*")
_TEXT_WRAP = re.compile(r"\\(?:text|mathrm)\{([^{}]*)\}")
_PREFIX = re.compile(r"^(?:答案|答|所以|因此|故|综上)\s*[:：]?\s*")
_SPACE = re.compile(r"\s+")
_TRAILING = re.compile(r"[。.;；]+$")
_PERCENT = re.compile(r"^(-?\d+(?:\.\d+)?)\\?%$")
_SIMPLE_FRAC = re.compile(r"^(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)$")
_LATEX_FRAC = re.compile(r"^\\frac\{(-?\d+(?:\.\d+)?)\}\{(-?\d+(?:\.\d+)?)\}$")
_SQRT = re.compile(r"^\\sqrt\{(\d+(?:\.\d+)?)\}$")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_OPTION_KEYS = re.compile(r"^[A-H]{1,8}$")
_SET_SEP = re.compile(r"[或,、;；]")
_KEY_SEP = re.compile(r"[,、;；]")

_SYNONYM_GROUPS = (
    frozenset({"无解", "没有解", "不存在", "无实数解"}),
    frozenset({"全体实数", "任意实数", "R", "\\mathbb{R}", "(-∞,+∞)"}),
    frozenset({"无穷多解", "无数解"}),
)


def normalize_answer(text: str) -> str:
    # NFKC 一次性把全角数字/字母/括号/逗号/百分号折成半角；
    # 自己维护 translate 表会漏（首版就漏了全角数字，测试直接抓到）。
    clean = unicodedata.normalize("NFKC", (text or "").strip())
    clean = _FENCE.sub("", clean).replace("$", "")
    clean = clean.replace("−", "-").replace("－", "-")
    clean = _TEXT_WRAP.sub(r"\1", clean)
    clean = clean.replace("\\left", "").replace("\\right", "")
    clean = clean.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    clean = clean.replace("\\cdot", "*").replace("×", "*").replace("÷", "/")
    clean = re.sub(r"\\[,;:!]", "", clean)
    clean = clean.replace("√", "\\sqrt")
    clean = _SPACE.sub("", clean)
    clean = _PREFIX.sub("", clean)
    return _TRAILING.sub("", clean)


def parse_number(text: str) -> Decimal | None:
    clean = normalize_answer(text)
    if not clean:
        return None
    match = _PERCENT.match(clean)
    if match:
        return _to_decimal(match.group(1)) / 100
    match = _LATEX_FRAC.match(clean) or _SIMPLE_FRAC.match(clean)
    if match:
        numerator, denominator = _to_decimal(match.group(1)), _to_decimal(match.group(2))
        if denominator == 0:
            return None
        return numerator / denominator
    if _NUMBER.match(clean):
        return _to_decimal(clean)
    match = _SQRT.match(clean)
    if match:
        root = _to_decimal(match.group(1)).sqrt()
        # 只有完全平方才当数值比，否则留给字符串比较（3√3 这类不要硬算成近似值）
        return root if root == root.to_integral_value() else None
    return None


def match_answers(expected: str, actual: str) -> tuple[bool, str]:
    left, right = normalize_answer(expected), normalize_answer(actual)
    if not left or not right:
        return False, "有一边答案为空"
    left_keys, right_keys = _option_key_set(left), _option_key_set(right)
    if left_keys is not None and right_keys is not None:
        return (left_keys == right_keys), f"选择题 key：{left} vs {right}"
    left_num, right_num = parse_number(left), parse_number(right)
    if left_num is not None and right_num is not None:
        return _numbers_close(left_num, right_num), f"数值：{left} vs {right}"
    left_group, right_group = _synonym_group(left), _synonym_group(right)
    if left_group is not None and right_group is not None:
        return (left_group is right_group), f"同义词：{left} vs {right}"
    left_parts, right_parts = _solution_parts(left), _solution_parts(right)
    if len(left_parts) > 1 or len(right_parts) > 1:
        return (left_parts == right_parts), f"多解集合：{left} vs {right}"
    return (left == right), f"复算答案不一致：{expected} ≠ {actual}"


def _to_decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation:  # pragma: no cover - 正则已限定形态
        raise ValueError(f"不是数值：{raw}") from None


def _numbers_close(left: Decimal, right: Decimal) -> bool:
    diff = abs(left - right)
    if left == 0 or right == 0:
        return diff <= REL_TOL
    return diff / max(abs(left), abs(right)) <= REL_TOL


def _option_key_set(text: str) -> frozenset[str] | None:
    """`AC` / `A,C` / `A、C` 都归一成 key 集合；非纯 key 返回 None 交给后续规则。"""
    compact = _KEY_SEP.sub("", text)
    if _OPTION_KEYS.match(compact):
        return frozenset(compact)
    return None


def _synonym_group(text: str) -> frozenset[str] | None:
    for group in _SYNONYM_GROUPS:
        if text in group:
            return group
    return None


def _solution_parts(text: str) -> frozenset[str]:
    parts = [part for part in _SET_SEP.split(text) if part]
    return frozenset(parts)
```

`backend/app/ai/gen/__init__.py`：

```python
"""S4-4 变式题生成门面：业务层只 import 这里。"""
from app.ai.gen.compare import REL_TOL, match_answers, normalize_answer, parse_number

__all__ = ["REL_TOL", "match_answers", "normalize_answer", "parse_number"]
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_variant_compare.py -q
```

预期：全绿（约 26 条）。

- [ ] **Step 5: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/app/ai/gen/compare.py backend/app/ai/gen/__init__.py backend/tests/test_variant_compare.py
git commit -m "feat(s4-4): 变式题答案比对纯函数（数值容差/选项集合/多解/同义词）"
```

---

### Task 2: 生成适配器 `ai/gen/variant_generator.py` + Prompt

**Files:**
- Create: `backend/app/ai/prompts/question_gen_v1.md`
- Create: `backend/app/ai/gen/variant_generator.py`
- Modify: `backend/app/ai/gen/__init__.py`
- Test: `backend/tests/test_variant_generator.py`

**Interfaces:**
- Consumes: `app.ai.json_utils.loads_json_object`、`app.ai.llm.{LLMClient, LLMMessage, get_llm_client}`、`app.schemas.question.validate_question_shape`
- Produces:
  - `class GenerationContext`（frozen dataclass：`stem_md, options, correct_answer_md, kp_names, cause_type, qtype, difficulty, count`）
  - `class GeneratedVariant(BaseModel)`：`stem_md, options (list[dict] 或 None), answer_md, analysis_md, qtype, difficulty`
  - `class VariantGenerationError(Exception)`
  - `generate_variants(context, *, llm_client=None, max_retries=2) -> list[GeneratedVariant]`
  - `render_prompt(context) -> str`
  - `PROMPT_VERSION = "question_gen_v1"`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_variant_generator.py`：

```python
"""S4-4 生成适配器：严格 JSON、条数、选项规则、重试。"""
from __future__ import annotations

import pytest

from app.ai.gen.variant_generator import (
    GenerationContext,
    GeneratedVariant,
    VariantGenerationError,
    generate_variants,
    render_prompt,
)


class FakeClient:
    def __init__(self, payloads: list[str]):
        self.payloads = payloads
        self.calls: list[dict] = []

    def chat(self, messages, *, temperature=0.0, max_tokens=None, scene=""):
        self.calls.append({"messages": messages, "scene": scene, "temperature": temperature})

        class _Resp:
            text = self.payloads.pop(0)

        return _Resp()


def _ctx(**overrides) -> GenerationContext:
    base = dict(
        stem_md="等差数列 $\\{a_n\\}$ 中 $a_1=2$，公差 $d=3$，求 $a_{10}$。",
        options=[],
        correct_answer_md="$29$",
        kp_names=["等差数列"],
        cause_type="审题偏差",
        qtype="解答",
        difficulty=2,
        count=2,
    )
    base.update(overrides)
    return GenerationContext(**base)


GOOD = (
    '{"items":['
    '{"stem_md":"等差数列 $a_1=1$，公差 $d=2$，求 $a_7$。","options":null,'
    '"answer_md":"$13$","analysis_md":"用 $a_n=a_1+(n-1)d$，得 $a_7=1+6\\\\times2=13$。",'
    '"qtype":"解答","difficulty":3},'
    '{"stem_md":"等差数列 $a_1=5$，公差 $d=-2$，求 $a_6$。","options":null,'
    '"answer_md":"$-5$","analysis_md":"$a_6=5+5\\\\times(-2)=-5$，注意符号。",'
    '"qtype":"解答","difficulty":1}'
    "]}"
)


def test_generate_variants_returns_parsed_items():
    client = FakeClient([GOOD])

    items = generate_variants(_ctx(), llm_client=client)

    assert [item.answer_md for item in items] == ["$13$", "$-5$"]
    assert all(isinstance(item, GeneratedVariant) for item in items)
    assert client.calls[0]["scene"] == "gen"
    assert client.calls[0]["temperature"] == 0.7


def test_generate_variants_prompt_contains_context():
    prompt = render_prompt(_ctx())

    assert "等差数列" in prompt
    assert "审题偏差" in prompt
    assert "$29$" in prompt


def test_generate_variants_retries_on_short_count():
    short = '{"items":[{"stem_md":"求 $1+2$ 的值。","options":null,"answer_md":"$3$",' \
            '"analysis_md":"直接相加得 3，注意不要抄错。","qtype":"解答","difficulty":1}]}'
    client = FakeClient([short, GOOD])

    items = generate_variants(_ctx(), llm_client=client)

    assert len(items) == 2
    assert len(client.calls) == 2


def test_generate_variants_retries_on_invalid_option_shape():
    bad = ('{"items":[{"stem_md":"下列哪个正确？","options":[{"key":"A","text":"1"}],'
           '"answer_md":"A","analysis_md":"只有一个选项，不合法但先看校验。","qtype":"单选","difficulty":2}]}')
    short_ok = '{"items":[{"stem_md":"求 $2+2$ 的值。","options":null,"answer_md":"$4$",' \
               '"analysis_md":"直接相加得 4，注意进位。","qtype":"解答","difficulty":1}]}'
    client = FakeClient([bad, short_ok])

    items = generate_variants(_ctx(count=1), llm_client=client)

    assert len(items) == 1
    assert len(client.calls) == 2


def test_generate_variants_raises_after_retries_exhausted():
    client = FakeClient(["不是 JSON", "还是不是 JSON", "仍不是 JSON"])

    with pytest.raises(VariantGenerationError):
        generate_variants(_ctx(), llm_client=client, max_retries=2)
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_variant_generator.py -q
```

预期：`ModuleNotFoundError` 或 `ImportError`。

- [ ] **Step 3: 写 Prompt**

`backend/app/ai/prompts/question_gen_v1.md`：

```markdown
你是一位资深高中数学命题老师，现在要为一名学生出 {{ count }} 道**同知识点变式题**。

## 原题
{{ stem_md }}
{% if options %}
选项：
{% for key, text in options %}{{ key }}. {{ text }}
{% endfor %}
{% endif %}
标准答案：{{ correct_answer_md or "（未提供）" }}
知识点：{{ kp_names | join("、") if kp_names else "（未标注）" }}
学生的错因：{{ cause_type or "（未诊断）" }}
原题题型：{{ qtype }}；原题难度：{{ difficulty }}（1 最易，5 最难）

## 出题要求
1. 每题必须考同一个知识点（上面列出的知识点），不要跑题。
2. 难度 = 原题难度 ±1，落在 1–5 之间。
3. **不得与原题数字、情境雷同**：换数字、换问法（如求第 n 项换成求项数）、换情境。
4. 题型必须与原题相同（原题是 {{ qtype }}，就出 {{ qtype }}）；选择题必须给 ≥2 个选项且 key 唯一，填空/解答题不得有选项。
5. 每题都要给最终答案与不超过 3 步的分步解析，公式用 LaTeX（行内 $...$）。
6. 答案必须是你自己算过、确定正确的；不确定就换一道更简单的，不要编。

## 输出
严格输出 JSON，不要代码围栏以外的任何解释：

{"items":[{"stem_md":"","options":null,"answer_md":"","analysis_md":"","qtype":"{{ qtype }}","difficulty":3}]}

`options` 仅选择题使用，形如 [{"key":"A","text":""}]；其余题型为 null。
必须正好输出 {{ count }} 道题。
```

- [ ] **Step 4: 写生成器**

`backend/app/ai/gen/variant_generator.py`：

```python
"""S4-4 变式题生成适配器：严格 JSON + Pydantic 校验 + 最多 2 次重试。

只负责「把上下文变成可信的结构化题目」；答案对不对由 `variant_verifier` 独立复算，
比对由 `compare.match_answers` 决定 —— 三件事分开，测试才能分别盯住（spec §5）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client
from app.schemas.question import OptionIn, validate_question_shape

logger = logging.getLogger(__name__)

SCENE = "gen"
PROMPT_VERSION = "question_gen_v1"
PROMPT_FILE = "question_gen_v1.md"
MAX_VARIANTS = 3
MAX_RETRIES = 2
# 真机验收：3 道解答题连解析一起输出常到 1700~2500 tokens，2000 会整批截断成非法 JSON
MAX_TOKENS = 3500
STEM_LIMIT = 2000
ANSWER_LIMIT = 800
# 真机验收：解析常写到 1500 字符以上，整批 3 道全废；放宽到 2000（Prompt 仍要求 ≤200 字）
ANALYSIS_LIMIT = 2000
KP_LIMIT = 3
TEMPERATURE = 0.7

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)

_QTYPE = ("单选", "多选", "填空", "解答")


class VariantGenerationError(Exception):
    """生成失败：JSON 非法、条数不符、字段非法、重试耗尽。"""


@dataclass(frozen=True)
class GenerationContext:
    stem_md: str
    options: list[tuple[str, str]] = field(default_factory=list)
    correct_answer_md: str | None = None
    kp_names: list[str] = field(default_factory=list)
    cause_type: str | None = None
    qtype: str = "解答"
    difficulty: int = 3
    count: int = MAX_VARIANTS


class GeneratedVariant(BaseModel):
    stem_md: str = Field(min_length=5, max_length=STEM_LIMIT)
    options: list[OptionIn] | None = None
    answer_md: str = Field(min_length=1, max_length=ANSWER_LIMIT)
    analysis_md: str = Field(min_length=10, max_length=ANALYSIS_LIMIT)
    qtype: str
    difficulty: int = Field(ge=1, le=5)

    @model_validator(mode="after")
    def _check(self) -> "GeneratedVariant":
        if self.qtype not in _QTYPE:
            raise ValueError(f"非法题型：{self.qtype}")
        keys = [option.key for option in self.options] if self.options else None
        validate_question_shape(qtype=self.qtype, option_keys=keys)
        self.stem_md = self.stem_md.strip()
        self.answer_md = self.answer_md.strip()
        self.analysis_md = self.analysis_md.strip()
        return self


class _ItemsOut(BaseModel):
    items: list[GeneratedVariant]


def render_prompt(context: GenerationContext) -> str:
    try:
        template = _ENV.get_template(PROMPT_FILE)
        return template.render(
            stem_md=context.stem_md[:STEM_LIMIT],
            options=context.options,
            correct_answer_md=(context.correct_answer_md or "")[:ANSWER_LIMIT] or None,
            kp_names=context.kp_names[:KP_LIMIT],
            cause_type=context.cause_type,
            qtype=context.qtype,
            difficulty=context.difficulty,
            count=context.count,
        )
    except Exception as exc:  # 模板缺变量/文件缺失都收敛成生成失败
        raise VariantGenerationError(f"prompt 渲染失败：{exc}") from exc


def generate_variants(
    context: GenerationContext,
    *,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> list[GeneratedVariant]:
    """生成 `context.count` 道题；条数不符或字段非法都按失败重试。"""
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    if context.count < 1:
        raise ValueError("count 必须 ≥1")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_prompt(context))]

    last_error: Exception | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        response = client.chat(
            messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, scene=SCENE
        )
        try:
            parsed = _ItemsOut.model_validate(loads_json_object(response.text))
            if len(parsed.items) != context.count:
                raise ValueError(f"生成条数不符：{len(parsed.items)} != {context.count}")
            return parsed.items
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.info("variant_generate_retry attempt=%s error=%s", attempts, exc)
    raise VariantGenerationError(f"变式题生成失败（已尝试 {attempts} 次）：{last_error}")
```

- [ ] **Step 5: 更新门面**

`backend/app/ai/gen/__init__.py`：

```python
"""S4-4 变式题生成门面：业务层只 import 这里。"""
from app.ai.gen.compare import REL_TOL, match_answers, normalize_answer, parse_number
from app.ai.gen.variant_generator import (
    MAX_VARIANTS,
    PROMPT_VERSION,
    GenerationContext,
    GeneratedVariant,
    VariantGenerationError,
    generate_variants,
    render_prompt,
)

__all__ = [
    "MAX_VARIANTS",
    "PROMPT_VERSION",
    "REL_TOL",
    "GenerationContext",
    "GeneratedVariant",
    "VariantGenerationError",
    "generate_variants",
    "match_answers",
    "normalize_answer",
    "parse_number",
    "render_prompt",
]
```

- [ ] **Step 6: 跑测试确认通过**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_variant_generator.py -q
```

预期：5 条全绿。若 `test_generate_variants_retries_on_invalid_option_shape` 报 `OptionIn` 额外字段/必填问题，检查 `OptionIn` 的字段名（`key` / `text`）。

- [ ] **Step 7: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/app/ai/gen/variant_generator.py backend/app/ai/gen/__init__.py backend/app/ai/prompts/question_gen_v1.md backend/tests/test_variant_generator.py
git commit -m "feat(s4-4): 变式题生成适配器与 Prompt（严格 JSON、选项规则、条数重试）"
```

---

### Task 3: 复算适配器 `ai/gen/variant_verifier.py` + Prompt

**Files:**
- Create: `backend/app/ai/prompts/question_verify_v1.md`
- Create: `backend/app/ai/gen/variant_verifier.py`
- Modify: `backend/app/ai/gen/__init__.py`
- Test: `backend/tests/test_variant_verifier.py`

**Interfaces:**
- Produces:
  - `class VerifyContext`（`stem_md`, `options`）
  - `class VariantVerificationError(Exception)`
  - `verify_answer(context, *, llm_client=None, max_retries=2) -> str`（返回复算出的最终答案文本）
  - `render_verify_prompt(context) -> str`
  - `VERIFY_PROMPT_VERSION = "question_verify_v1"`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_variant_verifier.py`：

```python
"""S4-4 复算适配器：只喂题干（不含答案）、严格 JSON、重试。"""
from __future__ import annotations

import pytest

from app.ai.gen.variant_verifier import (
    VerifyContext,
    VariantVerificationError,
    render_verify_prompt,
    verify_answer,
)


class FakeClient:
    def __init__(self, payloads: list[str]):
        self.payloads = payloads
        self.calls: list[dict] = []

    def chat(self, messages, *, temperature=0.0, max_tokens=None, scene=""):
        self.calls.append({"messages": messages, "scene": scene, "temperature": temperature})

        class _Resp:
            text = self.payloads.pop(0)

        return _Resp()


def _ctx() -> VerifyContext:
    return VerifyContext(
        stem_md="等差数列 $a_1=1$，公差 $d=2$，求 $a_7$。", options=[]
    )


def test_render_verify_prompt_excludes_answer_and_analysis():
    prompt = render_verify_prompt(_ctx())

    assert "等差数列" in prompt
    assert "答案" in prompt  # 只是要求它作答，不能出现给定答案
    assert "$13$" not in prompt


def test_verify_answer_returns_answer_text():
    client = FakeClient(['{"answer_md":"$13$","reasoning_md":"$a_7=1+6\\\\times2=13$"}'])

    answer = verify_answer(_ctx(), llm_client=client)

    assert answer == "$13$"
    assert client.calls[0]["scene"] == "gen"


def test_verify_answer_retries_on_invalid_json():
    client = FakeClient(['{"wrong":1}', '{"answer_md":"$13$"}'])

    assert verify_answer(_ctx(), llm_client=client) == "$13$"


def test_verify_answer_raises_after_retries():
    client = FakeClient(["nope", "nope", "nope"])

    with pytest.raises(VariantVerificationError):
        verify_answer(_ctx(), llm_client=client, max_retries=2)
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_variant_verifier.py -q
```

预期：`ImportError`。

- [ ] **Step 3: 写复算 Prompt**

`backend/app/ai/prompts/question_verify_v1.md`：

```markdown
你是一位独立解题的数学老师。下面是一道题，请**只根据题干**独立求解，不要猜测出题人给过什么答案。

## 题目
{{ stem_md }}
{% if options %}
选项：
{% for key, text in options %}{{ key }}. {{ text }}
{% endfor %}
{% endif %}

## 要求
1. 自己完整算一遍，再给最终答案。
2. 选择题只写选项 key（多选连写，如 AC）；多解用"或"连接；无解就写"无解"。
3. 过程不超过 3 步，公式用 LaTeX。

## 输出
严格输出 JSON，不要代码围栏以外的任何解释：

{"answer_md":"最终答案","reasoning_md":"不超过 3 步的关键过程"}
```

- [ ] **Step 4: 写复算器**

`backend/app/ai/gen/variant_verifier.py`：

```python
"""S4-4 独立复算适配器：只给题干与选项，让模型自己解一遍。

这是自检的独立侧：Prompt 里不出现参考答案（否则等于让模型给自己打分）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, Field, ValidationError

from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client

logger = logging.getLogger(__name__)

SCENE = "gen"
VERIFY_PROMPT_VERSION = "question_verify_v1"
PROMPT_FILE = "question_verify_v1.md"
MAX_RETRIES = 2
STEM_LIMIT = 2000
ANSWER_LIMIT = 500
TEMPERATURE = 0.2
# 真机验收：对数不等式类题目的推理会写满上限，1200/1800 都被截断成非法 JSON，故留 2600
MAX_TOKENS = 2600

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


class VariantVerificationError(Exception):
    """复算失败：JSON 非法、字段缺失、重试耗尽。"""


@dataclass(frozen=True)
class VerifyContext:
    stem_md: str
    options: list[tuple[str, str]] = field(default_factory=list)


REASONING_LIMIT = 1500


class _VerifyOut(BaseModel):
    answer_md: str = Field(min_length=1, max_length=ANSWER_LIMIT)
    reasoning_md: str | None = None

    @model_validator(mode="after")
    def _trim_reasoning(self) -> "_VerifyOut":
        # reasoning 只用于展示、不参与比对：超长就截断，不能因为写多了把整道题判死
        if self.reasoning_md is not None and len(self.reasoning_md) > REASONING_LIMIT:
            self.reasoning_md = self.reasoning_md[:REASONING_LIMIT]
        return self


def render_verify_prompt(context: VerifyContext) -> str:
    try:
        template = _ENV.get_template(PROMPT_FILE)
        return template.render(stem_md=context.stem_md[:STEM_LIMIT], options=context.options)
    except Exception as exc:
        raise VariantVerificationError(f"验证 prompt 渲染失败：{exc}") from exc


def verify_answer(
    context: VerifyContext,
    *,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> str:
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_verify_prompt(context))]

    last_error: Exception | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        response = client.chat(
            messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, scene=SCENE
        )
        try:
            parsed = _VerifyOut.model_validate(loads_json_object(response.text))
            return parsed.answer_md.strip()
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.info("variant_verify_retry attempt=%s error=%s", attempts, exc)
    raise VariantVerificationError(f"复算失败（已尝试 {attempts} 次）：{last_error}")
```

- [ ] **Step 5: 更新门面**

在 `backend/app/ai/gen/__init__.py` 追加导入与 `__all__`：

```python
from app.ai.gen.variant_verifier import (
    VERIFY_PROMPT_VERSION,
    VerifyContext,
    VariantVerificationError,
    render_verify_prompt,
    verify_answer,
)
```

`__all__` 追加：`"VERIFY_PROMPT_VERSION", "VerifyContext", "VariantVerificationError", "render_verify_prompt", "verify_answer"`。

- [ ] **Step 6: 跑测试确认通过**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_variant_verifier.py tests/test_variant_generator.py tests/test_variant_compare.py -q
```

预期：全绿。

- [ ] **Step 7: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/app/ai/gen/variant_verifier.py backend/app/ai/gen/__init__.py backend/app/ai/prompts/question_verify_v1.md backend/tests/test_variant_verifier.py
git commit -m "feat(s4-4): 独立复算适配器与 Prompt（只喂题干，不含参考答案）"
```

---

### Task 4: `question_service.create_generated_question`（AI 题入库唯一入口）

**Files:**
- Modify: `backend/app/services/question_service.py`（在 `create_extracted_question` 之后新增函数；文件头常量区加 `AI_VARIANT_TAG`）
- Test: `backend/tests/test_question_service.py`（追加用例；文件已存在，先读它的 fixture 命名再写）

**Interfaces:**
- Consumes: `check_duplicate`、`_persist_question`、`embedding_text`、`compute_stem_hash`、`get_embedding_client`
- Produces:
  - `AI_VARIANT_TAG = "AI变式"`
  - `create_generated_question(session, *, subject_id, stem_md, options_json, answer_md, analysis_md, qtype, difficulty, links, created_by, embedder=None) -> tuple[Question, bool]`
  - 语义：命中判重 → 返回既有题 + `False`；否则建题（`origin="ai"`、`verified=False`、`tags=["AI变式"]`）+ `True`，并 **commit**。

- [ ] **Step 1: 读现有测试的 fixture**

```powershell
cd backend
Select-String -Path tests/test_question_service.py -Pattern "^def |^class |^@pytest.fixture" | Select-Object -First 40
```

记下 session/embedding 假实现的名字（后面写测试要用同款）。

- [ ] **Step 2: 写失败测试**

在 `backend/tests/test_question_service.py` 末尾追加（若 fixture 名不同，按 Step 1 的实际情况改）：

```python
def test_create_generated_question_marks_ai_and_unverified(session, fake_embedder):
    from app.services import question_service as svc

    question, created = svc.create_generated_question(
        session,
        subject_id=7,
        stem_md="已知等差数列 $a_1=1$，公差 $d=2$，求 $a_7$。",
        options_json=None,
        answer_md="$13$",
        analysis_md="用通项公式得 13。",
        qtype="解答",
        difficulty=2,
        links=[(12, Decimal("1.000000"))],
        created_by=5,
        embedder=fake_embedder,
    )

    assert created is True
    assert question.origin == "ai"
    assert question.verified is False
    assert question.tags == ["AI变式"]
    assert question.embedding is not None


def test_create_generated_question_returns_existing_on_duplicate(session, fake_embedder):
    from app.services import question_service as svc

    first, created_first = svc.create_generated_question(
        session, subject_id=7, stem_md="求 $2+2$ 的值。", options_json=None,
        answer_md="$4$", analysis_md="直接相加。", qtype="解答", difficulty=1,
        links=[], created_by=5, embedder=fake_embedder,
    )
    second, created_second = svc.create_generated_question(
        session, subject_id=7, stem_md="求 $2+2$ 的值。", options_json=None,
        answer_md="$4$", analysis_md="直接相加。", qtype="解答", difficulty=1,
        links=[], created_by=5, embedder=fake_embedder,
    )

    assert created_first is True
    assert created_second is False
    assert second.id == first.id
```

- [ ] **Step 3: 跑测试确认失败**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_question_service.py -q -k generated
```

预期：`AttributeError: module ... has no attribute 'create_generated_question'`。

- [ ] **Step 4: 实现**

在 `backend/app/services/question_service.py` 常量区（`MANUAL_WEIGHT` 附近）加：

```python
AI_VARIANT_TAG = "AI变式"
```

在 `create_extracted_question` 之后新增：

```python
def create_generated_question(
    session: Session,
    *,
    subject_id: int,
    stem_md: str,
    options_json: list[dict] | None,
    answer_md: str,
    analysis_md: str | None,
    qtype: str,
    difficulty: int,
    links: list[tuple[int, Decimal]],
    created_by: int | None,
    embedder: EmbeddingClient | None = None,
) -> tuple[Question, bool]:
    """AI 变式题入库的唯一入口：origin/verified/tag 在这里写死，调用方不能改。

    判重走同一套两道闸：题库里已有同题就复用（created=False），
    这样用户重复点「存入题库」不会造出第二道一样的题（spec D-10）。
    """
    client = embedder or get_embedding_client()
    vec = client.encode([embedding_text(stem_md)])[0]
    duplicate = check_duplicate(
        session, subject_id=subject_id, stem_hash=compute_stem_hash(stem_md), vec=vec
    )
    if duplicate is not None:
        return duplicate, False
    question = _persist_question(
        session,
        subject_id=subject_id,
        origin=QuestionOrigin.AI.value,
        source_file_id=None,
        stem_md=stem_md,
        options_json=options_json,
        answer_md=answer_md,
        analysis_md=analysis_md,
        qtype=qtype,
        difficulty=difficulty,
        tags=[AI_VARIANT_TAG],
        verified=False,
        embedding=vec,
        created_by=created_by,
        links=links,
    )
    _commit(session)
    return question, True
```

- [ ] **Step 5: 跑测试确认通过**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_question_service.py -q
```

预期：全绿（含既有用例）。

- [ ] **Step 6: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/app/services/question_service.py backend/tests/test_question_service.py
git commit -m "feat(s4-4): AI 变式题入库入口（origin=ai、verified=false、判重复用）"
```

---

### Task 5: 服务层 `services/question_gen_service.py`

**Files:**
- Create: `backend/app/services/question_gen_service.py`
- Test: `backend/tests/test_question_gen_service.py`

**Interfaces:**
- Consumes: `app.ai.gen`（生成/复算/比对）、`app.services.question_service.create_generated_question`、`app.services.mistake_analysis_service`（仅 `has_analysis` 不直接用，用本地查询）、`app.services.task_service.create_task`（函数内延迟导入）
- Produces:
  - `TASK_GENERATE_VARIANTS = "mistake.variants"`
  - `MAX_VARIANTS = 3`、`MAX_ROUNDS = 2`、`MAX_TOTAL_CALLS = 12`、`MIN_STEM_CHARS = 10`
  - `enqueue_variants(session, *, owner, mistake_id, queue) -> AsyncTask`（无诊断/题干过短 → `ConflictError`；越权 → `NotFoundError`）
  - `run_generation(session, *, user_id, mistake_id) -> dict`（写 JSON，不 commit）
  - `accept_variant(session, *, owner, mistake_id, variant_id) -> tuple[Question, bool]`（commit）
  - `build_generation_context(session, *, question, analysis) -> GenerationContext`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_question_gen_service.py`（复用 S4-3 测试的 `FakeSession` 风格；`monkeypatch` 打桩 AI 层，禁止真实调用）：

```python
"""S4-4 变式题服务：触发校验、生成编排、入库幂等。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.ai.gen import GeneratedVariant, VerifyContext, VariantVerificationError
from app.core.exceptions import ConflictError, NotFoundError
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.services import question_gen_service as svc


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
        self.added: list[object] = []
        self.flushed = 0
        self.commits = 0

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        return self.scalar_results.pop(0) if self.scalar_results else None

    def execute(self, statement):
        return _Rows(self.rows_results.pop(0) if self.rows_results else [])

    def add(self, instance):
        if getattr(instance, "id", None) is None:
            instance.id = 901
        self.added.append(instance)

    def flush(self):
        self.flushed += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _mistake() -> Mistake:
    return Mistake(id=43, user_id=5, question_id=100, status="待订正", correct_streak=0)


def _question() -> Question:
    return Question(
        id=100, subject_id=7, stem_md="等差数列 $a_1=2$，公差 $d=3$，求 $a_{10}$。",
        stem_hash="h", qtype="解答", difficulty=2, origin="upload",
        answer_md="$29$", verified=True,
    )


def _analysis(**overrides) -> MistakeAnalysis:
    base = dict(
        id=7, mistake_id=43, cause_type="审题偏差", kp_ids=[12],
        model="qwen-plus", prompt_version="mistake_analyze_v2",
        similar_questions_json=None,
    )
    base.update(overrides)
    return MistakeAnalysis(**base)


def _session(*, analysis=None, question=None, mistake=None) -> FakeSession:
    mistake = mistake or _mistake()
    question = question or _question()
    analysis = analysis if analysis is not None else _analysis()
    return FakeSession(
        objects={
            (Mistake, 43): mistake,
            (Question, 100): question,
            (MistakeAnalysis, None): analysis,
        },
        scalar_results=[analysis],
    )


def _variant(answer="$13$") -> GeneratedVariant:
    return GeneratedVariant(
        stem_md="等差数列 $a_1=1$，公差 $d=2$，求 $a_7$。",
        options=None,
        answer_md=answer,
        analysis_md="用 $a_n=a_1+(n-1)d$ 得 $a_7=13$。",
        qtype="解答",
        difficulty=3,
    )


def test_enqueue_variants_requires_analysis(monkeypatch):
    monkeypatch.setattr(svc, "_load_owned", lambda *a, **k: (_mistake(), _question(), None))

    with pytest.raises(ConflictError, match="先完成错因诊断"):
        svc.enqueue_variants(FakeSession(), owner=type("U", (), {"id": 5})(), mistake_id=43, queue=object())


def test_enqueue_variants_rejects_short_stem(monkeypatch):
    short = _question()
    short.stem_md = "求值"
    monkeypatch.setattr(svc, "_load_owned", lambda *a, **k: (_mistake(), short, _analysis()))

    with pytest.raises(ConflictError, match="题干太短"):
        svc.enqueue_variants(FakeSession(), owner=type("U", (), {"id": 5})(), mistake_id=43, queue=object())


def test_enqueue_variants_creates_task(monkeypatch):
    created: dict = {}

    class _TaskService:
        @staticmethod
        def create_task(session, *, owner, name, payload, queue):
            created.update(name=name, payload=payload)
            return type("T", (), {"id": 88})()

    monkeypatch.setattr(svc, "_load_owned", lambda *a, **k: (_mistake(), _question(), _analysis()))
    monkeypatch.setattr("app.services.task_service.create_task", _TaskService.create_task)

    task = svc.enqueue_variants(
        FakeSession(), owner=type("U", (), {"id": 5})(), mistake_id=43, queue=object()
    )

    assert task.id == 88
    assert created["name"] == "mistake.variants"
    assert created["payload"] == {"user_id": 5, "mistake_id": 43}


def test_run_generation_keeps_only_passed_variants(monkeypatch):
    session = _session()

    # 假生成器按 ctx.count 返回（重生成时只补缺的条数），否则重生成轮会越补越多
    def _fake_generate(ctx, **kwargs):
        return [_variant("$13$"), _variant("$99$")][: ctx.count]

    # 第 1 轮：第一道复算一致、第二道不一致；第 2 轮补生成的那道复算一致
    answers = iter(["$13$", "$100$", "$13$"])
    monkeypatch.setattr(svc, "generate_variants", _fake_generate)
    monkeypatch.setattr(svc, "verify_answer", lambda ctx, **k: next(answers))

    summary = svc.run_generation(session, user_id=5, mistake_id=43)

    payload = session.objects[(MistakeAnalysis, None)].similar_questions_json
    assert summary["requested"] == 3
    assert summary["passed"] == 2
    assert summary["rejected"] == 1
    assert summary["rounds"] == 2
    assert payload["version"] == 1
    assert len(payload["items"]) == 2
    assert payload["items"][0]["answer_md"] == "$13$"
    assert payload["items"][0]["self_check"]["verified_answer_md"] == "$13$"
    assert payload["rejected"][0]["reason"]
    assert session.commits == 0  # 任务内不 commit


def test_run_generation_clamps_difficulty_around_original(monkeypatch):
    session = _session()
    monkeypatch.setattr(svc, "generate_variants", lambda ctx, **k: [_variant()][: ctx.count])
    monkeypatch.setattr(svc, "verify_answer", lambda ctx, **k: "$13$")

    svc.run_generation(session, user_id=5, mistake_id=43)

    payload = session.objects[(MistakeAnalysis, None)].similar_questions_json
    # 原题难度 2 → 允许 1..3；假生成器给的是 3，落在区间内不被改
    assert payload["items"][0]["difficulty"] == 3


def test_run_generation_marks_task_result_even_if_all_rejected(monkeypatch):
    session = _session()
    monkeypatch.setattr(svc, "generate_variants", lambda ctx, **k: [_variant("$1$")][: ctx.count])
    monkeypatch.setattr(svc, "verify_answer", lambda ctx, **k: "$2$")

    summary = svc.run_generation(session, user_id=5, mistake_id=43)

    payload = session.objects[(MistakeAnalysis, None)].similar_questions_json
    assert summary["passed"] == 0
    assert payload["items"] == []
    assert payload["stats"]["rejected"] >= 1
    assert payload["stats"]["rounds"] == 3  # 1 次生成 + 2 次重生成，之后放弃


def test_run_generation_treats_verification_error_as_rejected(monkeypatch):
    session = _session()

    def _boom(ctx, **kwargs):
        raise VariantVerificationError("炸了")

    monkeypatch.setattr(svc, "generate_variants", lambda ctx, **k: [_variant()])
    monkeypatch.setattr(svc, "verify_answer", _boom)

    summary = svc.run_generation(session, user_id=5, mistake_id=43)

    payload = session.objects[(MistakeAnalysis, None)].similar_questions_json
    assert summary["passed"] == 0
    assert payload["rejected"][0]["reason"] == "复算调用失败"


def test_accept_variant_creates_question_and_marks_json(monkeypatch):
    session = _session()
    payload = {
        "version": 1,
        "items": [
            {"variant_id": "abc12345", "stem_md": "求 $2+2$ 的值。", "options": None,
             "answer_md": "$4$", "analysis_md": "直接相加得 4。", "qtype": "解答",
             "difficulty": 1, "kp_ids": [12],
             "self_check": {"status": "passed", "attempts": 1},
             "accepted_question_id": None, "accepted_at": None}
        ],
        "rejected": [],
        "stats": {"requested": 1, "passed": 1, "rejected": 0, "rounds": 1},
    }
    session.objects[(MistakeAnalysis, None)].similar_questions_json = payload

    class _Created:
        id = 128

    captured: dict = {}

    def _fake_create(session, **kwargs):
        captured.update(kwargs)
        return _Created(), True

    monkeypatch.setattr(svc.question_service, "create_generated_question", _fake_create)
    monkeypatch.setattr(
        svc, "_kp_links", lambda session, question_id: [(12, Decimal("1.000000"))]
    )

    question, created = svc.accept_variant(
        session, owner=type("U", (), {"id": 5})(), mistake_id=43, variant_id="abc12345"
    )

    assert created is True and question.id == 128
    item = session.objects[(MistakeAnalysis, None)].similar_questions_json["items"][0]
    assert item["accepted_question_id"] == 128
    assert item["accepted_at"]
    assert session.commits == 1
    # 入库题继承原题的 subject 与知识点链接，创建者记为当前用户
    assert captured["subject_id"] == 7
    assert captured["created_by"] == 5
    assert captured["links"] == [(12, Decimal("1.000000"))]


def test_accept_variant_is_idempotent(monkeypatch):
    session = _session()
    payload = {
        "version": 1,
        "items": [
            {"variant_id": "abc12345", "stem_md": "求 $2+2$ 的值。", "options": None,
             "answer_md": "$4$", "analysis_md": "直接相加得 4。", "qtype": "解答",
             "difficulty": 1, "kp_ids": [12],
             "self_check": {"status": "passed", "attempts": 1},
             "accepted_question_id": 128, "accepted_at": "2026-11-03T10:00:00+00:00"}
        ],
        "rejected": [],
        "stats": {"requested": 1, "passed": 1, "rejected": 0, "rounds": 1},
    }
    session.objects[(MistakeAnalysis, None)].similar_questions_json = payload
    existing = _question()
    existing.id = 128
    session.objects[(Question, 128)] = existing
    monkeypatch.setattr(
        svc.question_service, "create_generated_question",
        lambda *a, **k: pytest.fail("已入库的变式题不应重复建题"),
    )

    question, created = svc.accept_variant(
        session, owner=type("U", (), {"id": 5})(), mistake_id=43, variant_id="abc12345"
    )

    assert created is False
    assert question.id == 128
    assert session.commits == 0


def test_accept_variant_unknown_id_404():
    session = _session()
    session.objects[(MistakeAnalysis, None)].similar_questions_json = {"version": 1, "items": []}

    with pytest.raises(NotFoundError, match="变式题不存在"):
        svc.accept_variant(
            session, owner=type("U", (), {"id": 5})(), mistake_id=43, variant_id="nope"
        )
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_question_gen_service.py -q
```

预期：`ModuleNotFoundError: app.services.question_gen_service`。

- [ ] **Step 3: 实现服务**

`backend/app/services/question_gen_service.py`：

```python
"""S4-4 变式题：触发、生成编排、入库（spec §6）。

三层：
- `enqueue_variants`：手动触发，先校验归属/诊断/题干，再建任务；
- `run_generation`：任务内用例，生成 → 逐题独立复算 → 比对 → 写 JSON，不 commit；
- `accept_variant`：把 JSON 里的一道题存进题库，回写 accepted 字段。

生成与复算是两次独立 LLM 调用（spec D-4）；比对在代码层做确定性判定（D-5）。
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gen import (
    MAX_VARIANTS,
    PROMPT_VERSION,
    GenerationContext,
    GeneratedVariant,
    VariantGenerationError,
    VariantVerificationError,
    VerifyContext,
    generate_variants,
    match_answers,
    verify_answer,
)
from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.knowledge_point import KnowledgePoint
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.user import User
from app.services import question_service

if TYPE_CHECKING:  # 顶层导入 app.tasks 会与「任务注册表 ↔ service 常量」互相循环（同 S4-3）
    from app.tasks.queue import TaskQueue

logger = logging.getLogger(__name__)

TASK_GENERATE_VARIANTS = "mistake.variants"
MAX_ROUNDS = 2
MAX_TOTAL_CALLS = 12
MIN_STEM_CHARS = 10
KP_LIMIT = 3
STEM_LIMIT = 2000
EXCERPT_LIMIT = 80


def _load_owned(
    session: Session, *, user_id: int, mistake_id: int
) -> tuple[Mistake, Question, MistakeAnalysis | None]:
    mistake = session.get(Mistake, mistake_id)
    if mistake is None or mistake.user_id != user_id:
        raise NotFoundError("错题不存在")
    question = session.get(Question, mistake.question_id)
    if question is None:
        raise NotFoundError("题目不存在")
    analysis = session.scalar(
        select(MistakeAnalysis).where(MistakeAnalysis.mistake_id == mistake_id)
    )
    return mistake, question, analysis


def _kp_names(session: Session, question_id: int) -> list[str]:
    stmt = (
        select(KnowledgePoint.name)
        .join(QuestionKp, QuestionKp.kp_id == KnowledgePoint.id)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc(), KnowledgePoint.id)
        .limit(KP_LIMIT)
    )
    return [name for name in session.scalars(stmt).all() if name]


def _kp_links(session: Session, question_id: int) -> list[tuple[int, Decimal]]:
    """变式题继承原题的知识点链接（spec D-11）：不重新对齐，避免与例题不一致。"""
    stmt = (
        select(QuestionKp.kp_id, QuestionKp.weight)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc(), QuestionKp.kp_id)
    )
    return [(row[0], row[1]) for row in session.execute(stmt).all()]


def build_generation_context(
    session: Session, *, question: Question, analysis: MistakeAnalysis | None
) -> GenerationContext:
    return GenerationContext(
        stem_md=question.stem_md[:STEM_LIMIT],
        options=[(item.get("key", ""), item.get("text", "")) for item in (question.options_json or [])],
        correct_answer_md=question.answer_md,
        kp_names=_kp_names(session, question.id),
        cause_type=analysis.cause_type if analysis is not None else None,
        qtype=question.qtype,
        difficulty=question.difficulty,
        count=MAX_VARIANTS,
    )


def enqueue_variants(
    session: Session, *, owner: User, mistake_id: int, queue: TaskQueue
) -> Any:
    _mistake, question, analysis = _load_owned(session, user_id=owner.id, mistake_id=mistake_id)
    if analysis is None:
        raise ConflictError("请先完成错因诊断")
    if len((question.stem_md or "").strip()) < MIN_STEM_CHARS:
        raise ConflictError("这道题题干太短，暂不支持生成变式")
    from app.services import task_service  # 延迟导入，避免与 app.tasks 循环

    return task_service.create_task(
        session,
        owner=owner,
        name=TASK_GENERATE_VARIANTS,
        payload={"user_id": owner.id, "mistake_id": mistake_id},
        queue=queue,
    )


def _clamp_difficulty(original: int, value: int) -> int:
    """变式题难度锁在原题 ±1（spec D-7）；模型偶尔越界，这里收口，不因此弃题。"""
    low = max(1, original - 1)
    high = min(5, original + 1)
    return min(max(value, low), high)


def _item_payload(
    variant: GeneratedVariant, *, verified: str, kp_ids: list[int], attempts: int, original_difficulty: int
) -> dict:
    return {
        "variant_id": secrets.token_hex(4),
        "stem_md": variant.stem_md,
        "options": [option.model_dump() for option in variant.options] if variant.options else None,
        "answer_md": variant.answer_md,
        "analysis_md": variant.analysis_md,
        "qtype": variant.qtype,
        "difficulty": _clamp_difficulty(original_difficulty, variant.difficulty),
        "kp_ids": kp_ids,
        "self_check": {"status": "passed", "attempts": attempts, "verified_answer_md": verified},
        "accepted_question_id": None,
        "accepted_at": None,
    }


def run_generation(session: Session, *, user_id: int, mistake_id: int) -> dict[str, Any]:
    """一次生成用例：不 commit（由任务 runner 提交/回滚）。"""
    started = time.monotonic()
    _mistake, question, analysis = _load_owned(
        session, user_id=user_id, mistake_id=mistake_id
    )
    if analysis is None:
        raise NotFoundError("错题诊断不存在")
    base = build_generation_context(session, question=question, analysis=analysis)
    kp_ids = list(analysis.kp_ids or [])

    passed: list[dict] = []
    rejected: list[dict] = []
    rounds = 0
    calls = 0
    pending = MAX_VARIANTS
    while pending > 0 and rounds <= MAX_ROUNDS and calls < MAX_TOTAL_CALLS:
        rounds += 1
        try:
            variants = generate_variants(replace(base, count=pending))
            calls += 1
        except VariantGenerationError as exc:
            logger.warning(
                "variant_generate_failed mistake_id=%s rounds=%s error=%s", mistake_id, rounds, exc
            )
            # 一道都没通过时不能静默返回空结果：让任务 failed，旧 JSON 保持不变（spec §5.5）
            if not passed:
                raise
            break
        failed: list[GeneratedVariant] = []
        for variant in variants:
            if calls >= MAX_TOTAL_CALLS:
                failed.append(variant)
                continue
            try:
                verified = verify_answer(
                    VerifyContext(
                        stem_md=variant.stem_md,
                        options=[(option.key, option.text) for option in (variant.options or [])],
                    )
                )
                calls += 1
            except VariantVerificationError as exc:
                calls += 1
                logger.warning(
                    "variant_verify_failed mistake_id=%s error=%s", mistake_id, exc
                )
                rejected.append({"reason": "复算调用失败", "stem_excerpt": variant.stem_md[:EXCERPT_LIMIT]})
                failed.append(variant)
                continue
            ok, reason = match_answers(variant.answer_md, verified)
            if ok:
                passed.append(
                    _item_payload(
                        variant,
                        verified=verified,
                        kp_ids=kp_ids,
                        attempts=rounds,
                        original_difficulty=base.difficulty,
                    )
                )
                continue
            logger.warning(
                "variant_self_check_rejected mistake_id=%s reason=%s stem_excerpt=%s",
                mistake_id,
                reason,
                variant.stem_md[:EXCERPT_LIMIT],
            )
            rejected.append({"reason": reason, "stem_excerpt": variant.stem_md[:EXCERPT_LIMIT]})
            failed.append(variant)
        pending = min(len(failed), MAX_VARIANTS - len(passed))

    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": get_settings().llm_model,
        "prompt_version": PROMPT_VERSION,
        "stats": {
            "requested": MAX_VARIANTS,
            "passed": len(passed),
            "rejected": len(rejected),
            "rounds": rounds,
        },
        "items": passed,
        "rejected": rejected[:9],
    }
    analysis.similar_questions_json = payload
    session.flush()
    return {
        "mistake_id": mistake_id,
        "requested": MAX_VARIANTS,
        "passed": len(passed),
        "rejected": len(rejected),
        "rounds": rounds,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def accept_variant(
    session: Session, *, owner: User, mistake_id: int, variant_id: str
) -> tuple[Question, bool]:
    _mistake, question, analysis = _load_owned(session, user_id=owner.id, mistake_id=mistake_id)
    if analysis is None or not isinstance(analysis.similar_questions_json, dict):
        raise NotFoundError("变式题不存在或已被重新生成")
    payload = analysis.similar_questions_json
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
    target = next((item for item in items if item.get("variant_id") == variant_id), None)
    if target is None:
        raise NotFoundError("变式题不存在或已被重新生成")
    accepted_id = target.get("accepted_question_id")
    if accepted_id:
        existing = session.get(Question, int(accepted_id))
        if existing is not None:
            return existing, False
    created_question, created = question_service.create_generated_question(
        session,
        subject_id=question.subject_id,
        stem_md=str(target["stem_md"]),
        options_json=target.get("options"),
        answer_md=str(target["answer_md"]),
        analysis_md=target.get("analysis_md"),
        qtype=str(target["qtype"]),
        difficulty=int(target["difficulty"]),
        links=_kp_links(session, question.id),
        created_by=owner.id,
    )
    target["accepted_question_id"] = created_question.id
    target["accepted_at"] = datetime.now(timezone.utc).isoformat()
    # JSONB 默认不做脏检查，必须整体重新赋值才会写库
    analysis.similar_questions_json = {**payload, "items": items}
    session.commit()
    return created_question, created
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_question_gen_service.py -q
```

预期：8 条全绿。若 `_session()` 的 `scalar_results` 顺序与 `_load_owned` 调用次数不匹配，按实际调整（实现里每次 `run_generation` 只调一次 `scalar`）。

- [ ] **Step 5: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/app/services/question_gen_service.py backend/tests/test_question_gen_service.py
git commit -m "feat(s4-4): 变式题服务（手动触发、生成编排、自检过滤、确认入库）"
```

---

### Task 6: 任务 `mistake.variants` + 注册

**Files:**
- Create: `backend/app/tasks/generate_variants.py`
- Modify: `backend/app/tasks/__init__.py`
- Test: `backend/tests/test_question_gen_task.py`

**Interfaces:**
- Consumes: `question_gen_service.run_generation`、`question_gen_service.TASK_GENERATE_VARIANTS`
- Produces: 注册项 `mistake.variants`，handler `(Session, payload) -> dict`，不 commit

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_question_gen_task.py`：

```python
"""S4-4 变式任务：注册名、参数透传、不 commit。"""
from __future__ import annotations

from app.tasks import generate_variants as task_module
from app.tasks.registry import get_handler


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_variant_task_registered():
    assert get_handler("mistake.variants") is task_module.run_generate_variants


def test_variant_task_delegates_and_does_not_commit(monkeypatch):
    calls: dict = {}

    def _fake(session, *, user_id, mistake_id):
        calls.update(user_id=user_id, mistake_id=mistake_id)
        return {"mistake_id": mistake_id, "passed": 2}

    monkeypatch.setattr(task_module.question_gen_service, "run_generation", _fake)
    session = FakeSession()

    result = task_module.run_generate_variants(session, {"user_id": 5, "mistake_id": 43})

    assert result["passed"] == 2
    assert calls == {"user_id": 5, "mistake_id": 43}
    assert session.commits == 0
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_question_gen_task.py -q
```

预期：`ModuleNotFoundError: app.tasks.generate_variants`。

- [ ] **Step 3: 实现任务模块**

`backend/app/tasks/generate_variants.py`：

```python
"""S4-4 变式题生成任务：handler 不 commit，由 runner 统一提交/回滚。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services import question_gen_service
from app.services.question_gen_service import TASK_GENERATE_VARIANTS
from app.tasks.registry import register


@register(TASK_GENERATE_VARIANTS)
def run_generate_variants(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    return question_gen_service.run_generation(
        session,
        user_id=int(payload["user_id"]),
        mistake_id=int(payload["mistake_id"]),
    )
```

- [ ] **Step 4: 注册进任务包**

`backend/app/tasks/__init__.py`：在 import 区加一行，并补进 `__all__`：

```python
from app.tasks import generate_variants as _generate_variants  # noqa: F401  注册 mistake.variants
```

`__all__` 插到 `_demo` 之前保持字母序：`"_analyze_mistake", "_demo", "_generate_variants", ...`。

- [ ] **Step 5: 跑测试确认通过**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_question_gen_task.py -q
```

预期：2 条全绿。

- [ ] **Step 6: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/app/tasks/generate_variants.py backend/app/tasks/__init__.py backend/tests/test_question_gen_task.py
git commit -m "feat(s4-4): mistake.variants 任务与注册"
```

---

### Task 7: 接口（生成 / 入库）+ DTO 扩展

**Files:**
- Modify: `backend/app/schemas/mistake.py`（`MistakeVariantOut`、`VariantsStatsOut`、`VariantAcceptOut`、`MistakeAnalysisOut` 两字段）
- Modify: `backend/app/services/mistake_service.py`（`_analysis_of` 映射 variants）
- Modify: `backend/app/api/v1/mistakes.py`（+2 路由）
- Test: `backend/tests/test_mistakes_api.py`（追加）

**Interfaces:**
- Consumes: `question_gen_service.{enqueue_variants, accept_variant}`
- Produces:
  - `POST /api/v1/mistakes/{id}/variants` → 202 `Envelope[TaskOut]`
  - `POST /api/v1/mistakes/{id}/variants/{variant_id}/accept` → 200 `Envelope[VariantAcceptOut]`
  - `MistakeAnalysisOut.similar_questions` / `.variants_stats`

- [ ] **Step 1: 写 DTO**

在 `backend/app/schemas/mistake.py` 的 `MistakeAnalysisOut` 之前插入：

```python
class MistakeVariantOut(BaseModel):
    variant_id: str
    stem_md: str
    options: list[OptionOut] | None = None
    answer_md: str
    analysis_md: str | None = None
    qtype: str
    difficulty: int
    self_check: str = "passed"
    accepted_question_id: int | None = None


class VariantsStatsOut(BaseModel):
    requested: int
    passed: int
    rejected: int
    rounds: int
    generated_at: datetime | None = None


class VariantAcceptOut(BaseModel):
    question_id: int
    created: bool
```

`MistakeAnalysisOut` 末尾（`created_at` 之前）加：

```python
    similar_questions: list[MistakeVariantOut] | None = None
    variants_stats: VariantsStatsOut | None = None
```

- [ ] **Step 2: 写映射**

在 `backend/app/services/mistake_service.py` 的 `_analysis_of` 里，`return MistakeAnalysisOut(...)` 前加：

```python
    variants = _variants_of(analysis.similar_questions_json)
```

并把 `similar_questions=variants[0], variants_stats=variants[1]` 传进构造；在 `_analysis_of` 之后新增：

```python
def _flatten_self_check(raw: dict) -> dict:
    """JSONB 里 self_check 是对象（带 attempts/verified_answer_md），出参只要状态字符串。"""
    data = dict(raw)
    check = data.get("self_check")
    if isinstance(check, dict):
        data["self_check"] = str(check.get("status") or "passed")
    elif not isinstance(check, str):
        data["self_check"] = "passed"
    return data


def _variants_of(payload: object) -> tuple[list[MistakeVariantOut] | None, VariantsStatsOut | None]:
    """从 JSONB 读变式题；结构版本不认识就当作没有（向前兼容，不抛错）。"""
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None, None
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return None, None
    items: list[MistakeVariantOut] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            items.append(MistakeVariantOut.model_validate(_flatten_self_check(raw)))
        except ValidationError:
            continue
    stats_raw = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    stats = VariantsStatsOut(
        requested=int(stats_raw.get("requested", 0)),
        passed=int(stats_raw.get("passed", 0)),
        rejected=int(stats_raw.get("rejected", 0)),
        rounds=int(stats_raw.get("rounds", 0)),
        generated_at=payload.get("generated_at"),
    )
    return items, stats
```

需要的 import：`from pydantic import ValidationError`（放文件顶部 import 区），以及 DTO 名。

- [ ] **Step 3: 写路由**

在 `backend/app/api/v1/mistakes.py` 的 `trigger_mistake_analysis` 之后、`review_mistake` 之前插入：

```python
@router.post("/{mistake_id}/variants", status_code=202, response_model=Envelope[TaskOut], summary="生成变式题")
def generate_mistake_variants(
    mistake_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    task = question_gen_service.enqueue_variants(
        session, owner=current_user, mistake_id=mistake_id, queue=queue
    )
    return Envelope(trace_id=get_trace_id(), data=TaskOut.model_validate(task))


@router.post(
    "/{mistake_id}/variants/{variant_id}/accept",
    response_model=Envelope[VariantAcceptOut],
    summary="变式题存入题库",
)
def accept_mistake_variant(
    mistake_id: int,
    variant_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[VariantAcceptOut]:
    question, created = question_gen_service.accept_variant(
        session, owner=current_user, mistake_id=mistake_id, variant_id=variant_id
    )
    return Envelope(
        trace_id=get_trace_id(),
        data=VariantAcceptOut(question_id=question.id, created=created),
    )
```

并在 import 区补 `VariantAcceptOut` 与 `question_gen_service`：

```python
from app.schemas.mistake import (..., VariantAcceptOut, ...)
from app.services import mistake_analysis_service, mistake_service, question_gen_service
```

- [ ] **Step 4: 写接口测试**

在 `backend/tests/test_mistakes_api.py` 末尾追加（沿用该文件既有的 client/token/queue fixture；先 `Select-String` 看它怎么注入假队列）：

```python
def test_generate_variants_returns_202(client, auth_headers, fake_queue, monkeypatch):
    monkeypatch.setattr(
        "app.services.question_gen_service.enqueue_variants",
        lambda session, *, owner, mistake_id, queue: type(
            "T", (), {"id": 77, "status": "pending", "name": "mistake.variants", "result": None,
                      "error": None, "created_at": None, "finished_at": None, "attempts": 0}()
        )(),
    )

    resp = client.post("/api/v1/mistakes/43/variants", headers=auth_headers)

    assert resp.status_code == 202
    assert resp.json()["data"]["id"] == 77


def test_generate_variants_409_without_analysis(client, auth_headers, fake_queue, monkeypatch):
    from app.core.exceptions import ConflictError

    def _boom(*args, **kwargs):
        raise ConflictError("请先完成错因诊断")

    monkeypatch.setattr("app.services.question_gen_service.enqueue_variants", _boom)

    resp = client.post("/api/v1/mistakes/43/variants", headers=auth_headers)

    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


def test_accept_variant_returns_question_id(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.services.question_gen_service.accept_variant",
        lambda session, *, owner, mistake_id, variant_id: (type("Q", (), {"id": 128})(), True),
    )

    resp = client.post("/api/v1/mistakes/43/variants/abc12345/accept", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["data"] == {"question_id": 128, "created": True}


def test_accept_variant_404(client, auth_headers, monkeypatch):
    from app.core.exceptions import NotFoundError

    def _boom(*args, **kwargs):
        raise NotFoundError("变式题不存在或已被重新生成")

    monkeypatch.setattr("app.services.question_gen_service.accept_variant", _boom)

    resp = client.post("/api/v1/mistakes/43/variants/nope/accept", headers=auth_headers)

    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_detail_exposes_variants(client, auth_headers, monkeypatch):
    # 详情 DTO 的映射由 test_mistake_variants_dto.py 覆盖（见下）；
    # 这里只锁「接口把 analysis 里的字段原样吐出来」这一层：假 service 返回带变式题的详情。
    from datetime import datetime, timezone

    from app.schemas.mistake import (
        MistakeAnalysisOut,
        MistakeDetailOut,
        MistakeVariantOut,
        VariantsStatsOut,
    )

    detail = MistakeDetailOut(
        id=43,
        question_id=100,
        status="待订正",
        correct_streak=0,
        stem_excerpt="等差数列求项",
        subject_id=7,
        qtype="解答",
        difficulty=2,
        created_at=datetime.now(timezone.utc),
        stem_md="等差数列 $a_1=2$，公差 $d=3$，求 $a_{10}$。",
        analysis=MistakeAnalysisOut(
            cause_type="计算失误",
            created_at=datetime.now(timezone.utc),
            similar_questions=[
                MistakeVariantOut(
                    variant_id="abc12345",
                    stem_md="求 $2+2$ 的值。",
                    answer_md="$4$",
                    qtype="解答",
                    difficulty=2,
                )
            ],
            variants_stats=VariantsStatsOut(
                requested=3, passed=1, rejected=2, rounds=2, generated_at=None
            ),
        ),
    )
    monkeypatch.setattr(
        "app.services.mistake_service.get_detail", lambda session, *, owner_id, mistake_id: detail
    )

    resp = client.get("/api/v1/mistakes/43", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()["data"]["analysis"]
    assert body["similar_questions"][0]["variant_id"] == "abc12345"
    assert body["variants_stats"]["rejected"] == 2
```

新建 `backend/tests/test_mistake_variants_dto.py`（这两条直接测纯函数，不依赖 DB）：

```python
"""S4-4 详情 DTO：JSONB → similar_questions / variants_stats 的映射与向前兼容。"""
from __future__ import annotations

from app.services.mistake_service import _variants_of

PAYLOAD = {
    "version": 1,
    "generated_at": "2026-11-03T14:02:11+00:00",
    "model": "qwen-plus",
    "prompt_version": "question_gen_v1",
    "stats": {"requested": 3, "passed": 2, "rejected": 1, "rounds": 2},
    "items": [
        {
            "variant_id": "abc12345",
            "stem_md": "求 $2+2$ 的值。",
            "options": None,
            "answer_md": "$4$",
            "analysis_md": "直接相加。",
            "qtype": "解答",
            "difficulty": 2,
            "kp_ids": [12],
            "self_check": {"status": "passed", "attempts": 1},
            "accepted_question_id": None,
            "accepted_at": None,
        }
    ],
    "rejected": [],
}


def test_variants_of_maps_items_and_stats():
    items, stats = _variants_of(PAYLOAD)

    assert items is not None and items[0].variant_id == "abc12345"
    assert items[0].difficulty == 2
    assert stats is not None
    assert (stats.requested, stats.passed, stats.rejected, stats.rounds) == (3, 2, 1, 2)


def test_variants_of_returns_none_for_unknown_version():
    assert _variants_of({**PAYLOAD, "version": 2}) == (None, None)
    assert _variants_of(None) == (None, None)
    assert _variants_of({}) == (None, None)


def test_variants_of_skips_malformed_items():
    broken = {**PAYLOAD, "items": [{"variant_id": "x"}]}  # 缺 stem/answer

    items, _stats = _variants_of(broken)

    assert items == []
```

- [ ] **Step 5: 跑接口测试**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_mistakes_api.py tests/test_mistake_variants_dto.py -q
```

预期：全绿。

- [ ] **Step 6: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/app/schemas/mistake.py backend/app/services/mistake_service.py backend/app/api/v1/mistakes.py backend/tests/test_mistakes_api.py backend/tests/test_mistake_variants_dto.py
git commit -m "feat(s4-4): 变式题生成/入库接口与详情 DTO 扩展"
```

---

### Task 8: 前端类型 / API / 变式训练区 / 单测

**Files:**
- Modify: `web/src/types/mistakes.ts`
- Modify: `web/src/api/mistakes.ts`
- Modify: `web/src/views/mistakes/MistakeDetailView.vue`
- Test: `web/src/views/mistakes/__tests__/MistakeDetailView.spec.ts`

**Interfaces:**
- Consumes: `GET /tasks/{id}`（既有 `getTask`）、`POST /mistakes/{id}/variants`、`POST /mistakes/{id}/variants/{vid}/accept`
- Produces: `MistakeVariant`、`VariantsStats`、`VariantAcceptResult`、`generateVariants(id)`、`acceptVariant(id, variantId)`

- [ ] **Step 1: 扩展类型**

`web/src/types/mistakes.ts`：

```ts
/** S4-4 变式题（MistakeVariantOut） */
export interface MistakeVariant {
  variant_id: string
  stem_md: string
  options: MistakeOption[] | null
  answer_md: string
  analysis_md: string | null
  qtype: string
  difficulty: number
  self_check: string
  accepted_question_id: number | null
}

export interface VariantsStats {
  requested: number
  passed: number
  rejected: number
  rounds: number
  generated_at: string | null
}

export interface VariantAcceptResult {
  question_id: number
  created: boolean
}
```

`MistakeAnalysis` 加两个字段：

```ts
  similar_questions: MistakeVariant[] | null
  variants_stats: VariantsStats | null
```

- [ ] **Step 2: 扩展 API 封装**

`web/src/api/mistakes.ts` 末尾：

```ts
/** S4-4 生成变式题（异步任务，用 getTask 轮询）。 */
export async function generateVariants(id: number): Promise<TaskOut> {
  const resp = await http.post<ApiEnvelope<TaskOut>>(`${API_PREFIX}/mistakes/${id}/variants`)
  return resp.data.data
}

/** S4-4 把一道变式题存进题库；重复调用返回同一 question_id + created=false。 */
export async function acceptVariant(id: number, variantId: string): Promise<VariantAcceptResult> {
  const resp = await http.post<ApiEnvelope<VariantAcceptResult>>(
    `${API_PREFIX}/mistakes/${id}/variants/${variantId}/accept`,
  )
  return resp.data.data
}
```

import 区补 `TaskOut` 与 `VariantAcceptResult`（文件已有 `TaskOut` 的话只补类型）。

- [ ] **Step 3: 写组件逻辑（script）**

`MistakeDetailView.vue` 中：

1. 删掉占位：`similar_questions_json?: unknown`（第 40 行附近）与 `similarQuestions` computed（第 67-72 行）。
2. import 补：`acceptVariant, generateVariants` 与类型 `MistakeVariant`。
3. 在诊断轮询逻辑之后加一组（与 `startAnalyze` 同款结构）：

```ts
const generating = ref(false)
const generateError = ref('')
const generateTaskId = ref<number | null>(null)
const generateSeconds = ref(0)
const accepting = ref<string | null>(null)
let generateTimer: ReturnType<typeof setInterval> | null = null

const variants = computed<MistakeVariant[]>(() => analysis.value?.similar_questions ?? [])
const variantsStats = computed(() => analysis.value?.variants_stats ?? null)
const canGenerate = computed(() => analysis.value !== null && !generating.value)

function stopGeneratePolling(): void {
  if (generateTimer !== null) {
    clearInterval(generateTimer)
    generateTimer = null
  }
}

function resetGenerateState(): void {
  stopGeneratePolling()
  generateSeconds.value = 0
  generateTaskId.value = null
}

async function pollGenerate(): Promise<void> {
  const taskId = generateTaskId.value
  if (taskId === null || !generating.value) return
  try {
    const task = await getTask(taskId)
    if (!generating.value) return
    if (task.status === 'succeeded') {
      resetGenerateState()
      generating.value = false
      await load()
      return
    }
    if (task.status === 'failed') {
      generateError.value = task.error || '生成失败，可重试'
      resetGenerateState()
      generating.value = false
    }
  } catch {
    resetGenerateState()
    generating.value = false
  }
}

async function startVariants(): Promise<void> {
  if (generating.value || detail.value === null) return
  generateError.value = ''
  generating.value = true
  try {
    const task = await generateVariants(detail.value.id)
    generateTaskId.value = task.id
    generateSeconds.value = 0
    generateTimer = setInterval(() => {
      generateSeconds.value += 4
      void pollGenerate()
    }, 4000)
  } catch {
    generating.value = false
    generateError.value = '发起生成失败，请稍后重试'
  }
}

async function acceptOne(variant: MistakeVariant): Promise<void> {
  if (accepting.value !== null || detail.value === null) return
  accepting.value = variant.variant_id
  try {
    const result = await acceptVariant(detail.value.id, variant.variant_id)
    ElMessage.success(result.created ? `已存入题库 #${result.question_id}` : `题库已有这道题 #${result.question_id}`)
    await load()
  } catch {
    // http.ts 已统一提示
  } finally {
    accepting.value = null
  }
}
```

4. `onBeforeUnmount` 里补 `stopGeneratePolling()`。

- [ ] **Step 4: 写模板**

在诊断卡 `</el-card>` 之后插入：

```vue
      <el-card shadow="never" class="card" data-testid="variants">
        <template #header>
          <div class="section-head">
            <span>变式训练</span>
            <el-button
              v-if="analysis && variants.length"
              size="small"
              data-testid="regenerate-variants"
              :loading="generating"
              :disabled="generating"
              @click="startVariants"
            >
              重新生成
            </el-button>
          </div>
        </template>

        <el-alert v-if="generateError" type="error" :title="generateError" :closable="false" show-icon />

        <div v-if="generating" class="analyzing" data-testid="variants-loading">
          <span class="spinner" aria-hidden="true" />
          生成并自检中…已等待 {{ generateSeconds }} 秒
        </div>

        <template v-else-if="variants.length">
          <el-text v-if="variantsStats && variantsStats.rejected > 0" size="small" data-testid="variants-rejected">
            本次有 {{ variantsStats.rejected }} 道未通过自检，已丢弃
          </el-text>
          <div
            v-for="(variant, index) in variants"
            :key="variant.variant_id"
            class="variant-card"
            :data-testid="`variant-${variant.variant_id}`"
          >
            <div class="cause-row">
              <el-tag size="small" type="info" effect="plain">第 {{ index + 1 }} 题</el-tag>
              <el-tag size="small" effect="plain">{{ variant.qtype }}</el-tag>
              <el-tag size="small" type="success" effect="plain">难度 {{ variant.difficulty }}</el-tag>
              <el-tag size="small" type="success">已复算通过</el-tag>
              <span class="spacer" />
              <el-button
                v-if="variant.accepted_question_id === null"
                size="small"
                type="primary"
                :data-testid="`accept-variant-${variant.variant_id}`"
                :loading="accepting === variant.variant_id"
                :disabled="accepting !== null"
                @click="acceptOne(variant)"
              >
                存入题库
              </el-button>
              <el-tag v-else size="small" type="info" :data-testid="`accepted-${variant.variant_id}`">
                已入库 #{{ variant.accepted_question_id }}
              </el-tag>
            </div>
            <MdPreview :model-value="variant.stem_md" :no-mermaid="true" preview-theme="github" />
            <el-collapse>
              <el-collapse-item title="查看答案" :name="`answer-${variant.variant_id}`">
                <MdPreview :model-value="variant.answer_md" :no-mermaid="true" preview-theme="github" />
                <MdPreview
                  v-if="variant.analysis_md"
                  :model-value="variant.analysis_md"
                  :no-mermaid="true"
                  preview-theme="github"
                />
              </el-collapse-item>
            </el-collapse>
          </div>
        </template>

        <el-empty v-else-if="analysis" description="还没有变式题">
          <el-button
            type="primary"
            data-testid="generate-variants"
            :disabled="!canGenerate"
            @click="startVariants"
          >
            生成变式题
          </el-button>
        </el-empty>

        <el-empty v-else description="先完成错因诊断，再生成变式题" />
      </el-card>
```

样式补到 `<style scoped>`：

```css
.variant-card {
  border-top: 1px solid var(--app-border);
  padding: 12px 0;
}
.spacer {
  flex: 1;
}
```

- [ ] **Step 5: 写前端单测**

在 `web/src/views/mistakes/__tests__/MistakeDetailView.spec.ts` 追加（按文件里既有的 mock 方式 mock `generateVariants` / `acceptVariant` / `getTask`）：

```ts
it('有诊断但无变式题时显示生成按钮', async () => {
  // 既有 fixture 造 analysis（similar_questions: null, variants_stats: null）
  // 断言 getByTestId('generate-variants') 存在且未 disabled
})

it('渲染变式题卡片与自检徽标', async () => {
  // analysis.similar_questions = [variantFixture()]
  // 断言 getByTestId('variant-<id>') 存在、文案含「已复算通过」与「难度 3」
})

it('rejected > 0 时显示丢弃提示', async () => {
  // variants_stats = {requested:3, passed:2, rejected:1, rounds:2, generated_at: null}
  // 断言 getByTestId('variants-rejected') 文案含「1 道未通过自检」
})

it('已入库的变式题显示已入库 #id 且没有按钮', async () => {
  // variant.accepted_question_id = 128
  // 断言 getByTestId('accepted-<id>') 文案含 '#128'，且 getByTestId('accept-variant-<id>') 不存在
})

it('点击存入题库调用 acceptVariant 并刷新详情', async () => {
  // click accept-variant-<id>；断言 acceptVariant 被调用 (mistakeId, variantId)，且 getMistake 再次调用
})

it('点击生成变式题调用 generateVariants 并进入轮询态', async () => {
  // click generate-variants；断言 generateVariants 被调用、getByTestId('variants-loading') 出现
})

it('无诊断时不显示生成按钮', async () => {
  // analysis = null；断言 getByTestId('generate-variants') 为空，且文案含「先完成错因诊断」
})
```

- [ ] **Step 6: 跑前端测试与构建**

```powershell
cd web
$env:NODE_OPTIONS="--require E:\BiShe-AIStudy\.sdd\tools\dsh-exec-patch.cjs"
npm run test:run -- --pool=threads
npm run build
```

预期：全部通过；build exit 0。

- [ ] **Step 7: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add web/src/types/mistakes.ts web/src/api/mistakes.ts web/src/views/mistakes/MistakeDetailView.vue web/src/views/mistakes/__tests__/MistakeDetailView.spec.ts
git commit -m "feat(s4-4): 详情页变式训练区（生成/重新生成/逐题入库/自检徽标）"
```

---

### Task 9: 真机验收（21 道生成 + 手算核对 + 入库 + 证据）

**Files:**
- Create: `.sdd/s4-4/accept_s4_4.py`（不入 git）
- Create: `.sdd/s4-4/acceptance-evidence.md`（不入 git）
- Create: `.sdd/s4-4/variants.json`（生成结果快照，不入 git）

**Interfaces:**
- Consumes: 运行中的 `uvicorn :8031` + ARQ worker（**验收前确认只有一个 worker 在消费 Redis**，S4-3 吃过旧进程的亏）

- [ ] **Step 1: 起服务（用受管后台任务，不要 `Start-Process`）**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8031
```

另起一个后台任务跑：

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python.exe -m arq app.tasks.worker.WorkerSettings
```

验证只有一个消费者：

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python.exe -c "import redis; c=redis.Redis(host='127.0.0.1',port=6379,db=0); print([l for l in c.execute_command('CLIENT','LIST').decode().splitlines() if 'cmd=' in l])"
```

- [ ] **Step 2: 写验收脚本**

`.sdd/s4-4/accept_s4_4.py`：

```python
"""S4-4 真机验收：7 道错题各生成 3 道变式题，收集结果供人工核对答案。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8031/api/v1"
USER, PWD = "s43_accept_20261103", "accept-pass-2026"
OUT = Path(r"E:\BiShe-AIStudy\.sdd\s4-4\variants.json")
# 错题 id 直接从 DB 取（S4-3 的验收账号 + 已有诊断），不依赖测试数据 JSON 的字段名
WANT = 7


def _mistake_ids(session, username: str) -> list[int]:
    from sqlalchemy import text

    rows = session.execute(
        text(
            """
            select m.id
            from mistakes m
            join users u on u.id = m.user_id
            join mistake_analyses a on a.mistake_id = m.id
            where u.username = :username
            order by m.id
            limit :limit
            """
        ),
        {"username": username, "limit": WANT},
    ).all()
    return [row[0] for row in rows]


def login(c: httpx.Client) -> dict[str, str]:
    resp = c.post(f"{BASE}/auth/login", json={"username": USER, "password": PWD})
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def wait_task(c: httpx.Client, h: dict[str, str], task_id: int, timeout: float = 300.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = c.get(f"{BASE}/tasks/{task_id}", headers=h).json()["data"]
        if task["status"] in {"succeeded", "failed"}:
            return task
        time.sleep(4)
    raise TimeoutError(f"任务 {task_id} 超时")


def main() -> int:
    from app.core.db import new_session

    with new_session() as session:
        mistake_ids = _mistake_ids(session, USER)
    if len(mistake_ids) < WANT:
        print(f"只有 {len(mistake_ids)} 道已有诊断的错题，验收样本不足")
        return 2
    rows: list[dict] = []
    with httpx.Client(timeout=60.0) as c:
        h = login(c)
        for mid in mistake_ids:
            started = time.monotonic()
            resp = c.post(f"{BASE}/mistakes/{mid}/variants", headers=h)
            if resp.status_code != 202:
                rows.append({"mistake_id": mid, "error": resp.text})
                print(f"m={mid} 触发失败 {resp.status_code} {resp.text[:120]}")
                continue
            task = wait_task(c, h, resp.json()["data"]["id"])
            detail = c.get(f"{BASE}/mistakes/{mid}", headers=h).json()["data"]
            analysis = detail.get("analysis") or {}
            items = analysis.get("similar_questions") or []
            stats = analysis.get("variants_stats") or {}
            elapsed = round(time.monotonic() - started, 1)
            rows.append(
                {
                    "mistake_id": mid,
                    "question_id": detail.get("question_id"),
                    "my_answer": detail.get("my_answer_md"),
                    "correct_answer": detail.get("correct_answer_md"),
                    "cause_type": analysis.get("cause_type"),
                    "status": task["status"],
                    "task_result": task.get("result"),
                    "stats": stats,
                    "items": items,
                    "elapsed_s": elapsed,
                }
            )
            print(f"m={mid} {task['status']} passed={len(items)} stats={stats} {elapsed}s")

        # 入库幂等：取第一条有变式题的用例
        accept_check = {}
        for row in rows:
            if row.get("items"):
                mid = row["mistake_id"]
                vid = row["items"][0]["variant_id"]
                first = c.post(f"{BASE}/mistakes/{mid}/variants/{vid}/accept", headers=h)
                second = c.post(f"{BASE}/mistakes/{mid}/variants/{vid}/accept", headers=h)
                accept_check = {
                    "mistake_id": mid,
                    "variant_id": vid,
                    "first": first.json()["data"],
                    "second": second.json()["data"],
                }
                qid = accept_check["first"]["question_id"]
                accept_check["question"] = c.get(f"{BASE}/questions/{qid}", headers=h).json()["data"]
                break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"rows": rows, "accept_check": accept_check}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    total = sum(len(row.get("items") or []) for row in rows)
    print(f"生成 {len(rows)} 题次，通过自检共 {total} 道；结果写入 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 跑验收脚本并留存输出**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python.exe E:\BiShe-AIStudy\.sdd\s4-4\accept_s4_4.py 2>&1 | Tee-Object -FilePath E:\BiShe-AIStudy\.sdd\s4-4\accept.out.txt
```

若 `variant_generate_retry` 日志占比超过 30%（说明 `temperature=0.7` 下严格 JSON 不稳），把 `variant_generator.py` 的 `TEMPERATURE` 降到 `0.5` 重跑整轮验收，并在 `.sdd/s4-4/progress.md` 记下改值与原因（spec §14 第 5 条的技术假设要用实测结清）。

- [ ] **Step 4: 逐题手算核对答案（本任务的核心，不能跳）**

对 `.sdd/s4-4/variants.json` 里每道 `items[*]`：自己算一遍，与 `answer_md` 比对，判 `正确 / 错误 / 无法判定（题目本身有误）`。把结论写进 `.sdd/s4-4/acceptance-evidence.md` 的表格（每行：用例号、variant_id、题干摘要、模型答案、我的答案、判定）。

准确率 = 正确 / 总数；目标 ≥90%。**若不到 90%，先别改代码**：把错误案例归类（生成错 / 复算也错 / 题目歧义），再决定是补 Prompt 还是如实报告。

- [ ] **Step 5: 收集被自检拦下的案例**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python.exe -c @"
from sqlalchemy import text
from app.core.db import new_session
s = new_session()
rows = s.execute(text('''
  select id, task_id, error, result
  from async_tasks
  where name = 'mistake.variants'
  order by id desc
  limit 8
''')).all()
for r in rows:
    print(r)
s.close()
"@
```

再从 `.sdd/s4-4/logs/worker.err.log`（若已重定向）或控制台输出里 `Select-String variant_self_check_rejected` 抓至少 1 条真实拦截记录，贴进证据文档。

- [ ] **Step 6: 成本与耗时统计**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python.exe -c @"
from sqlalchemy import text
from app.core.db import new_session
s = new_session()
row = s.execute(text('''
  select count(*) as calls,
         sum(prompt_tokens) as pt, sum(completion_tokens) as ct,
         round(avg(latency_ms)) as avg_ms,
         round(sum(cost), 6) as cost
  from llm_call_logs
  where scene = 'gen' and created_at > now() - interval '2 hours'
''')).first()
print('calls=%s prompt=%s completion=%s avg_ms=%s cost=%s' % tuple(row))
s.close()
"@
```

（列名以 `models/llm_call_log.py` 为准；若列名不同，按实际改 SQL。）

- [ ] **Step 7: 写证据文档**

`.sdd/s4-4/acceptance-evidence.md` 必须包含：

1. 环境（模型、时间、uvicorn/worker）；
2. 生成汇总表（7 个题次：passed/rejected/rounds/elapsed）；
3. **21 道逐题核对表**（模型答案 vs 我的答案 vs 判定）+ 准确率；
4. 至少 1 条被自检拦下的真实日志（原文）；
5. 入库检查：`created=true` → 重复 accept `created=false` 同 id → `GET /questions/{id}` 的 `origin=ai`/`verified=false`/KP 继承；
6. `scene='gen'` 的调用数/tokens/耗时/费用；
7. 如实标注：**自测集（题目来自 S4-1 题库），人工核对，不是真实学生使用数据**；
8. 预判限制的实测结果（复算通过≠答案正确：本轮是否出现"两边同错"）。

- [ ] **Step 8: 提交（只提交代码与文档，不提交 .sdd / variants.json）**

```powershell
cd E:\BiShe-AIStudy\study-agent
git status --short
```

确认没有把 `.sdd/`、`测试数据/s4_3_cases.json` 加进来后再继续（本任务通常无需提交）。

---

### Task 10: 文档同步 + 全量回归

**Files:**
- Modify: `docs/API.md`（§6 两个接口 + `analysis` 两字段；§3.5 任务类型清单）
- Modify: `docs/SCHEMA.md`（§5.4 `similar_questions_json` 备注）
- Modify: `docs/PROGRESS.md`（当前状态、任务清单、变更日志、遗留）
- Modify: `docs/DECISIONS.md`（追加 D-047）
- Modify: `AGENTS.md`（§9.2 补 S4-4 细则；§9.6 补锚点）
- Modify: `docs/AI协作开发实施计划.md`（S4-4 勾选 + 实施记录）
- Create: `.sdd/s4-4/progress.md`（偏离与裁决，不入 git）

- [ ] **Step 1: API.md**

在 §6「错题本」里，紧跟 `POST /mistakes/{id}/analyze` 之后加两节：

- `POST /api/v1/mistakes/{mistake_id}/variants`：202/`Envelope[TaskOut]`；无诊断或题干 <10 字 → 409/40900；任务结果示例 `{"mistake_id":43,"requested":3,"passed":2,"rejected":1,"rounds":2,"elapsed_ms":21400}`。
- `POST /api/v1/mistakes/{mistake_id}/variants/{variant_id}/accept`：200/`Envelope[{question_id, created}]`；`created=false` 表示已入库或题库已有同题；404 表示「变式题不存在或已被重新生成」。
- `GET /mistakes/{id}` 的 `analysis` 行改成包含 `similar_questions`（数组，元素字段逐个列出）与 `variants_stats`（requested/passed/rejected/rounds/generated_at）。

§3.5 任务类型表补一行 `mistake.variants`（202、结果字段见上）。

- [ ] **Step 2: SCHEMA.md**

§5.4 的 `similar_questions_json` 行备注改成：

> 变式题（S4-4 写入）：`{"version":1,"generated_at","model","prompt_version","stats":{...},"items":[...],"rejected":[...]}`，结构见 `docs/spec/s4-4-variant-generation.md` §4.1；未生成时 NULL

- [ ] **Step 3: PROGRESS.md**

- 当前状态第 8/9/10/11 行改成本卡事实（阶段 4 完成 S4-1~S4-4；后端/前端实测数字；S4-4 关键口径；下一步 S4-5）；
- 任务清单 `- [ ] S4-4` → `- [x]`；
- 变更日志新增 `### 2026-11-03（S4-4）`：交付物、拍板（纯手动/先 JSON 后入库/确定性比对）、测试数字（实测后再写）、真机验收摘要（21 道、准确率、入库幂等、拦截日志）、已知不足（自动生成未做、复算通过≠正确、无 LaTeX 校验、accepted_question_id 悬空）；
- 遗留表加：AI 变式题的审核/淘汰流、变式题相似度度量、"自动随诊断生成"未做。

- [ ] **Step 4: DECISIONS.md**

追加 `## D-047 变式题生成与复算自检（S4-4）`，条目覆盖：纯手动（D-1）、先 JSON 后确认入库（D-2）、JSONB 不建表（D-3）、两段式独立复算（D-4）、确定性比对（D-5）、重试与丢弃（D-6）、难度/题数（D-7）、题干过短拒绝（D-8）、需先诊断（D-9）、accept 幂等（D-10）、入库标记与 KP 继承（D-11）、非原子两步收敛（§6.4）、无迁移与测试数字。

- [ ] **Step 5: AGENTS.md**

- §9.2 在「错因诊断（S4-3）」之后加「变式题生成（S4-4）」一条（手动触发、护栏、比对口径、幂等、`scene=gen`、不自动生成的原因）。
- §9.6 加锚点行：`backend/app/ai/gen/{compare,variant_generator,variant_verifier}.py + backend/app/services/question_gen_service.py + backend/app/tasks/generate_variants.py + backend/app/api/v1/mistakes.py`。

- [ ] **Step 6: 实施计划**

`- [ ] S4-4 变式题生成 + 复算自检` → `- [x]`；在该卡下补「实施记录（2026-11-03）」一行（交付 + 真机结论 + 测试数字）。

- [ ] **Step 7: 全量回归**

```powershell
cd backend
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m alembic heads
..\.venv\Scripts\python.exe -m alembic check
```

```powershell
cd web
$env:NODE_OPTIONS="--require E:\BiShe-AIStudy\.sdd\tools\dsh-exec-patch.cjs"
npm run test:run -- --pool=threads
npm run build
```

预期：后端全绿（基线 999 + 本卡新增）、`alembic heads` 仍为 `0011_s4_3`、`check` 无漂移；前端全绿（基线 187 + 本卡新增）、build exit 0。把实际数字写进 PROGRESS。

- [ ] **Step 8: 写 `.sdd/s4-4/progress.md`**

记录：偏离 plan 的地方（如有）、Task 8 前端交互的取舍、验收数字、环境事故、遗留。

- [ ] **Step 9: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add docs/API.md docs/SCHEMA.md docs/PROGRESS.md docs/DECISIONS.md AGENTS.md docs/AI协作开发实施计划.md
git commit -m "docs(s4-4): 接口/数据/进度/决策/细则同步与实施记录"
```

---

### Task 11: 终审与收尾（ff-merge，不 push）

- [ ] **Step 1: 自查清单**

逐条确认（有任一条不过就先修）：

1. `git status` 干净，没有把 `.sdd/`、`测试数据/*.json` 加进来；
2. `grep -rn "similar_questions_json" backend/app` 只有模型、服务、DTO 三处读写，没有别的模块私自写；并且 `services/mistake_analysis_service.py` 里**没有**对它的写操作（spec D-12：重新诊断不清空变式题）；
3. `grep -rn "scene=" backend/app/ai/gen` 只有 `gen`；
4. 没有新增依赖：`git diff main --stat -- requirements.txt web/package.json` 为空；
5. 没有硬编码 Prompt：`question_gen_v1.md` / `question_verify_v1.md` 都在 `ai/prompts/` 下；
6. 任务 handler 无 `session.commit()`（`tasks/generate_variants.py` 里搜索确认）；
7. 前端详情页没有残留 S4-3 的占位字段：`grep -n "similar_questions_json\|similarQuestions" web/src` 应为空。

- [ ] **Step 2: 全量回归再跑一次（合并前）**

按 Task 10 Step 7 的两组命令重跑，贴输出。

- [ ] **Step 3: ff-merge**

```powershell
cd E:\BiShe-AIStudy\study-agent
git checkout main
git merge --ff-only feature/s4-4-variant-generation
git log --oneline -5
git branch -d feature/s4-4-variant-generation
```

- [ ] **Step 4: 合并后复跑关键测试**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

```powershell
cd web
$env:NODE_OPTIONS="--require E:\BiShe-AIStudy\.sdd\tools\dsh-exec-patch.cjs"
npm run test:run -- --pool=threads
```

- [ ] **Step 5: 停掉验收用的服务**

把 Task 9 Step 1 起的 uvicorn / worker 后台任务都停掉，并复查 Redis 没有残留消费者。**不要 push**（用户自己推）。

## 附：确定性质量护栏（真机验收后补，spec §5.2.1）

新增 `backend/app/ai/gen/quality.py`：

```python
SELF_TALK_MARKERS = ("？错", "?错", "错！", "重算", "重新计算", "再核", "改为", "换一道", "换一题",
                     "修正题目", "但题目", "等等，", "让我重新", "重新写")


def stem_fingerprint(stem_md: str) -> str:
    return _SPACE.sub("", unicodedata.normalize("NFKC", stem_md or ""))


def find_self_talk(analysis_md: str) -> str | None:
    for marker in SELF_TALK_MARKERS:
        if marker in (analysis_md or ""):
            return marker
    return None
```

`run_generation` 的循环在调用 `verify_answer` **之前**插入两道检查（`rejected` 记因、`failed` 占重生成名额）：

```python
    seen_stems: set[str] = set()
    ...
            fingerprint = stem_fingerprint(variant.stem_md)
            if fingerprint in seen_stems:
                rejected.append({"reason": "同批题干重复", "stem_excerpt": variant.stem_md[:EXCERPT_LIMIT]})
                failed.append(variant)
                continue
            marker = find_self_talk(variant.analysis_md)
            if marker is not None:
                rejected.append({"reason": f"解析自问自答（命中「{marker}」）", ...})
                failed.append(variant)
                continue
            seen_stems.add(fingerprint)
```

验证命令：`cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_variant_quality.py tests/test_question_gen_service.py -q`
