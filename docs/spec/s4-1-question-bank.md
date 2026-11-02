# S4-1 题库表 + 试卷切题 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S4-1
- 日期：2026-11-02
- 状态：设计已逐节确认，待用户评审本文
- 上游：S1-1 解析门面 `ai/parse/parse_document()`、S2-6 文件上传、S2-7 异步任务、S2-9 知识点树（108 节点，`knowledge_points.embedding` 已补齐）、S2-10 对齐打分 `ai/align/scoring.py`
- 下游：S4-2 错题录入（从题库选题）、S4-3 错因诊断（按 `question.kp_ids` 定位）、S4-8 看板（知识点 TOP10）、S5-1 组卷（按知识点配额选题）、S5-4 作答判分
- 产物：`models/question.py`、`models/question_kp.py`、迁移 `0009_s4_1_questions.py`、`ai/extract/{splitter,question_extractor}.py`、`ai/prompts/question_extract_v1.md`、`services/question_service.py`、`tasks/question_extract.py`、`api/v1/questions.py`、`schemas/question.py`、前端 `views/questions/{ImportView,ReviewView}.vue`、`测试数据/高中数学试卷-高二期末综合卷（20题）.docx`

## 1. 目标

1. 建 `questions` / `question_kps` 两表，字段与 `SCHEMA.md` §5.1/§5.2 一一对应（§5.1 已补 `stem_hash` 列，见 D-1）。
2. 支持上传一份 PDF/DOCX 试卷，**异步切题**：规则预切题号 → 逐题 LLM 结构化 → 判重 → 挂知识点 → 落库。
3. 判重两道闸：规范化题干 `stem_hash` 唯一约束 + 题干向量余弦 ≥ 0.92，命中即跳过。
4. 每题按 S2-10 公式自动对齐知识点（≥0.75 才挂），`question_kps.weight` 存原始分。
5. 提供题目 CRUD 与**合并 / 拆分**，支撑“AI 切题会漏题、串题”的人工兜底。
6. 前端两页：导入（上传 → 轮询 → 结果概览）+ 审题（逐题编辑 / 新增 / 合并 / 拆分 / 调知识点）。
7. 用一份 ≥20 题的验收卷真实跑通，重复导入幂等，人工核对结果如实记录。

非目标：拍照/扫描件识别（D-2，S4-2 做多模态）、AI 生成题（S4-4）、错题录入（S4-2）、组卷（S5-1）、图谱关系（S4-5）、题目审核工作流。

## 2. 范围

### 2.1 做

- `app/models/question.py`、`app/models/question_kp.py` + `alembic/versions/0009_s4_1_questions.py`。
- `app/ai/extract/splitter.py`：纯函数（卷头清理 + 题号预切 + 声明题数解析 + 兜底判定）。
- `app/ai/extract/question_extractor.py` + `app/ai/prompts/question_extract_v1.md`：单题/整块统一 schema，严格 JSON + Pydantic + 最多 2 次重试。
- `app/services/question_service.py`：`normalize_stem`、`stem_hash`、批量 embedding、判重、知识点对齐、CRUD、合并、拆分、入队。
- `app/tasks/question_extract.py` + 注册：`question.extract` 任务。
- `app/api/v1/questions.py` + `app/schemas/question.py`：9 个接口（见 §6）。
- `app/services/file_service.py`：放宽 `parse=False` 的文件类型限制（见 D-4），`POST /api/v1/files` 的 `parse` 参数说明同步。
- 前端 `views/questions/ImportView.vue`、`views/questions/ReviewView.vue`、`api/questions.ts`、路由与侧栏入口（`/questions`）。
- `测试数据/高中数学试卷-高二期末综合卷（20题）.docx` + 生成脚本 `测试数据/_make_s4_1_exam_paper.py`。
- 测试约 52 条后端 + 6 条前端（见 §8）。
- 文档：`API.md` 新增 §5.5、`SCHEMA.md` §5.1/§5.2（已改）、`AGENTS.md` §9.2/§9.6、`DECISIONS.md`、`PROGRESS.md`、实施计划勾选。

### 2.2 不做

- 不做图片/扫描件识别：`parse_document()` 返回 `is_scanned` 时任务直接失败并给出明确提示，不静默成功。
- 不把试卷写成 `notes`、不切片、不写 `note_chunks`、不进向量检索池。
- 不做题级进度（D-13）；前端只轮询任务状态与已用时。
- 不新增 `async_tasks.progress` 列，不改 S2-7 契约。
- 不做题目软删除（`questions` 无 `deleted_at`），删除为硬删且受引用保护。
- 不做题库审核工作流 / 版本历史 / 导入批次表。
- 不做“切题结果暂存草稿”：任务结束即落库，人工在审题页修正。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| D-1 | `questions` 增加 `stem_hash TEXT NOT NULL` + `UNIQUE(subject_id, stem_hash)`（已更新 SCHEMA §5.1） | SCHEMA §9 要求“规范化题干哈希”判重，原表无处存放；同题在不同学科下允许共存，故唯一键带 `subject_id` |
| D-2 | 本卡只支持 PDF/DOCX；图片与扫描件明确失败 | `ai/parse` 无 OCR 能力，`ai/ocr/` 只有占位；多模态适配器随 S4-2 拍照错题一起做，避免本卡引入未验证链路 |
| D-3 | 题库为**公共语料**（无 `user_id`），任何登录用户可读；写限于创建者本人或 teacher/admin | 与 SCHEMA §5.1 现状一致，数据隔离清单（S2-3）未把题目算作学生私有数据 |
| D-4 | 新增 `POST /questions/import`；复用 `files` 表存原件（`file_service.upload_file(parse=False)`），不触发 `parse.document` | 复用 S2-6 的流式校验/sha256 去重/magic 校验；试卷不该变成文档笔记。`parse=False` 现有“仅图片”限制放宽为“图片或 PDF/DOCX” |
| D-5 | 切题 = **规则预切 + 单题 LLM**，块数不足时整卷兜底 | 题目边界由确定性规则给出，从根上避免串题；单题失败只重试单题。兜底同用一套 schema，只是 `mode=block` 允许返回多条 |
| D-6 | 单题/整块统一输出 schema：`questions: [...]` 数组，单题模式下断言长度为 1 | 一套 prompt + 一套 Pydantic 模型覆盖两种模式，减少分叉 |
| D-7 | 允许**部分成功**：单题 3 次重试仍失败 → 进 `result.failed_items`，任务仍 `succeeded` | 20 题里坏 1 题不该让整卷白切；缺口必须显式暴露给人工补录 |
| D-8 | 判重：先 `stem_hash` 命中唯一约束，未命中再比 `embedding` 余弦 ≥ 0.92 | SCHEMA §9 两道闸；哈希便宜先走，向量兜“改数字/换语序”的近似题 |
| D-9 | 一次批量 embedding 同时服务判重与知识点召回 | 20 题一次 `encode()`，比逐题调用省 19 次请求；向量同时用于 cos 判重与候选召回 |
| D-10 | 知识点对齐**不额外调 LLM**：LLM 只输出自由文本 `kp_names` 作为关键词信号，最终由确定性公式裁决 | 复用 S2-10 的 `0.6*cos + 0.3*keyword + 0.1*prior`；幻觉出来的知识点名只影响关键词分，不会被直接落库 |
| D-11 | 卷头清理只在**第一个题号出现之前**的行做，卷尾只在**最后一个题号之后**的行做 | 避免把解答题里的“某中学”“姓名”误删；这是“误删题干”风险的正解 |
| D-12 | `verified` 语义扩展：卷面自带答案 → `true`；答案由 LLM 补写 → `false`；无答案 → `false` | 沿用方案 6.5“答案是否可信”的含义，并区分来源 |
| D-13 | 不做题级进度，`async_tasks.result` 只存最终结果 | 20 题约 60–90s，可接受；不为进度改 S2-7 已有表 |
| D-14 | “重切单题”不做接口：**重复导入同一份卷子 = 补漏**，已入库题被哈希跳过，只补缺失题 | 幂等带来的自然能力，少一个接口与一套状态 |
| D-15 | 合并/拆分/删除均为**硬删**；删除前检查 `mistakes` 引用，但用 `has_table` 守卫——表不存在（S4-1 阶段）时跳过，S4-2 建表后自动生效 | `questions` 无 `deleted_at`；错题引用后删题会让错题失去题干。守卫避免 S4-1 依赖尚未存在的表，也避免 S4-2 回头改 S4-1 代码 |
| D-16 | 任务 payload 只带 `file_id`（+ 冗余 `subject_id/origin` 便于校验），题面文本不落 `async_tasks` | 避免把整卷正文写进任务表；重试时重新下载解析，保证幂等 |

## 4. 切题规则（`ai/extract/splitter.py`）

### 4.1 输入输出

```python
@dataclass(frozen=True)
class QuestionBlock:
    index: int                      # 1-based，用于失败定位
    text: str                       # 该题原文（含小问、选项、解析）
    section_qtype: str | None       # 由所属大题标题推断的题型提示
    section_index: int              # 所属大题序号

@dataclass(frozen=True)
class SplitResult:
    blocks: list[QuestionBlock]
    detected_count: int
    expected_count: int | None      # 各大题“共 N 小题”之和
    degraded: bool                  # True = 走整卷兜底
    warnings: list[str]             # 跳号、块数不符等，进任务日志与 result
```

### 4.2 步骤

1. **拼行**：`ParsedDocument.blocks` 按顺序展开为行，保留 `page_no`。
2. **大题标题识别**（正则）：
   `^\s*([一二三四五六七八九十]+)\s*[、.．]\s*(选择题|多选题|填空题|解答题|判断题|计算题|证明题)`
   命中后记录大题序号、题型提示，并从同段解析声明题数：`共\s*(\d+)\s*小题` 或 `\((\d+)\s*小题`。
3. **首题号定位**：第一处匹配 `^\s*(\d{1,2})\s*[.．、]\s*\S` 的行（**必须行首**）。
4. **卷头清理**：只对第 3 步之前的行生效，命中 `姓名|班级|考号|学号|密封线|密\s*封\s*线|学校|中学|命题人|审核人|考试时间|满分|注意事项|答题卡` 的行整行删除。清理后若首题号之前已无内容，直接丢弃。
5. **主题号切分**：首题号之后，行首匹配 `^\s*(\d{1,2})\s*[.．、]\s*` 视为新题起点；题号应递增，跳号只记 `warnings.append("题号跳号: 3")`，不丢块。
6. **小问不切**：`（1）` `(1)` `1)` `①`–`⑩` 等一律视为题内内容。
7. **卷尾清理**：最后一个主题号之后命中 `第\s*\d+\s*页|共\s*\d+\s*页|答题卡` 的行删除。
8. **判定兜底**：
   - `expected_count` 有值且 `detected_count != expected_count` → `degraded=True`；
   - 或 `detected_count < 3` 且 `expected_count >= 10` → `degraded=True`；
   - 无任何大题标题且 `detected_count < 3` → `degraded=True`。
9. `degraded=True` 时把**整卷文本**（卷头清理后）作为一个 block 交给 `mode="block"` 的抽取，由 LLM 内部切题。

### 4.3 纯函数约束

- 无 IO、无 DB、无 LLM，全部输入是文本与行列表；`warnings` 用 `list[str]` 返回而不是打日志（日志由调用方打）。
- 所有正则集中在本文件顶部并加注释，便于按真实卷子调参。

## 5. 抽取与对齐

### 5.1 抽取（`ai/extract/question_extractor.py`）

- Prompt：`ai/prompts/question_extract_v1.md`（Jinja2，`StrictUndefined`），变量 `mode`、`subject_name`、`section_qtype`、`expected_count`、`question_text`。
- 输出 schema（Pydantic，字段名即 JSON 键）：

```python
class ExtractedOption(BaseModel):
    key: str        # A/B/C/D
    text: str

class ExtractedQuestion(BaseModel):
    stem_md: str                     # 题干，公式用 $...$
    options: list[ExtractedOption] | None
    answer_md: str | None
    analysis_md: str | None
    qtype: Literal["单选", "多选", "填空", "解答"]
    difficulty: int                  # 1–5
    kp_names: list[str]              # LLM 认为涉及的知识点名称（自由文本）
    answer_source: Literal["paper", "ai", "none"]   # 卷面带答案 / LLM 补写 / 无答案
```

- 校验规则（Pydantic `model_validator`）：
  - `qtype in {单选, 多选}` → `options` 至少 2 项且 key 唯一；`answer_md` 非空时其首字母必须落在选项 key 集合内（单选恰好 1 个字母）。
  - `qtype in {填空, 解答}` → `options` 必须为 `None`。
  - `stem_md` 去空白后长度 ≥ 5。
  - `difficulty` 越界或 `qtype` 非法 → 校验失败，进重试。
- 最多 2 次重试（共 3 次调用）；`scene="gen"`；失败抛 `QuestionExtractError`，由任务计入 `failed_items`。
- 单题模式（`mode="single"`）下 `len(questions) != 1` → 视为失败并重试；`mode="block"` 允许 1..`expected_count` 条，超出部分截断并记 warning。
- `stem_latex` 与 `tags` 本卡不填：前者仅在“整题可由单个公式表达”时才该有值（切题场景几乎不成立），后者属于人工标注，均留 `NULL`。前端编辑接口支持后续补。`verified` 按 `answer_source` 推导（D-12）。

### 5.2 规范化与哈希（`question_service.normalize_stem` / `compute_stem_hash`）

```text
1. 去掉行首题号前缀（\d{1,2}[.．、]\s*）
2. 全角字符转半角（含全角空格、全角括号、全角字母）
3. 删除所有空白字符
4. 删除行首行尾的标点（，。；：、,.）
5. sha256(utf-8) 十六进制
```

不删数字、不删 `$`/`\`（LaTeX 是题干语义的一部分）。同一题不同排版（多余空格、全角标点）→ 同一哈希；改一个数 → 不同哈希。

### 5.3 判重（`question_service.check_duplicate`）

```text
1. SELECT ... WHERE subject_id = :sid AND stem_hash = :hash  → 命中即返回该题
2. 未命中：在 subject 内做向量检索 top-1（cosine），cos ≥ 0.92 → 返回该题
3. 都未命中 → None
```

### 5.4 知识点对齐（`question_service.align_knowledge_points`）

```text
候选：同 subject 全部知识点（embedding 已由 ensure_kp_embeddings 补齐）
cos   = clamp(1 - cosine_distance, 0, 1)                     # 题干向量 vs 节点向量
keyword = max(keyword_score(kp.name, 题干), keyword_score(kp.name, " ".join(kp_names)))
prior = tree_prior(kp.level, kp.ancestor_names, tags=kp_names, title=题干前 200 字)
score = 0.6*cos + 0.3*keyword + 0.1*prior
```

- 取 top-10 候选，**score ≥ 0.75 才写 `question_kps`**，`weight` 存 `score`（NUMERIC 6 位小数）。
- 每题最多写 3 个知识点（按分降序），避免一题挂满全树。
- 打分与阈值直接复用 `ai/align/scoring.py` 的 `combine / classify / keyword_score / tree_prior / AUTO_THRESHOLD`，**不复制常量**。

## 6. 接口（API.md 新增 §5.5）

### POST /api/v1/questions/import
- 权限：`student` / `teacher` / `admin`
- 类型：异步任务
- 入参：multipart `file`（.pdf/.docx）+ `subject_id`（int，必填）+ `origin`（`upload` 默认；student 只能 `upload`，teacher/admin 可选 `exam/mock/textbook`）
- 出参：**202** `Envelope[TaskOut]`（`id` / `name`=`question.extract` / `status` / `created_at`）
- 笔记：原件落 `files`（`parse_status=done`），不入 `parse.document` 队列
- 错误：`400/40000` 类型不支持或非 PDF/DOCX；`403/40300` student 选了非 `upload` 的 origin；`404/40400` subject 不存在；`503/50300` 队列不可用；`422/42200` 缺文件/缺 subject

### GET /api/v1/tasks/{task_id}
- 复用 S2-7，**不新增**。`result` 结构：
```json
{"file_id": 7, "subject_id": 7, "detected_count": 20, "expected_count": 20,
 "created": 18, "duplicated": 2,
 "failed_items": [{"index": 13, "reason": "校验失败：选择题选项少于 2 项"}],
 "degraded": false, "warnings": [], "elapsed_ms": 63400}
```

### GET /api/v1/questions
- 权限：登录用户（公共题库）
- 类型：同步分页
- 入参：`page` / `page_size` / `subject_id` / `qtype` / `kp_id` / `origin` / `created_by`（`me` 表示只看自己导入的）/ `verified` / `keyword`（题干模糊）/ `sort`（白名单：`created_at` `id` `difficulty`）+ `order`
- 出参：`Envelope[PageData[QuestionSummary]]`
- 错误：`422/42200` 分页越界或非法排序字段

### GET /api/v1/questions/{question_id}
- 权限：登录用户
- 出参：`Envelope[QuestionDetail]`（含 `options_json`、`kp_ids`、`kps[]`：`kp_id/kp_name/kp_code/weight`、`source_file_id`、`created_by`、`created_at`）
- 错误：`404/40400`

### POST /api/v1/questions
- 权限：`student` / `teacher` / `admin`
- 入参：`{subject_id, stem_md, options?(list), answer_md?, analysis_md?, qtype, difficulty, kp_ids?, origin?}`
- 行为：规范化 → 判重（命中返回 **409/40900** 并附已存在题目 id）→ 补 embedding → 落库 → 按 `kp_ids` 直写 `question_kps(weight=1.0)`（人工指定不参与打分）
- 出参：**201** `Envelope[QuestionDetail]`
- 错误：`409/40900` 判重命中；`422/42200` 字段非法；`404/40400` subject/kp 不存在

### PATCH /api/v1/questions/{question_id}
- 权限：创建者本人 / teacher / admin（否则 `403/40300`）
- 入参：上述字段的可选子集 + `kp_ids?`（传则整体替换）
- 行为：题干变化 → 重算 `stem_hash` + 重算 `embedding` + 重新判重（撞别人已存在题 → `409/40900`）；`kp_ids` 传空数组 = 清空
- 出参：`Envelope[QuestionDetail]`

### POST /api/v1/questions/{question_id}/split
- 权限：同 PATCH
- 入参：`{"split_at": "2."}`（在题干中该标记处切开）
- 行为：按标记切成两题，各自重算 hash/embedding/知识点；原题硬删
- 出参：`Envelope[list[QuestionDetail]]`（长度 2，顺序与原题干一致）
- 错误：`400/40000` 切点未匹配或切出的任一半去空白后 < 5 字；`409/40900` 原题被错题引用

### POST /api/v1/questions/merge
- 权限：同 PATCH（要求对**全部** id 都有权）
- 入参：`{"ids": [a, b]}`（2–10 个）
- 行为：按 id 升序拼接题干（空行分隔），取第一题的 subject/qtype/difficulty，答案与解析按同样顺序拼接；新题重算 hash/embedding/知识点；原题硬删
- 出参：`Envelope[QuestionDetail]`
- 错误：`400/40000` 题目不属于同一 subject；`409/40900` 任一原题被错题引用；`403/40300` 任一题无权

### DELETE /api/v1/questions/{question_id}
- 权限：同 PATCH
- 行为：硬删；`question_kps` 级联删除
- 出参：**204**
- 错误：`409/40900` 被 `mistakes.question_id` 引用（`mistakes` 表不存在时跳过该检查，见 D-15）

## 7. 组件契约

### `models/question.py`

按 `SCHEMA.md` §5.1：`id`（BIGINT IDENTITY）、`subject_id`（FK subjects）、`origin`、`source_file_id`（FK files，可空）、`stem_md`、`stem_latex`、`stem_hash`、`options_json`（JSONB）、`answer_md`、`analysis_md`、`qtype`、`difficulty`（SMALLINT）、`tags`（TEXT[]）、`verified`、`embedding`（VECTOR(1024)）、`created_by`（FK users，可空）、`created_at`。

约束：`ck_questions_origin`、`ck_questions_qtype`（值集常量进 `models/enums.py`：`QuestionOrigin` / `QuestionType`）、`ck_questions_difficulty`（1–5）、`uq_questions_subject_stem_hash`、`ix_questions_subject_id`、`ix_questions_origin`、`ix_questions_qtype`、`ix_questions_embedding_hnsw`、GIN(`tags`)。

### `models/question_kp.py`

复合 PK `(question_id, kp_id)`；两列 FK 均 `ON DELETE CASCADE`；`weight NUMERIC`；`ix_question_kps_kp_id`。

### `services/question_service.py`

```python
TASK_QUESTION_EXTRACT = "question.extract"   # 常量放 service，task 反向导入（同 S3-1 避免循环导入）

def normalize_stem(text: str) -> str: ...
def compute_stem_hash(text: str) -> str: ...
def embedding_text(question_stem: str) -> str: ...          # 去 LaTeX 分隔符，供 encode
def check_duplicate(session, *, subject_id: int, stem_hash: str, vec: list[float]) -> Question | None: ...
def align_knowledge_points(session, *, subject_id: int, text: str, kp_names: list[str],
                           vec: list[float]) -> list[tuple[int, Decimal]]: ...
def create_question(session, *, payload: QuestionCreateIn, creator: User,
                    embedder=None) -> Question: ...          # 判重 → 落库 → 挂 kp；命中抛 ConflictError
def update_question(session, *, question_id: int, payload: QuestionUpdateIn, viewer: User,
                    embedder=None) -> Question: ...
def split_question(session, *, question_id: int, split_at: str, viewer: User, embedder=None) -> list[Question]: ...
def merge_questions(session, *, ids: list[int], viewer: User, embedder=None) -> Question: ...
def delete_question(session, *, question_id: int, viewer: User) -> None: ...
def ensure_can_edit(question: Question, viewer: User) -> None: ...   # 非创建者且非 teacher/admin → 403
def list_questions(session, *, filters: QuestionFilters, page: PageParams, sort: SortParams) -> PageData[Question]: ...
def build_questions_query(session, *, filters: QuestionFilters): ...  # subject/qtype/origin/created_by/verified/kp_id 下推
```

`kp_id` 过滤用 `EXISTS (SELECT 1 FROM question_kps qk WHERE qk.question_id = questions.id AND qk.kp_id = :kp)`，避免 join 造成重复行。

### `tasks/question_extract.py`

```python
@register(TASK_QUESTION_EXTRACT)
def question_extract_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    # 1) 校验 file 存在、属于任务 owner、后缀 ∈ {.pdf, .docx}
    # 2) 下载对象到临时文件 → parse_document() → is_scanned 直接失败
    # 3) split_questions() → degraded 时 mode="block"
    # 4) 逐 block：extractor.extract_questions() → 失败收集 failed_items
    # 5) 批量 encode 全部题干的 embedding_text（一次调用）
    # 6) 逐题：check_duplicate → 命中计 duplicated；否则 create_question
    # 7) 返回统计字典（即 result）
```

- 临时文件清理放 `finally`，Windows 句柄占用只记 WARNING（同 S2-8）。
- **不自行 commit `async_tasks` 状态**；题目逐题写入可就地 `flush`，最终由 runner 统一提交（避免半卷脏数据）。
- 任一步骤整体失败（文件不存在/解析失败/无文本）→ 抛异常，任务 `failed`，`error` 写清楚原因。

### 前端

- `views/questions/ImportView.vue`：学科选择 + 文件选择（PDF/DOCX）+ origin（教师/管理员可见）+ 上传 → 轮询 `GET /tasks/{id}`（1.5s 间隔）→ 成功后展示统计并跳审题页（带 `?file_id=` 筛选）。
- `views/questions/ReviewView.vue`：左列表（按 `source_file_id` 或 `subject_id` 筛选）+ 右卡片编辑；支持新增、合并（多选两题）、拆分（在题干 textarea 里选中光标位置切分）、知识点多选、KaTeX 渲染预览（复用 S3-8 的 Markdown + KaTeX 渲染组件）。
- `api/questions.ts`：仅通过 `http.ts` 调接口；类型定义与 `schema` 对齐。
- 路由与导航：新增 `/questions`（`name: 'questions'`，学生/教师/管理员可见），`layouts/nav.ts` 插入“题库”并把后续项序号顺延为 `05 智能问答 / 06 错题本 / 07 复习计划`（现有代码与测试未硬编码序号，已核对）。
- 权限差异：student 对非本人创建的题只能看，编辑按钮置灰并提示（不弹 403）。

## 8. 测试计划（约 48 条）

`tests/test_question_splitter.py`（14）
1. `1.` / `1、` / `1．` 三种题号都能切
2. 行内出现 `1.` 但不在此行行首不切
3. 解答题内 `（1）（2）` 不切
4. `1)` 小问不切
5. 大题标题解析出题型与“共 8 小题”
6. `expected_count` 为各大题之和
7. 跳号只记 warning、不丢块
8. 卷头“姓名/班级/考号/密封线”被删
9. 卷头含“某中学”的**题目正文**不被删
10. 卷尾“第 1 页 共 4 页”被删
11. 无题号整段 → `degraded=True`
12. 切出数 ≠ 声明数 → `degraded=True`
13. 空文本 → 0 块且 `degraded=True`
14. 题号 10、11 两位数不误判为 1

`tests/test_question_service.py`（14）
1. `normalize_stem` 去题号与空白
2. 全角转半角后 hash 相同
3. 改一个数字 hash 不同
4. `check_duplicate` 哈希命中返回原题
5. 哈希未命中、cos ≥ 0.92 返回原题
6. 都不命中返回 None
7. `align_knowledge_points` ≥0.75 才返回
8. 每题最多 3 个知识点
9. `create_question` 判重命中抛 `ConflictError`
10. `create_question` 落库并写 `question_kps(weight=1.0)`（人工指定）
11. `update_question` 改题干后 `stem_hash`/`embedding` 都更新
12. `delete_question`：`mistakes` 表不存在时正常删除并级联清 `question_kps`；临时建表且有引用时抛 `ConflictError`
13. `merge_questions` 拼接顺序与 subject 校验
14. `split_question` 切点不存在 → `InvalidParamError`

`tests/test_question_extractor.py`（8）
1. 合法单题 JSON → 1 条 `ExtractedQuestion`
2. 合法整块 JSON → 多条
3. 选择题 options 少于 2 项 → 重试
4. 单选答案不在选项 key 内 → 重试
5. 填空/解答带 options → 重试
6. 连续 3 次非法 → `QuestionExtractError`
7. `mode="single"` 返回 2 条 → 截断为 1 并记 warning
8. 整块返回数超过 `expected_count` → 截断

`tests/test_question_task.py`（6）
1. 正常切 20 题 → `created=20`
2. 重复导入 → `duplicated=20, created=0`
3. 单题 3 次失败 → 进 `failed_items`，任务仍成功
4. `is_scanned` → 任务失败且 error 含“扫描”
5. 文件不属于 owner → 失败
6. 无文本 → 失败

`tests/test_questions_api.py`（10）
1. 导入 202 且任务名正确
2. student 传 `origin=exam` → 403
3. 列表分页结构与默认排序
4. 列表按 `kp_id` 过滤
5. 详情含 `kps[]`
6. 手动新增 201
7. 手动新增重复 → 409 且带已存在 id
8. 他人改题 → 403
9. 合并 subject 不同 → 400
10. 删除被引用 → 409

`web/src/views/questions/__tests__/ReviewView.spec.ts`（6）
1. 渲染题目列表
2. 编辑题干后保存调用 PATCH
3. 合并按钮在两题选中时可用
4. 拆分调用 POST split
5. KaTeX 公式渲染
6. student 对他人题目编辑按钮置灰

## 9. 验收

### 9.1 验收数据

`测试数据/高中数学试卷-高二期末综合卷（20题）.docx`（脚本生成）：8 单选 + 4 填空 + 8 解答 = 20 题，带答案与解析，公式用 Unicode 上下标排版。

> **如实标注**：这是**本人自编**的 20 题高中数学卷（知识点与题型按高考卷结构组织），不是外部真实试卷。`PROGRESS.md` 与论文中必须这样写，不得冒充真题。

### 9.2 步骤

1. `pytest` 全绿；`npm run test` + `npm run build` 通过。
2. 起 `uvicorn` + `arq` worker + 前端；用 student 登录。
3. 上传验收卷 → 记录 `task_id`；轮询到 `succeeded`，记录 `detected_count / created / duplicated / failed_items / elapsed_ms`。
4. 打开审题页逐题核对，按“可直接用 / 需小改 / 需重录”三档计数，记录数字。
5. **再导入同一份卷子一次** → 断言 `created=0, duplicated=20`（幂等）。
6. 抽 5 题检查知识点（`GET /questions/{id}` 的 `kps[]`）是否合理，记录命中/不命中。
7. 制造漏题场景：手动删 1 题后重新导入 → 只补回该题（`created=1`）。
8. 合并 2 题、拆分 1 题、编辑 1 题，刷新后校验结果；删除 1 道无引用的题 → 204 且 `question_kps` 级联清理（错题引用保护待 S4-2 建 `mistakes` 后补验）。
9. 清理测试数据，`pytest` 复跑全绿。

### 9.3 通过标准

- 切出 **≥20 道**，题号连续、无串题；公式 KaTeX 渲染正常、答案与原卷一致。
- 重复导入幂等（`created=0`）。
- 人工核对“可直接用”占比 ≥ 80%，其余如实记录。
- 单测覆盖 D-1/D-8/D-10/D-11/D-15 的关键分支。

## 10. 文档同步

- `SCHEMA.md` §5.1（`stem_hash`、`verified` 语义、判重规则）、§5.2（索引与 weight 语义）——**已完成**。
- `API.md`：新增 `## 5.5 题库与试卷切题（S4-1 定稿）`，9 个接口定稿；§3 `POST /files` 的 `parse` 参数说明补充“试卷原件传 false”。
- `AGENTS.md` §9.2 增补题库规则（不生成笔记、两道闸判重、0.75 阈值、硬删+引用保护）；§9.6 增补“题库/切题锚点”。
- `DECISIONS.md` 新增 D-0xx（题库公共化 + `stem_hash` 契约变更 + 部分成功语义）。
- `PROGRESS.md` 状态、清单勾选、变更日志、遗留（拍照切题待 S4-2）。
- `docs/AI协作开发实施计划.md` 第 14 章 S4-1 勾选。
- 提交：`feat(s4-1): ...`（Conventional Commits）。

## 11. 已知限制

- 只认 PDF/DOCX；图片与扫描件明确失败（S4-2 补多模态）。
- 规则预切依赖规范题号；不规范卷子走整卷兜底，兜底漏题率高于逐题模式，`degraded` 标记会暴露但不会自动修复。
- 知识点对齐是“向量 + 关键词 + 树先验”的近似，跨章节的复合题（如“导数 + 数列”）通常只能挂上 1–2 个最显著的知识点。
- LLM 补写的答案不可信（`verified=false`），界面必须标注。
- 判重对“同题换数字”（变式题）不拦，只拦近似重复（cos ≥ 0.92）。
- 试卷原件留在 `files` 表（`parse_status=done`），文件页会与普通附件混排；本卡不区分用途。
- 合并/拆分是硬删原题，操作不可撤销；前端必须二次确认。
- 题库公共：任何登录用户可见全部题目，仅写权限受限；多用户环境下存在“学生导入低质量题”的风险，本卡不建审核流。
- 任务耗时随题量线性增长（约 3s/题），无题级进度；中断后重跑整卷（已入库题会被跳过）。