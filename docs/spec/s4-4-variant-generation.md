# S4-4 变式题生成 + 复算自检 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S4-4（`docs/AI协作开发实施计划.md:677`）
- 方案依据：`docs/个性化学习智能体-毕业设计完整方案.md` §6.5「试题生成与自适应组卷」的生成可靠性设计、附录 C2「变式题生成」Prompt 骨架
- 日期：2026-11-03
- 状态：设计与用户逐条确认（4 个决策点），待用户评审本文
- 上游：S4-3（`mistake_analyses` 与 `kp_ids`、错因、`similar_questions_json` 列保持 NULL）、S4-2（`mistakes` 归属与复用口径）、S4-1（`questions` / `question_kps`、两道闸判重、`validate_question_shape`）、S0-5（`AppError` 体系）、S2-7（异步任务 + runner）、S3-4（文件型 Prompt 约定）
- 下游：S5-4 在线作答（消费入库后的 `origin=ai` 题目）、S5-1 组卷（AI 题在题库内可直接被选）、S4-8 统计（可选：变式题自检通过率）
- 产物：`ai/gen/{__init__,variant_generator,variant_verifier,compare}.py`、`ai/prompts/{question_gen_v1,question_verify_v1}.md`、`services/question_gen_service.py`、`tasks/generate_variants.py`、`services/question_service.py`（+1 公共函数）、`schemas/mistake.py`（DTO 扩展）、`api/v1/mistakes.py`（+2 路由）、前端 `types/mistakes.ts` / `api/mistakes.ts` / `views/mistakes/MistakeDetailView.vue`（变式训练区）、`.sdd/s4-4/accept_s4_4.py`（验收脚本）
- **无迁移**：`similar_questions_json` 列 S4-2 已建（`JSONB NULL`），`alembic head` 保持 `0011_s4_3`

## 1. 目标

1. 针对一道**已诊断**的错题，按需生成 3 道同知识点变式题（题型同原题、难度 ±1），每题带答案与分步解析，写进 `mistake_analyses.similar_questions_json`。
2. **独立复算自检**：另起一次 LLM 调用，只给题干（+选项）、不给答案，让模型解题；把复算答案与生成答案做**确定性比对**（数值容差 / 选择题 key 集合 / 规范化字符串）。不一致的题重生成，最多 2 轮；仍不过则丢弃并留痕。
3. 自检通过的题在详情页可视化，并支持**人工确认**后存入题库（`origin=ai`、`verified=false`），继承原题知识点；已入库的题可被 S5 组卷/作答直接复用。
4. 复用既有能力，不另造轮子：判重走 `question_service.check_duplicate` 两道闸、选项规则走 `schemas/question.py::validate_question_shape`、任务走 `task_service.create_task` + runner、LLM 走 `ai/llm` 适配器（`scene="gen"`）。
5. 失败可见：被自检拦下的案例必须能查到（JSON `stats`/`rejected` + WARNING 日志 + `llm_call_logs`），作为验收材料与论文素材。

非目标：自动随诊断生成（本卡改为纯手动，见 D-1）、变式题的难度自适应/个性化推荐（S5-1）、变式题入库后的审核流、题目 LaTeX 编译校验（S4-1 未引入 LaTeX 编译器，本卡只做结构化校验）、AI 题的质量回写与淘汰（S4-8 之后再说）。

## 2. 范围

### 2.1 做

- `ai/gen/variant_generator.py`：生成适配器（1 次调用出 3 道，严格 JSON + Pydantic 校验 + 2 次重试）
- `ai/gen/variant_verifier.py`：复算适配器（只喂题干/选项，输出最终答案 + 简要步骤）
- `ai/gen/compare.py`：纯函数答案比对（规范化、数值/根式/分数/百分号、选项 key 集合、无解同义词），零依赖、可单测
- `ai/prompts/question_gen_v1.md`、`ai/prompts/question_verify_v1.md`
- `services/question_gen_service.py`：`enqueue_variants`、`run_generation`（任务内用例，写 JSON）、`accept_variant`（建题 + 回写 JSON）
- `services/question_service.py`：新增公共函数 `create_generated_question`（AI 题入库的唯一入口，含判重与 KP 继承）
- `tasks/generate_variants.py`：注册 `mistake.variants`
- `api/v1/mistakes.py`：`POST /{id}/variants`（202）、`POST /{id}/variants/{variant_id}/accept`（200）
- `schemas/mistake.py`：`MistakeAnalysisOut` 增 `similar_questions` / `variants_stats`
- 前端：详情页「变式训练」区（生成、重新生成、逐题确认入库、自检徽标、被丢弃提示）
- 测试：AI 层（比对纯函数 + 生成 + 复算）、服务层、任务层、接口层、前端组件
- 验收：7 道错题 × 3 道 = 21 道真机生成 + 我逐题手算核对 + 入库幂等 + 拦截日志

### 2.2 不做

- 自动触发（用户明确选择纯手动，与任务卡不同，见 D-1）
- 生成即入库（用户明确选择先 JSON + 人工确认，与任务卡不同，见 D-2）
- 变式题表格化（不新建 `mistake_variants` 表；JSONB 已够用，见 D-3）
- 题型转换（原题是选择就生成选择，不生成"把选择题改成解答题"）
- 图片题/几何作图题的变式（原题带图时不生成，见 D-8）
- 对已入库 AI 题的二次编辑与删除治理（走既有题库接口，本卡不改）

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| D-1 | **纯手动触发**：`POST /mistakes/{id}/variants` 才生成，录入/诊断成功后**不自动**入队 | 用户拍板。理由：变式题一次要 4–12 次 LLM 调用（生成 3 道 + 逐题复算 + 重试），自动生成会让"录入一道错题"的成本翻几倍，而学生未必每次都练；手动按钮把成本交给真实需求。**与任务卡「集成进错题分析」不一致，已在 spec 与本行记录** |
| D-2 | **先生成到 JSON，人工确认后才入库**：`accept` 才建 `questions` 行 | 用户拍板。`questions` 是公共语料（所有用户可见、组卷/练习都从它取），把每个学生的 AI 变式题直接灌进去会污染题库，也没法回溯"哪道题是谁的变式"。JSON 先行 + 单题确认 = 任务卡要求的"人工确认"第二道防线；入库后仍可被 S5 正常使用 |
| D-3 | 存储用既有 `mistake_analyses.similar_questions_json`（JSONB），**不建新表、不加迁移** | 该列 S4-2 就是为此建的（`SCHEMA §5.4`，S4-3 保持 NULL）。变式题与诊断 1:1、无跨题查询需求（筛选/统计都不按变式题查），JSONB 足够；建表要多一张表、一次迁移和一套 CRUD，收益为零 |
| D-4 | 生成与复算**分成两个 Prompt、两次独立调用**，复算只给题干（+选项） | 方案 §6.5 的核心要求"独立复算"。同一次调用里自问自答不算独立；把答案再喂回去等于让模型给自己打分 |
| D-5 | 比对在**代码层**做确定性判定：规范化字符串 + 数值相对误差 1e-6 + 选择题 key 集合 + 无解/全体实数同义词组 | 用户拍板。可解释、可复现、可在论文里写成公式；不引入第三次 LLM"裁判"（贵且裁判也会错）。等价写法差异靠重生成与规范化规则消化，误杀代价只是少一道题 |
| D-6 | 失败策略：该题重生成，最多 2 轮（生成调用总数 ≤3）；仍不过 → 丢弃并记 `rejected` + WARNING `variant_self_check_rejected` | 方案"不一致 → 丢弃或重生成（最多 2 次）"。丢弃的题绝不进 `items`，前端只提示"本次有 N 道未通过自检"，不展示错答案 |
| D-7 | 难度 = 原题 `difficulty` ±1（裁剪到 1–5）；一次请求固定 **3 道**（`MAX_VARIANTS=3`），**对外不开放 `count` 参数**（内部重生成时按剩余条数传） | 用户选择"每题 3 道"。固定数量让 Prompt 与 JSON 校验简单（少于 3 道按失败重试），也避免前端为"要几道"多一层交互 |
| D-8 | 只有**题干文本足够**（`len(stem_md.strip()) ≥ 10`）才生成；不足则 `409/40900`「这道题题干太短，暂不支持生成变式」 | 生成器只吃题干文本 + 选项。拍照错题的题干是视觉识别出来的，**仍然有文本**，所以不能按 `image_file_id` 是否为空来判断（那样会误伤所有拍照题）。真正没法生成的是识别失败/题干过短的情况 |
| D-9 | 变式题必须**已有诊断**才能生成（无诊断 → `409/40900`「请先完成错因诊断」） | 变式题挂在 `mistake_analyses` 行上（D-3），且 Prompt 要用错因与 `kp_ids` 做条件；没有诊断既无处存也无依据。前端按此置灰按钮 |
| D-10 | `accept` 幂等：同 `variant_id` 再点 → 返回同一 `question_id` + `created=false`；若题库里已有同题（两道闸命中）也返回既有题 `created=false` | 与 S4-2"重复录入复用赢家"同口径，避免前端重试/双击造重复题 |
| D-11 | 入库题目：`origin=ai`、`verified=false`、`tags=["AI变式"]`、知识点**继承原题** `question_kps` 的 `kp_id + weight` | 任务卡明确要求 `origin=ai + verified=false`；变式题与例题同知识点是最合理默认，重新对齐既慢又可能与例题不一致（同 S4-3 D-8 的理由） |
| D-12 | 重新诊断**不清空**已生成的变式题；重新生成**整体覆盖** JSON（旧 `variant_id` 全部失效） | 诊断重跑只换错因/讲解，题面没变，变式题仍然成立；重新生成是一次新请求，覆盖比"合并去重"更好解释，前端按当前 JSON 渲染即可 |
| D-13 | 两个接口都要求错题归属；他人/不存在统一 `404/40400` | 同 S4-2/S4-3 的私有数据口径 |
| D-14 | 任务 payload 只带 `mistake_id` / `user_id`；结果返回计数摘要（requested/passed/rejected/rounds/elapsed_ms） | payload 落 `async_tasks` 表，不能塞题面正文；摘要便于验收脚本与前端提示 |

## 4. 数据模型（无迁移）

### 4.1 `similar_questions_json` 结构（v1）

```json
{
  "version": 1,
  "generated_at": "2026-11-03T14:02:11+00:00",
  "model": "qwen-plus",
  "prompt_version": "question_gen_v1",
  "stats": {"requested": 3, "passed": 2, "rejected": 1, "rounds": 2},
  "items": [
    {
      "variant_id": "3f2a1b9c",
      "stem_md": "已知等差数列 $a_1=3$，公差 $d=4$，求 $a_8$。",
      "options": null,
      "answer_md": "$31$",
      "analysis_md": "由通项公式 $a_n=a_1+(n-1)d$ 得 $a_8=3+7\\times 4=31$。",
      "qtype": "解答",
      "difficulty": 2,
      "kp_ids": [12],
      "self_check": {"status": "passed", "attempts": 1, "verified_answer_md": "$31$"},
      "accepted_question_id": null,
      "accepted_at": null
    }
  ],
  "rejected": [
    {"reason": "复算答案不一致：$31$ ≠ $30$", "stem_excerpt": "已知等差数列 $a_1=3$，公差 $d=4$，求 $a_9$…"}
  ]
}
```

约束：

- `items` 长度 0–3；`rejected` 长度 0–9（3 道 × 最多 3 轮），每条 `reason` ≤200 字、`stem_excerpt` ≤80 字。
- `variant_id`：`secrets.token_hex(4)`，同一 JSON 内唯一。
- `accepted_question_id` 指向 `questions.id`；题被删后该值可能悬空（D-11 的实现限制，见 §13）。
- `kp_ids` 为入库时继承的原题 KP，仅作展示与追溯。

### 4.2 `SCHEMA.md` §5.4 备注

列定义不变，只把备注从「S4-4 写入；S4-3 保持 NULL」更新为指向本节结构（v1）。

## 5. AI 层（`ai/gen/`）

### 5.1 生成（`variant_generator.py`）

```python
SCENE = "gen"
PROMPT_VERSION = "question_gen_v1"
PROMPT_FILE = "question_gen_v1.md"
MAX_VARIANTS = 3
MAX_RETRIES = 2

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

def generate_variants(context, *, llm_client=None, max_retries=MAX_RETRIES) -> list[GeneratedVariant]
```

- 调用：`client.chat(messages, temperature=0.7, max_tokens=2000, scene="gen")`（方案 §6.5 表格：生成 0.7）。
- 输出 schema（严格 JSON）：

```json
{"items": [{"stem_md": "...", "options": [{"key": "A", "text": "..."}] | null,
            "answer_md": "...", "analysis_md": "...", "qtype": "解答", "difficulty": 3}]}
```

- Pydantic 校验：`stem_md` ≥5 且 ≤2000；`answer_md` 非空 ≤500；`analysis_md` ≥10 ≤1500；`qtype ∈ {单选,多选,填空,解答}`；`difficulty ∈ 1..5`；`options` 规则直接复用 `schemas/question.py::validate_question_shape`（该模块只依赖 pydantic，ai 层引用它不会把 fastapi 拖进来）。
- 条数不足 `count` → 视为本次失败（记 `variant_generate_count_short`），按重试处理，不"有多少算多少"（否则验收的 3 道/题会漂移）。重生成时 `count = len(pending)`。

### 5.2 复算（`variant_verifier.py`）

```python
PROMPT_VERSION = "question_verify_v1"
PROMPT_FILE = "question_verify_v1.md"

@dataclass(frozen=True)
class VerifyContext:
    stem_md: str
    options: list[tuple[str, str]] = field(default_factory=list)

def verify_answer(context, *, llm_client=None, max_retries=MAX_RETRIES) -> str
```

- 只喂题干与选项，**不喂答案、不喂解析**；Prompt 要求"独立解题，输出最终答案与不超过 3 步的关键过程"。
- 输出 schema：`{"answer_md": "...", "reasoning_md": "..."}`，`answer_md` 非空。
- 复算自身的失败（JSON 非法/重试耗尽）→ `VariantVerificationError`；该题记为"复算失败"并进入重生成（视同未通过）。

### 5.3 比对（`compare.py`，纯函数）

```python
def normalize_answer(text: str) -> str
def parse_number(text: str) -> Decimal | None
def match_answers(expected: str, actual: str) -> tuple[bool, str]  # (是否一致, 原因说明)
```

规范化顺序（只做"确定等价"的替换，不做数学变形）：

1. 去代码围栏与 `$`/`$$`；`\left`/`\right`/`\dfrac`/`\tfrac` 归一；`\cdot`→`*`；`×`→`*`；`÷`→`/`；
2. 全角括号/逗号/分号/冒号 → 半角；去空白；去前缀「答案：/答：/所以/因此/故」；去末尾「。/.」；
3. 去 `\text{}`、`\mathrm{}` 外壳。

数值解析（`parse_number`）覆盖：

- 整数/小数/负数、`-4/5`、`\frac{3}{5}`、`80\%`、`0.8`、`\sqrt{25}`（完全平方才求值）、`3\sqrt{3}`（保留为 `3√3` 字符串，不与数值混比）。

比对优先级：

1. **选择题**：两边都能解析成选项 key 集合（`A` / `AC` / `A,C` / `A、C`）→ 集合相等；
2. **数值**：两边都能解析成 Decimal → 相对误差 ≤`1e-6`（0 时用绝对误差）；
3. **同义词组**：`{无解, 没有解, 不存在}` / `{任意实数, 全体实数, R, \mathbb{R}}` / `{无穷多解}` 各自成组，同组即一致；
4. **多解**：按 `或` / `,` / `、` / `;` 切分后逐项规范化，**集合相等**即一致（`x=2 或 x=3` 与 `x=3, x=2` 视为同一答案）；
5. **字符串**：`normalize_answer` 后相等；
6. 其余 → 不一致，返回原因字符串（供 `rejected.reason`，例如「复算答案不一致：$31$ ≠ $30$」）。

### 5.4 Prompt 要点

`question_gen_v1.md`：

1. 角色：资深高中数学命题老师，为一名学生出**同知识点**变式题。
2. 输入：原题题干、选项（可能为空）、标答、知识点名称、错因、原题题型与难度、要出的数量。
3. 硬约束：同知识点；难度 = 原题 ±1；**不得与原题数字/情境雷同**（换数字、换问法、换情境）；题型必须与原题相同；每题必须给答案与 3 步以内的分步解析；公式用 LaTeX。
4. 输出严格 JSON（见 5.1 schema），不要 Markdown 围栏以外的解释，不要多也不要少。
5. 不确定的题宁可不写（但条数不足会整体重试）。

`question_verify_v1.md`：

1. 角色：独立解题者，**只根据题干作答**。
2. 输出：最终答案（`answer_md`）+ 不超过 3 步的关键过程（`reasoning_md`）。
3. 选择题只答选项 key；多解用集合写法；无解写"无解"。

### 5.5 错误

| 异常 | 触发 | 处理 |
|---|---|---|
| `VariantGenerationError` | 生成 JSON 非法/条数不足/字段非法/重试耗尽 | 任务 `failed`，旧 JSON 保持不变 |
| `VariantVerificationError` | 复算 JSON 非法/重试耗尽 | 该题视为未通过，进入重生成；重生成后仍失败则弃 |

## 6. 服务层（`services/question_gen_service.py`）

```python
TASK_GENERATE_VARIANTS = "mistake.variants"
MAX_VARIANTS = 3
MAX_ROUNDS = 2              # 重生成轮数上限
MAX_TOTAL_CALLS = 12        # 兜底：生成 3 次 + 复算 9 次

def enqueue_variants(session, *, owner, mistake_id, queue) -> AsyncTask
def run_generation(session, *, user_id, mistake_id) -> dict   # 任务内用例，不 commit
def accept_variant(session, *, owner, mistake_id, variant_id) -> tuple[Question, bool]  # 同步用例，commit
```

### 6.1 `enqueue_variants`

1. `_load_owned`：错题必须属于 `owner`，否则 `NotFoundError`（404）。
2. 已有诊断？没有 → `ConflictError("请先完成错因诊断")`（409/40900）。
3. 原题带图且无题面文字依据（D-8）→ `ConflictError("这道题暂不支持生成变式")`。
4. `task_service.create_task(name=TASK_GENERATE_VARIANTS, payload={"user_id","mistake_id","count":3})`。
5. 不做"已有变式题则跳过"——重新生成是用户的显式意图，天然覆盖。

### 6.2 `run_generation`（任务内、不 commit）

1. 载入 `Mistake` + `Question` + `MistakeAnalysis`；缺失/越权抛 `NotFoundError`（runner 会置 failed）。
2. `build_generation_context`：题干（截断 2000）、选项、标答、`kp_names`（复用 S4-3 的 `_kp_rows`，≤3）、`cause_type`、`qtype`、`difficulty`。
3. 生成 → 逐题复算 → 比对：通过的进 `passed`，未通过的进 `pending`。
4. `pending` 非空且轮数 <2 → 只对 `pending` 重生成（`count=len(pending)`），再复算；调用总数受 `MAX_TOTAL_CALLS` 约束。
5. 组装 JSON（§4.1），写 `analysis.similar_questions_json`，`session.flush()`。
6. 返回摘要：`{"mistake_id", "requested", "passed", "rejected", "rounds", "elapsed_ms"}`。
7. 全部被拦（`passed=0`）也算任务 `succeeded`（业务完成，只是没有可展示的题）——前端据 `passed=0` 提示"本次没有生成出通过自检的题，可重试"。

### 6.3 `accept_variant`（同步、commit）

1. 载入归属 + 诊断 JSON；`variant_id` 不在 `items` 里 → `NotFoundError("变式题不存在或已被重新生成")`。
2. 已有 `accepted_question_id` 且题目仍存在 → 直接返回该题 + `created=false`。
3. 否则调 `question_service.create_generated_question(...)`：
   - 题干规范化 + embedding + `check_duplicate`（两道闸）；命中 → 返回既有题 `created=false`；
   - 未命中 → `_persist_question(origin="ai", verified=False, tags=["AI变式"], links=原题 KP 链接)`，`created=true`。
4. 回写 JSON：`accepted_question_id`、`accepted_at`；`session.flush()` + `_commit`。
5. 返回 `(question, created)`。

### 6.4 `question_service.create_generated_question`

```python
def create_generated_question(
    session: Session, *, subject_id: int, stem_md: str, options_json: list[dict] | None,
    answer_md: str, analysis_md: str | None, qtype: str, difficulty: int,
    links: list[tuple[int, Decimal]], created_by: int | None, embedder: EmbeddingClient | None = None,
) -> tuple[Question, bool]
```

- 只给 AI 变式题用；`origin="ai"`、`verified=False`、`tags=["AI变式"]` 写死在这里，调用方不能改（防"顺手"把 AI 题标成 verified）。
- 判重与 `_persist_question` 复用既有实现；`links` 由调用方传入（继承原题），不走 LLM 对齐。
- **事务边界**：该函数自行 `commit`（与 `create_question` 同款，调用方拿到的是已落库的题），`accept_variant` 随后再回写 JSON 并 commit。两步非原子，但**重试收敛**：若建题成功、回写 JSON 失败，用户再点一次会命中 `check_duplicate`（同题）→ 返回同一 `question_id` + `created=false` 并补写 JSON，不会产生重复题。这样比把"建题 + 改 JSONB"塞进一个跨模块事务更简单，也不会让 `accept` 因为 JSONB 写失败而整体回滚掉一道已建好的题。

## 7. 异步任务（`tasks/generate_variants.py`）

```python
@register(TASK_GENERATE_VARIANTS)
def handle(session: Session, payload: dict) -> dict:
    return question_gen_service.run_generation(
        session, user_id=payload["user_id"], mistake_id=payload["mistake_id"]
    )
```

- handler 不 commit（runner 统一提交/回滚），与 `mistake.analyze` 一致。
- 任务 `failed` 时旧 JSON 不变（`run_generation` 只在最后一步写）；runner 重试 3 次由既有策略决定，`job_timeout=300s` 足够（最坏 12 次调用 ≈60–90s）。
- 注册靠 `app/tasks/__init__.py` 的 import 副作用（与既有任务同款）：新增模块必须在包内 import，否则 worker 不认这个任务名。

## 8. 接口

### 8.1 `POST /api/v1/mistakes/{mistake_id}/variants`

- 权限：登录用户（仅本人；他人与不存在统一 404/40400）
- 类型：异步（**202**，用 `GET /api/v1/tasks/{task_id}` 轮询）
- 入参：无（数量固定 3）
- 出参：**202** `Envelope[TaskOut]`
- 错误：`404/40400`「错题不存在」；`409/40900`「请先完成错因诊断」/「这道题暂不支持生成变式」；`500/50000`「任务队列不可用」；`401/40100`
- 任务结果：

```json
{"mistake_id": 43, "requested": 3, "passed": 2, "rejected": 1, "rounds": 2, "elapsed_ms": 21400}
```

### 8.2 `POST /api/v1/mistakes/{mistake_id}/variants/{variant_id}/accept`

- 权限：登录用户（仅本人）
- 类型：同步
- 出参：**200** `Envelope[VariantAcceptOut]` = `{"question_id": 128, "created": true}`
- 行为：把该变式题存进题库（`origin=ai`、`verified=false`、继承原题 KP）；已入库/题库已有同题时 `created=false` 并返回既有题 id
- 错误：`404/40400`「错题不存在」/「变式题不存在或已被重新生成」；`401/40100`

### 8.3 `GET /api/v1/mistakes/{mistake_id}` 的 `analysis` 扩展

`analysis` 新增两个字段（其余不变）：

```
similar_questions: list[MistakeVariantOut] | null
variants_stats: {requested, passed, rejected, rounds, generated_at} | null
```

`MistakeVariantOut` = `{variant_id, stem_md, options, answer_md, analysis_md, qtype, difficulty, self_check: "passed", accepted_question_id}`。
未生成过 → 两个字段均为 `null`（与「已生成但 0 道通过」区分：后者是空数组 + stats）。

字段映射在 `services/mistake_service.py::_analysis_of` 里完成（该函数是 `analysis` 的唯一组装点）：从 `similar_questions_json` 读 `items`/`stats`，按 `version` 判断结构，未知版本按 `null` 处理（向前兼容，不抛错）。

## 9. 前端（`views/mistakes/MistakeDetailView.vue`）

### 9.1 变式训练区

诊断卡下方新增一张卡（`data-testid="variants"`），`el-card` 头部右侧按钮：

| 状态 | 展示 |
|---|---|
| 无诊断 | 按钮置灰 + 提示「先完成错因诊断」 |
| 有诊断、无变式题 | `el-empty` + `生成变式题`（`data-testid="generate-variants"`） |
| 生成中 | `.spinner` + 「生成并自检中…已等待 N 秒」+ 轮询 4s（与诊断同款，`data-testid="variants-loading"`） |
| 有变式题 | 区头 `重新生成`（`data-testid="regenerate-variants"`）；列表逐题渲染（见 9.2） |
| 本次被拦 | 列表上方一条 `el-text`：「本次有 N 道未通过自检，已丢弃」（`data-testid="variants-rejected"`） |

### 9.2 单题卡片

```
[难度 3] [解答] [已复算通过]                    [存入题库] / [已入库 #128]
题干（MdPreview）
答案（默认折叠，点击展开） / 解析（折叠）
```

- 存入题库：`data-testid="accept-variant-{variant_id}"`；成功后按钮变「已入库 #id」并禁用（可点击跳 `/questions?highlight=id`，本卡只做文本 + 跳题库列表）。
- 答案默认折叠（先让学生自己做），`el-collapse` 展开。

### 9.3 类型与 API 封装

- `types/mistakes.ts`：`MistakeVariant`、`VariantsStats`、`MistakeAnalysis` 增 `similar_questions` / `variants_stats`；`VariantAcceptResult = {question_id, created}`。
- `api/mistakes.ts`：`generateVariants(id): Promise<TaskOut>`、`acceptVariant(id, variantId): Promise<VariantAcceptResult>`。
- 移除 S4-3 的占位 `similar_questions_json?: unknown` 与 `similarQuestions` computed。
- 生成成功后重新拉详情（与诊断完成后同样的 refetch 路径），不本地拼装。

## 10. 测试计划

### 10.1 后端（约 40 条）

| 文件 | 覆盖 |
|---|---|
| `tests/test_variant_compare.py`（新） | 规范化（`$`、`\frac`、全角、去前缀、末尾标点）；数值（整数/小数/分数/百分号/负数/相对误差 1e-6/0 的绝对误差）；根式（完全平方求值、3√3 保留）；选择题（单/多选、逗号/顿号混写）；同义词组（无解/全体实数）；不一致时返回原因 |
| `tests/test_variant_generator.py`（新） | Prompt 渲染（StrictUndefined 缺变量炸）；正常 3 道；条数不足重试；非法 qtype/选项规则（选择 <2 项、解答带选项）；重试耗尽抛 `VariantGenerationError` |
| `tests/test_variant_verifier.py`（新） | 只喂题干（断言 Prompt 不含答案）；正常返回；非法 JSON 重试；耗尽抛 `VariantVerificationError` |
| `tests/test_question_gen_service.py`（新） | 无诊断 409；他人错题 404；原题带图 409；`run_generation` 写 JSON（通过/被拦/轮数/统计）；全被拦仍 succeeded；旧 JSON 在失败时不变；`accept_variant` 建题（origin/verified/tags/KP 继承）；重复 accept 返同一 id + `created=false`；题库已有同题 → `created=false`；`variant_id` 不存在 404 |
| `tests/test_question_gen_task.py`（新） | handler 注册名；调服务；不 commit（session.commit 未被调用） |
| `tests/test_mistakes_api.py`（扩） | `POST /variants` 202 + 409（无诊断/带图）+ 404；`accept` 200/404；`GET` 详情带 `similar_questions`/`variants_stats` |
| `tests/test_question_service.py`（扩） | `create_generated_question` 的 origin/verified/tags/links 与判重 |

### 10.2 前端（约 10 条）

`MistakeDetailView.spec.ts`：无诊断时按钮置灰；生成 3 道后渲染卡片与徽标；`accepted_question_id` 非空显示「已入库 #id」；`rejected>0` 显示提示；`passed=0` 显示"没有通过自检的题"；生成中轮询；入库按钮调 `acceptVariant` 后刷新；`similar_questions=null` 与 `[]` 两种空态区分。

## 11. 验收

### 11.1 自动

- 后端 `..\.venv\Scripts\python.exe -m pytest -q` 全绿（基线 999 → 预期 ~1040）
- 前端 `npm run test:run`（基线 187 → 预期 ~197）、`npm run build`
- `alembic check` 无漂移（本卡无迁移）

### 11.2 真机（必须贴实测输出）

1. 取 S4-3 的 7 道错题（覆盖不同知识点/题型），各生成 3 道 → 应得 21 道（允许被自检拦下后补生成，实际通过数如实记录）。
2. **我逐题手算核对答案**（≥90% 才达标），不一致的逐条记原因；结果表写进 `.sdd/s4-4/acceptance-evidence.md`。
3. 贴出被自检拦下的案例日志（`grep variant_self_check_rejected` 与 `llm_call_logs` 记录），至少 1 条真实案例。
4. 入库：accept 1 道 → `created=true`；重复 accept → `created=false` 同 id；题库 `GET /questions/{id}` 能查到 `origin=ai`、`verified=false`、KP 继承正确。
5. 成本/耗时：从 `llm_call_logs` 聚合 `scene='gen'` 的调用数、tokens、耗时，报告"每题变式一次的平均调用数/耗时"。
6. 前端路径：`/mistakes/{id}` 生成 → 卡片渲染 → 入库（浏览器手工点一遍，截图/文字记录；**无 Playwright，浏览器 E2E 仍不做**）。

### 11.3 如实记录的边界（预判）

- 复算通过 ≠ 答案正确（模型可能两次都错同一个答案），本卡只能降低风险，不能保证；论文/报告必须这么写。
- 规范化比对会对"数学等价但写法差异大"的答案误判（如 `2\sqrt{3}` vs `\sqrt{12}`），误判方向是**丢弃**（保守）。
- 生成的题可能"同知识点但过于简单/过于相似"，本卡不度量相似度，只靠 Prompt 约束"不得与原题数字情境雷同"。

## 12. 文档同步

- `docs/API.md` §6：新增两个接口 + `analysis` 两字段；§3.5 任务类型清单补 `mistake.variants`
- `docs/SCHEMA.md` §5.4：`similar_questions_json` 备注指向结构 v1
- `docs/PROGRESS.md`：任务清单、变更日志、遗留（自动生成未做、AI 题审核流未做）
- `docs/DECISIONS.md`：D-047（S4-4）
- `AGENTS.md` §9.2 补 S4-4 细则、§9.6 补锚点
- `docs/AI协作开发实施计划.md`：S4-4 勾选 + 实施记录
- `.sdd/s4-4/progress.md`（偏离与裁决）、`.sdd/s4-4/acceptance-evidence.md`

## 13. 已知限制（实现后按实回填）

- 自动生成不做（D-1）；变式题只在用户点按钮时出现。
- 已入库 AI 题被删除后，JSON 里的 `accepted_question_id` 悬空，前端仍显示「已入库 #id」；本卡不清洗（可留作 S5 的题目生命周期议题）。
- 无 LaTeX 编译校验（S4-1 起就没有编译器依赖），只保证结构合法。
- 并发两次生成同一错题，后写覆盖先写（无锁）；`variant_id` 失效时 accept 返回 404 已覆盖用户可见后果。
- 没有"变式题质量/相似度"指标，只有自检通过率。

## 14. 开工前必须先验证的技术假设

1. `WorkerSettings.job_timeout = 300s`（`core/config.py:58`）对最坏 12 次调用足够 —— 用一次真机生成计时确认（目标单次 ≤90s）。
2. `loads_json_object` 能容忍模型把 JSON 包在 ```json 里（S4-3 已验证，沿用）。
3. `questions` 表 `UNIQUE(subject_id, stem_hash)` 与 `check_duplicate` 的余弦闸对 AI 题同样生效（判重逻辑与来源无关，读代码确认）。
4. `mistake_analyses.similar_questions_json` 是 `JSONB` 且 SQLAlchemy 2.0 下直接赋 `dict` 即写（无需 `json.dumps`）—— S4-2 模型定义已声明 `Mapped[dict | None]`，跑一次真实写入确认。
5. `qwen-plus` 在 `temperature=0.7` 下仍能稳定输出严格 JSON（S4-3 用 0.2；本卡生成用 0.7，需实测；若失败率高则降 0.5 并记录）。