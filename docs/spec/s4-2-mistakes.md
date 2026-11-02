# S4-2 错题录入 + 状态机 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S4-2
- 日期：2026-11-03
- 状态：设计已逐节确认，待用户评审本文
- 上游：S2-6 文件上传（`files` 表 + 流式校验 + 对象存储）、S2-7 异步任务、S4-1 题库（`questions` / `question_kps`、`question_service.create_question` 含两道闸判重与知识点对齐）、S0-5 `AppError` 体系、S2-4 分页三件套
- 下游：S4-3 错因诊断（写 `mistake_analyses`）、S4-8 统计看板（复用本卡聚合口径）、S5-4 作答判分（回写 `correct_streak`）、S5-5 复习调度（按 `last_review_at` 排期）
- 产物：`models/mistake.py`、`models/mistake_analysis.py`、迁移 `0010_s4_2_mistakes.py`、`ai/vision/mistake_ocr.py`、`ai/prompts/mistake_ocr_v1.md`、`services/mistake_service.py`、`tasks/mistake_recognize.py`、`api/v1/mistakes.py`、`schemas/mistake.py`、前端 `views/mistakes/{MistakeListView,MistakeNewView,MistakeDetailView}.vue`、`测试数据/_make_s4_2_mistake_photos.py`（合成验收图）

## 1. 目标

1. 建 `mistakes` 表与 `mistake_analyses` 表，字段与 `SCHEMA.md` §5.3/§5.4 一一对应（`mistakes` 补唯一键与级联口径，见 D-1）。
2. 两种录入方式：
   - **从题库选**：给定 `question_id` 建错题，可附学生作答与正确答案；
   - **拍照录入**：上传题目照片 → 异步任务用多模态模型识别出题干/作答 → 建（或复用）题目 → 建错题，并保留原图。
3. 状态机：`待订正 → 已订正 → 已掌握`，由「复习记录」接口驱动；`correct_streak ≥ 2` 自动置 `已掌握`，答错清零并退回 `待订正`。
4. 列表支持按 **状态 / 错因 / 知识点 / 时间区间** 筛选，字段排序走白名单；统计接口给出状态分布、错因分布、知识点 TOP10。
5. 错题是**学生私有数据**：所有查询显式过滤 `user_id`，越权与不存在统一 404。
6. 拍照识别能力落在 `ai/vision/`，不引入本地模型；LLM 适配器扩展为可携带图片，纯文本调用路径零改动。
7. 前端三页：错题列表（筛选 + 统计卡）、拍照录入（上传 → 轮询 → 跳详情）、错题详情（题干/我的作答/状态操作/诊断占位）。

非目标：错因诊断本身（S4-3）、变式题生成（S4-4）、统计看板可视化页（S4-8）、作答判分（S5-4）、复习调度（S5-5）、教师/家长查看学生错题、错题导出打印。

## 2. 范围

### 2.1 做

- `app/models/mistake.py`、`app/models/mistake_analysis.py` + `alembic/versions/0010_s4_2_mistakes.py`（含 `mistake_analyses` 建表）。
- `app/models/enums.py`：新增 `MistakeStatus`（待订正/已订正/已掌握）、`CauseType`（六类 + `unknown`）。
- `app/ai/llm/base.py` + `app/ai/llm/openai_compat.py`：`LLMMessage` 增 `images`，视觉消息组装（见 D-4）。
- `app/ai/vision/{__init__,mistake_ocr}.py` + `app/ai/prompts/mistake_ocr_v1.md`：单图识别，严格 JSON + Pydantic + 2 次重试。
- `app/services/mistake_service.py`：录入（选题/拍照建任务）、列表、详情、状态更新、复习记录、统计、删除。
- `app/tasks/mistake_recognize.py` + 注册：`mistake.recognize` 任务（不在 handler 内 commit）。
- `app/api/v1/mistakes.py` + `app/schemas/mistake.py`：8 个接口 + 复用 `GET /tasks/{task_id}` 轮询。
- `backend/app/core/config.py` + `.env.example`：`VISION_MODEL`（默认 `qwen3-vl-plus`）。`qwen-vl-max-latest` 需在百炼控制台开通，本账号实测 403；需换模型时用 `VISION_MODEL` 覆盖。
- 前端 `views/mistakes/*.vue`、`api/mistakes.ts`、`types/mistakes.ts`、路由与侧栏「06 错题本」入口。
- `测试数据/_make_s4_2_mistake_photos.py`：Pillow 渲染合成题目图（含一张旋转+加噪，模拟手机拍摄），用于真机验收。
- 后端测试约 40 条 + 前端 6 条（见 §10）。
- 文档：`API.md` 新增 §6、`SCHEMA.md` §5.3/§5.4 补唯一键与索引口径、`AGENTS.md` §9.2/§9.6、`DECISIONS.md`、`PROGRESS.md`、实施计划勾选。

### 2.2 不做

- 不做错因诊断、变式题、掌握度回写：`mistake_analyses` 只建表，本卡不写入任何行（S4-3 负责填充）。
- 不做作答判分：`correct_streak` 只由人工「复习记录」驱动，S5-4 才接自动判分。
- 不做错题软删除、不做回收站、不做导入批次表。
- 不做教师/家长视角的 `/students/{id}/mistakes`；本卡所有路由作用于当前登录用户。
- 不做多图一次录入（一图一题）；不做手写体专项优化（识别不出作答时按 D-14 处理）。
- 不做图片预处理流水线（裁边/纠偏/去阴影），原图直接送模型。
- 不做错题去重（同一知识点多道相似错题并存）。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| D-1 | `mistakes` 增加 `UNIQUE(user_id, question_id)`；重复录入**不报 409**，而是复用既有行并重置（`status=待订正`、`correct_streak=0`；`last_review_at` **不动**——录入不是复习，deviation d-1） | 错题本语义是「一本」：同一道题再错一次，应当刷新为待订正而不是并存两条；沿用 S4-1 `mine` 式幂等口径，也让前端「再记一次」按钮可以无脑点 |
| D-2 | `question_id` 外键 `ON DELETE RESTRICT`；与 S4-1 已在 `delete_question` 里做的 `_ensure_not_referenced` 形成双保险 | 题目被硬删会让错题失去题干。S4-1 的守卫在 `mistakes` 表建好后才生效（`has_table` 守卫），本卡建表后这条保护自动上线，需要真机验证 |
| D-3 | 本卡建 `mistake_analyses`（只建表不写数据），列表的 `cause_type` 用 `EXISTS` 过滤（一题至多一条诊断，EXISTS 与 kp_id 同口径、不会放大行数） | 卡要求「按错因筛选与统计」，而错因存在 S4-3 才写入的表；提前建表让筛选 SQL 一次写对，S4-3 补数据后自然生效，避免回头改列表代码 |
| D-4 | 扩 `LLMMessage` 增 `images: list[str] \| None`（base64 data URL）；**有图时** `content` 组装成 `[{type:text},{type:image_url}]`，**无图时仍发字符串** | 现有所有 LLM 调用（QA/改写/对齐/切题）都发字符串 content，改动必须向后兼容；视觉能力单独成模块，不让业务层直接拼多模态结构 |
| D-5 | 拍照录入走**异步任务** `mistake.recognize`（202 + 轮询 `GET /tasks/{id}`），与 `question.extract` 同构 | 视觉调用 5–15s 且可能失败；runner 统一的重试与状态机比同步长请求可靠，前端也已具备轮询代码（S4-1 导入页） |
| D-6 | 识别出的题干走**既有** `question_service.create_question`（两道闸判重 + 知识点对齐）；命中判重则复用既有题，不新建 | 避免为拍照单独写一套建题逻辑；同一道题第二次被拍时应当挂到已有题目上，公共题库才不会被照片重复污染 |
| D-7 | `correct_streak` 只由 `POST /mistakes/{id}/review` 驱动；`PATCH status` 手改状态**不**加 streak | 卡的验收要求「能改状态」，但「连续答对」是行为事实，不能靠改标签伪造；两者分开才能保证 `streak` 在答辩时可解释 |
| D-8 | 权限：所有 `mistakes` 路由作用于当前登录用户，他人记录与不存在都返回 404/40400 | 错题是本卡第一份严格学生私有数据；沿用 S2-3「不泄露目标是否存在」的越权口径 |
| D-9 | `kp_id` 筛选用 `EXISTS`：命中题目挂的知识点（`question_kps`）**或** 诊断定位的知识点（`mistake_analyses.kp_ids`） | 学生视角「这个知识点的错题」两种来源都算；用 EXISTS 而非 JOIN，避免一题多知识点导致行重复、分页错乱（S4-1 已有同类口径） |
| D-10 | 统计一律 SQL 聚合（`GROUP BY` + `count`），Python 只做 DTO 拼装 | AGENTS §4「禁止在循环里查库」；S4-8 会复用同一套聚合口径 |
| D-11 | 列表排序走 `apply_sort` 白名单（`created_at`/`last_review_at`/`status`/`correct_streak`），并追加 `id DESC` 兜底 | 同一秒录入的多条错题翻页会重复/漏行，S4-1 已经踩过 |
| D-12 | 删除错题：同事务先删 `mistake_analyses` 再删 `mistakes`（FK 为 `ON DELETE CASCADE` 时的显式等价写法） | 硬删且不留孤儿；显式删除比依赖级联更容易在测试里断言 |
| D-13 | 拍照识别失败（模型超时/JSON 非法/置信度极低）→ 任务 `failed`，但**图片保留在 `files`**，前端提示可重试或改用「题库选」 | 原图是学生的唯一证据，失败也不能丢；重试由用户决定，不在 handler 里静默吞异常 |
| D-14 | 识别不出作答时 `my_answer_md = null`，而不是猜一段文本；识别置信度低于 `0.5` 时题目仍入库，但结果 payload 带 `low_confidence=true` 提示人工复核 | 与方案 6.3「作答缺失就不猜」一致；错题本的价值在本卡是「记录 + 状态」，题干错了可以改，编造的作答会污染 S4-3 的错因诊断 |
| D-15 | 视觉模型走配置 `VISION_MODEL`（默认 `qwen3-vl-plus`），与文本模型分开配置；`qwen-vl-max-latest` 需在百炼控制台开通，本账号实测 403，需换模型时用 `VISION_MODEL` 覆盖 | S4-1 的 `llm_model=qwen-plus` 不支持图片；同厂商同 key，换模型只需改一个环境变量 |
| D-16 | 验收用 **Pillow 渲染的合成题目图**（含旋转+噪声模拟拍摄），文档与报告中如实标注「合成图，非真实拍摄」 | 本项目没有真实学生错题照片可用，也不允许伪造；合成图能真实驱动视觉链路（模型确实读图），但结论只对「印刷体照片」有效，手写体表现记为已知限制 |

## 4. 数据模型（迁移 `0010_s4_2_mistakes.py`）

### 4.1 `mistakes`（对应 SCHEMA §5.3）

| 字段 | 类型 | 可空 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | BIGINT IDENTITY | 否 | 自增 | PK |
| `user_id` | BIGINT | 否 | — | FK `users.id`（`fk_mistakes_user_id`，**NO ACTION**：未声明 ondelete，PG 默认；删用户不级联删错题） |
| `question_id` | BIGINT | 否 | — | FK `questions.id`（`fk_mistakes_question_id`，**RESTRICT**，见 D-2） |
| `my_answer_md` | TEXT | 是 | — | 学生作答；识别不出为 NULL（D-14） |
| `correct_answer_md` | TEXT | 是 | — | 正确答案（从题目带出或识别得到） |
| `image_file_id` | BIGINT | 是 | — | FK `files.id`（`fk_mistakes_image_file_id`，SET NULL），拍照原图 |
| `status` | TEXT | 否 | `'待订正'` | `ck_mistakes_status`（§10.7 三值，`in_check()` 生成） |
| `correct_streak` | INTEGER | 否 | `0` | `ck_mistakes_correct_streak`（`>= 0`） |
| `created_at` | TIMESTAMPTZ | 否 | `now()` | — |
| `last_review_at` | TIMESTAMPTZ | 是 | — | 最近一次复习记录时间 |

表级：
- `uq_mistakes_user_question` = `UNIQUE(user_id, question_id)`（D-1）
- `ix_mistakes_user_status` = `(user_id, status)` → 列表主查询与状态统计
- `ix_mistakes_user_created` = `(user_id, created_at)`（升序，实测 DDL）→ 默认 `created_at DESC` 排序与时间筛选都走它；查询方向用反向扫描，不需要 DESC 索引
- `ix_mistakes_question_id` = `(question_id)` → S4-1 `_ensure_not_referenced` 的反查

### 4.2 `mistake_analyses`（对应 SCHEMA §5.4，本卡只建表）

| 字段 | 类型 | 可空 | 约束 |
|---|---|---|---|
| `id` | BIGINT IDENTITY | 否 | PK |
| `mistake_id` | BIGINT | 否 | FK `mistakes.id`（`fk_mistake_analyses_mistake_id`，**CASCADE**）+ `uq_mistake_analyses_mistake_id`（ER 为 1:1） |
| `kp_ids` | BIGINT[] | 是 | `ix_mistake_analyses_kp_ids` GIN |
| `cause_type` | TEXT | 否 | `ck_mistake_analyses_cause_type`（§10.8 七值） |
| `error_step` / `explanation_md` / `review_advice_md` | TEXT | 是 | — |
| `similar_questions_json` | JSONB | 是 | — |
| `model` | TEXT | 否 | — |
| `prompt_version` | TEXT | 否 | — |
| `created_at` | TIMESTAMPTZ | 否 | `now()` |

### 4.3 枚举（`app/models/enums.py` 追加）

```python
class MistakeStatus(StrEnum):
    TODO = "待订正"        # 初始态；答错也回到这里
    CORRECTED = "已订正"   # 复习答对 1 次
    MASTERED = "已掌握"    # 连续答对 ≥ 2 次（D-7）

class CauseType(StrEnum):
    CONCEPT = "概念不清"; CALC = "计算失误"; READING = "审题偏差"
    METHOD = "方法不当"; FORGET = "知识遗忘"; TIME = "时间不足"
    UNKNOWN = "unknown"    # 作答缺失，只讲题不猜错因（方案 6.3）
```

`status` 用中文值（SCHEMA §10.7 已定），API 出入参也用中文，前端只做徽标映射，不做翻译层。

## 5. AI 层（视觉识别）

### 5.1 LLM 适配器扩展（D-4）

`ai/llm/base.py`：

```python
@dataclass(frozen=True)
class LLMMessage:
    role: str                 # system | user | assistant
    content: str
    images: list[str] | None = None   # base64 data URL，仅 user 角色使用
```

`ai/llm/openai_compat.py` 组装规则：

- `images` 为空 → `{"role": role, "content": content}`（**与现状逐字一致**，现有调用零改动）；
- `images` 非空 → `{"role": role, "content": [{"type": "text", "text": content}, {"type": "image_url", "image_url": {"url": <data URL>}} ...]}`。

模型名由调用方传入（任务层从 `Settings.vision_model` 取），适配器不硬编码模型。

### 5.2 单图识别（`ai/vision/mistake_ocr.py`）

```python
class VisionExtract(BaseModel):
    stem_md: str                      # 题干 Markdown（含 LaTeX）
    my_answer_md: str | None          # 学生作答；读不出或不完整为 None（D-14）
    correct_answer_md: str | None     # 卷面印刷的答案
    qtype: Literal["单选", "多选", "填空", "解答"]
    options: list[ExtractedOption] | None   # 复用 ai/extract 的 ExtractedOption（非选择题为 None，校验规则同 S4-1）
    confidence: float                 # 0–1，模型自评

def extract_mistake(image_bytes, mime, *, subject_name, llm_client=None, max_retries=2) -> VisionExtract
```

- 入口先校验 `mime in {"image/png","image/jpeg","image/webp"}`（取 `files.mime`，不信任扩展名）与 `len(image_bytes) <= 8MB`，否则 `VisionError`；视觉层保留 webp 属防御性代码，但拍照上传链路只开放 PNG/JPEG（d-11），本链路实际不可达 WebP；
- 题型/选项一致性直接复用 `ExtractedQuestion` 的校验思路（选择题 ≥2 项且 key 唯一，填空/解答不带选项）；视觉层内自建 `VisionExtract` 而非直接复用 `ExtractedQuestion`，因为字段不同（无 `kp_names`，多 `my_answer_md`/`confidence`）；
- Prompt 固化在 `ai/prompts/mistake_ocr_v1.md`（Jinja2 `StrictUndefined`，变量只有 `subject_name`）；
- 严格 JSON + Pydantic 校验 + 最多 2 次重试（复用 S4-1 的 `_loads_json` 思路）；仍失败抛 `VisionError(带累计尝试次数)`；
- `scene="mistake_ocr"`，落 `llm_call_logs`；
- **不做** OCR 结果缓存：同一张图重试应重新识别（图片可能有裁剪差异）。

### 5.3 与题库的衔接（D-6）

任务在识别成功后调用 `question_service.create_question`：

1. 用 `stem_md` 规范化 + 判重（两道闸）；
2. 命中重复 → 取既有 `question_id`（`duplicated=true`，不新建）；
3. 未命中 → 建题（`origin="upload"`、`source_file_id=原图 file_id`、`verified=correct_answer_md is not None`、知识点对齐照 S4-1 的 LLM 候选内选择）。

## 6. 服务层（`services/mistake_service.py`）

| 函数 | 签名要点 | 事务/规则 |
|---|---|---|
| `create_from_question` | `(session, *, user_id: int, payload: MistakeCreateIn) -> tuple[MistakeDetailOut, bool]` | 校验题目存在（404）；按 `(user_id, question_id)` 复用并重置（D-1）；正确答案缺省时用题目的 `answer_md`；并发 INSERT 撞唯一约束时重查赢家后复用，不把 `IntegrityError` 冒成 500 |
| `start_photo_recognize` | `(session, *, owner: User, subject_id: int, upload: UploadFile, storage: ObjectStorage, queue: TaskQueue, my_answer_md: str \| None = None) -> AsyncTask` | 校验 subject 存在 → 扩展名预校验 PNG/JPEG → 上传（`parse=false`）→ `record.mime` 兜底 → `task_service.create_task(TASK_MISTAKE_RECOGNIZE, payload)` |
| `list_mistakes` | `(session, *, user_id, filters, page, sort) -> PageData[MistakeSummaryOut]` | 恒过滤 `user_id`；`cause_type` 走 EXISTS（D-3 原写 LEFT JOIN，以代码为准）；`kp_id` 走 EXISTS（D-9）；排序白名单 + `id DESC`（D-11）；`kp_names` / `cause_type` 一页各一次 `IN` 批查 |
| `get_detail` | `(session, *, user_id, mistake_id) -> MistakeDetailOut` | 带题目快照 + `analysis`（当前恒 `None`） |
| `update_mistake` | `(session, *, user_id, mistake_id, payload: MistakeUpdateIn) -> MistakeDetailOut` | 只允许改 `my_answer_md` / `correct_answer_md` / `status`；可空列显式 null = 清空，`status` 显式 null → 422（对齐 S4-1 I1 口径） |
| `record_review` | `(session, *, user_id, mistake_id, correct: bool) -> MistakeDetailOut` | 见 §6.1 |
| `stats` | `(session, *, user_id, created_from: datetime \| None = None, created_to: datetime \| None = None) -> MistakeStatsOut` | D-10 SQL 聚合，三个维度 |
| `delete_mistake` | `(session, *, user_id, mistake_id) -> None` | D-12，先删 analyses 再删主行 |
| 常量 | `TASK_MISTAKE_RECOGNIZE = "mistake.recognize"`、`MASTERY_STREAK = 2`、`LOW_CONFIDENCE = 0.5` | 常量归 service（task 反向 import），与 S3-1 同做法 |

### 6.1 状态机（D-7）

```
                 review(correct=true) 且 streak+1 < 2
   待订正 ───────────────────────────────────────► 已订正
     ▲   review(correct=true) 且 streak+1 >= 2          │
     │                                                  │ review(correct=true)
     │                                                  ▼
     └────────── review(correct=false): streak=0 ──► 已掌握
                     （status 退回 待订正）
```

- `correct=true`：`correct_streak += 1`，`last_review_at = now()`；`correct_streak >= 2` → `已掌握`，否则 `已订正`；
- `correct=false`：`correct_streak = 0`，`status = 待订正`，`last_review_at = now()`；
- 已掌握后再答错，同样回到 `待订正`（不保留历史峰值，`streak` 就是当前连续值）。

## 7. 异步任务（`tasks/mistake_recognize.py`）

```
payload = {
  "file_id": int,          # 已上传的图片；任务内重新下载，不落图片字节
  "subject_id": int,
  "user_id": int,
  "my_answer_md": str|None # 学生手填的作答（优先级高于识别结果）
}
```

处理步骤（handler **不 commit**，由 `tasks/runner.py` 统一提交）：

1. 查 `files`（属于 `user_id` 且是图片）→ `storage.get_object()` 下载到内存；
2. `_subject_name`（复用 S4-1 回退口径）→ `ai/vision.extract_mistake(...)`；
3. `question_service.create_question(...)`（D-6）→ 得到 `question_id` 与 `duplicated`；
4. `mistake_service.create_from_question(...)` 建错题，`image_file_id=file_id`；
5. `my_answer_md` 取「学生手填 > 识别结果 > None（D-14）」；
6. 返回结果 payload。

结果 payload：

```json
{
  "mistake_id": 12, "question_id": 65, "created": true, "reused_question": false,
  "confidence": 0.86, "low_confidence": false, "used_answer_source": "student|vision|none",
  "elapsed_ms": 9123
}
```

失败口径：识别失败 / 建题失败 → 抛异常，runner 置 `failed`，**图片保留在 `files`**（D-13）。重试 3 次仍失败时前端提示「换一张更清晰的照片或改用题库选题」。

## 8. 接口（`api/v1/mistakes.py`，8 个，`API.md` 新增 §6）

| # | 方法/路径 | 入参 | 出参 | 说明 |
|---|---|---|---|---|
| 1 | `POST /api/v1/mistakes` | `{question_id, my_answer_md?, correct_answer_md?}` | 201 `MistakeCreateOut`（= `MistakeDetailOut` + `created: bool`） | 从题库选；重复录入复用并重置（D-1），此时 `created=false` |
| 2 | `POST /api/v1/mistakes/photo` | multipart：`file` + `my_answer_md?`；query：`subject_id`（必填） | 202 `TaskOut` | 存图（`parse=false`）→ 入队 `mistake.recognize` |
| 3 | `GET /api/v1/mistakes` | `status? / cause_type? / kp_id? / created_from? / created_to? / page / page_size / sort_by / order` | 200 `PageData[MistakeSummary]` | 恒限本人 |
| 4 | `GET /api/v1/mistakes/stats` | `created_from? / created_to?` | 200 `{total, by_status[], by_cause[], top_kps[]}` | D-10 |
| 5 | `GET /api/v1/mistakes/{mistake_id}` | — | 200 `MistakeDetail` | 扁平返回题干/选项/作答与 `analysis`（当前 null），不是嵌套 `question` 快照 |
| 6 | `PATCH /api/v1/mistakes/{mistake_id}` | `{my_answer_md?, correct_answer_md?, status?}` | 200 `MistakeDetail` | 可空列传 null = 清空；`status` 传 null → 422/42200 |
| 7 | `POST /api/v1/mistakes/{mistake_id}/review` | `{correct: bool}` | 200 `MistakeDetail` | 驱动 streak（§6.1） |
| 8 | `DELETE /api/v1/mistakes/{mistake_id}` | — | 204 | 硬删（D-12） |

路由顺序：`/photo`、`/stats` 必须声明在 `/{mistake_id}` 之前（S4-1 `/import` 同款坑）。

出参模型（`schemas/mistake.py`）：

```python
class MistakeSummaryOut(BaseModel):
    id: int; question_id: int; status: str; correct_streak: int
    stem_excerpt: str            # 题干前 120 字，列表用
    subject_id: int; qtype: str; difficulty: int
    kp_names: list[str]          # 来自 question_kps，按 weight 降序
    cause_type: str | None       # 来自 mistake_analyses，S4-3 前恒 None
    has_image: bool
    created_at: datetime; last_review_at: datetime | None

class MistakeDetailOut(MistakeSummaryOut):
    stem_md: str; options: list[OptionOut] | None
    my_answer_md: str | None; correct_answer_md: str | None
    image_url: str | None        # /api/v1/files/{file_id}/image（需 Bearer，前端取 blob 后转 objectURL）
    analysis: MistakeAnalysisOut | None
```

错误码：`404/40400`（错题不存在或非本人、`/photo` 的 subject 不存在、题目不存在）、`422/42200`（入参非法：缺 `file`、非 PNG/JPEG、status 非法值/null）、`409/40900` 只在并发重复录入且重查不到赢家时出现（正常重复录入走复用语义，不报 409）。

## 9. 前端（`views/mistakes/`）

| 页面 | 内容 |
|---|---|
| `MistakeListView.vue` | 统计卡（总数/待订正/已订正/已掌握）+ 筛选（状态下拉、错因下拉、知识点树选择、日期区间）+ 表格（题干摘录、题型、知识点标签、状态徽标、连续答对、录入时间）+ 行操作（详情 / 复习答对 / 复习答错 / 删除二次确认；详情入口 Task 11 已补，与实现一致） |
| `MistakeNewView.vue` | 选学科 → 选图片（手机拍照直接调起相机，`capture` 属性）→ 可选手填作答 → 上传后轮询任务（4s 一次、约 60s 超时）→ 成功跳详情（低置信/重复录入只提示），失败给重试与「改用题库选题」两个出口 |
| `MistakeDetailView.vue` | 题干（`MdPreview` + KaTeX）、选项、我的作答、正确答案、状态操作、复习按钮；原图经 `getImageBlob` 取回并 revoke；**诊断区占位**显示「AI 错因诊断将在 S4-3 上线」 |

- 入口：侧栏「06 错题本」→ `/mistakes`；拍照页 `/mistakes/new`；详情 `/mistakes/:id`。
- 录入入口两个按钮：「从题库选题」（复用 `GET /questions` 弹窗选择）与「拍照录入」。
- 知识点筛选复用 S2-9 的 `GET /kp/tree`（已有接口，不新增）。

## 10. 测试计划（后端约 40 条 + 前端 6 条）

| 文件 | 覆盖 |
|---|---|
| `tests/test_mistake_service.py`（约 20） | 录入（新建/重复复用重置）、`question_id` 不存在 404、他人记录 404、`record_review` 三态流转（0→1→2→mastered、答错清零退回）、`PATCH status` null → 422、`stats` 三分组、删除连带 analyses、`list_mistakes` 的 `cause_type` 与 `kp_id` 都用 EXISTS（编译 SQL 断言）、排序白名单 + `id DESC` |
| `tests/test_mistake_vision.py`（约 8） | `extract_mistake` happy path、JSON 非法重试后成功、2 次仍失败抛 `VisionError`、mime 非图片拒绝、超大文件拒绝、`my_answer_md` 缺失为 None、`confidence` 透传、prompt 渲染含 `subject_name` |
| `tests/test_mistake_task.py`（约 8） | 任务成功建题+错题、命中判重复用既有题（`reused_question=true`）、学生手填作答优先于识别、识别失败任务抛错且 file 未删、落 `llm_call_logs`（scene 断言）、handler 不 commit（`session.commits == 0`） |
| `tests/test_mistakes_api.py`（约 10） | 8 个接口的状态码与 envelope、`/photo` 202、非图片 422、`/stats` 与 `/photo` 路由先于 `/{id}`、越权 404、删除 204 |
| `tests/test_llm_vision_message.py`（约 4） | `images=None` 时 payload 与现状逐字一致、有图时组装 `image_url` 数组、多图、system 消息不接受图片（拒绝或忽略并告警） |
| `web/.../MistakeListView.spec.ts`（6） | 渲染 3 条错题与统计数、状态筛选触发请求、复习答对调用 `reviewMistake(id, true)`、删除先 confirm、已掌握行隐藏复习按钮、诊断占位文案 |

## 11. 验收

### 11.1 自动

- `cd backend && ..\.venv\Scripts\python.exe -m pytest -q` 全绿（基线 865，本卡后 ≥905）；
- `cd web && npm run test:run` 全绿（基线 125，本卡后 ≥131）；
- `alembic upgrade head` → `0010_s4_2`，`alembic downgrade 0009_s4_1` 可回滚。

### 11.2 真机（必须贴实测输出）

1. **题库选录入 10 道**：`POST /mistakes` × 10 → 201；重复录 1 道 → `created=false` 且 `status` 回 `待订正`；
2. **拍照录入**：用 `测试数据/_make_s4_2_mistake_photos.py` 生成 3 张合成题目图（1 张纯净、1 张旋转 7°+高斯噪声、1 张带「我的作答」文本），`POST /mistakes/photo` → 202 → 轮询到 `succeeded`，核对识别出的题干与原题文字一致（逐字 diff 比例）、`my_answer_md` 是否正确提取；
3. **状态机**：对 1 道错题连续 `review(correct=true)` 两次 → `已订正` → `已掌握`；再 `review(correct=false)` → `待订正`、`correct_streak=0`；
4. **筛选与统计**：按 `status=待订正`、`cause_type`（当前应恒空）、`kp_id`、日期区间各查一次，`total` 与人工数一致；`/stats` 三组数字与人工统计一致；
5. **引用保护**：S4-1 的「删除被错题引用的题目 → 409」真机复验（本卡建表后该守卫首次生效）；
6. **前端**：浏览器打开 `/mistakes`，走一遍筛选/复习/删除/拍照上传，贴路径与现象。

### 11.3 如实记录的边界

- 合成图 = 印刷体，**手写体识别效果未验证**，不得表述为「支持学生手写拍照」；
- 视觉模型自评 `confidence` 未经校准，只作为提示位，不参与硬判定。

## 12. 文档同步

- `docs/API.md` 新增 §6（8 个接口 + 错误码 + 出参模型）；
- `docs/SCHEMA.md` §5.3 补 `UNIQUE(user_id, question_id)`、三个索引与 `ck_` 名；§5.4 补 CASCADE 与 GIN 口径；§10.7/§10.8 标 ✅；
- `AGENTS.md` §9.2 新增「错题（S4-2）」条目；§9.6 补错题锚点（model/service/task/api/vision 六件套）；
- `docs/DECISIONS.md`：新增决策「拍照走异步任务 + 视觉适配器扩 `images`」「重复录入复用重置」「错题仅本人可见」；
- `docs/PROGRESS.md`：S4-2 状态行 + 验收数字 + 遗留（手写体、confidence 未校准、无多图）；
- `docs/AI协作开发实施计划.md`：S4-2 勾选与实施记录；
- `.env.example` 增 `VISION_MODEL`。

## 13. 已知限制（实现后按实回填）

1. 手写体识别未验证（合成图为印刷体）；
2. `confidence` 为模型自评，未校准，只做提示；
3. 一图一题，多题同框需学生自己裁成多张；
4. 错因筛选在 S4-3 有数据前恒为「无结果」，前端需明确提示「待诊断」；
5. `mistake_analyses` 建表但不写入，S4-3 之前 `analysis` 恒 `null`；
6. 拍照建题会进入公共题库（S4-1 的 D-3 口径），低质量照片题可能污染题库（遗留 82 已记录）；
7. 未做图片预处理（裁边/纠偏/增强），暗光或倾斜过大时识别质量下降。

## 14. 开工前必须先验证的技术假设

**Qwen-VL 的 OpenAI 兼容接口是否接受 base64 data URL。** DashScope 兼容模式对 `image_url.url` 的支持有两种可能形态（data URL 或公网 URL），本地对象在 MinIO 内网、没有公网地址，所以只能走 base64。若实测不接受，则降级方案依次为：

1. 改用 DashScope 原生 `multimodal-generation` 接口（多一个适配器，不引新依赖，`httpx` 已在用）；
2. 把图片临时转为可访问 URL（需要暴露 MinIO，本机可做但部署侧要额外配置，优先级最低）。

**处置**：plan 的第 1 步就是这个探针（一个独立脚本，拿 1 张合成图打真实接口，记录请求/响应），探针通过后再写 `ai/vision` 的正式代码。这条写在 spec 里，是因为它决定适配器形态，属于设计级不确定，不是实现细节。