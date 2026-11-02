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
4. 每题自动对齐知识点：向量召回同 subject 全部知识点 top-10，**由 LLM 在候选内选择**（只收候选内 `kp_id` 且 `confidence ≥ 0.5`）；`question_kps.weight` 存 `0.6*cos + 0.3*keyword + 0.1*prior`（6 位小数）。
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
- `app/api/v1/questions.py` + `app/schemas/question.py`：8 个新接口 + 复用 `GET /tasks/{task_id}`（见 §6）。
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
| D-5 | 切题 = **规则预切 + 单题 LLM**；规则判定 `degraded` 时改用 `mode=block` 逐块抽取（同 schema 允许一次返回多条）；一个 block 都切不出则任务失败，不做整卷静默重切 | 题目边界由确定性规则给出，从根上避免串题；单题失败只重试单题。`degraded` 显式暴露而不是悄悄重跑整卷 |
| D-6 | 单题/整块统一输出 schema：`questions: [...]` 数组，单题模式下断言长度为 1 | 一套 prompt + 一套 Pydantic 模型覆盖两种模式，减少分叉 |
| D-7 | 允许**部分成功**：单题 3 次重试仍失败 → 进 `result.failed_items`，任务仍 `succeeded` | 20 题里坏 1 题不该让整卷白切；缺口必须显式暴露给人工补录 |
| D-8 | 判重：先 `stem_hash` 命中唯一约束，未命中再比 `embedding` 余弦 ≥ 0.92 | SCHEMA §9 两道闸；哈希便宜先走，向量兜“改数字/换语序”的近似题 |
| D-9 | 一次批量 embedding 同时服务判重与知识点召回 | 20 题一次 `encode()`，比逐题调用省 19 次请求；向量同时用于 cos 判重与候选召回 |
| D-10 | 知识点对齐：向量召回 top-10 后**由 LLM 在候选内选择**（复用 `ai/align/extractor.py::extract_matches` 与 `kp_align_v1.md`，题目借用“试题”标题）；公式分 `0.6*cos + 0.3*keyword + 0.1*prior` 只决定权重与排序，最多挂 3 条；`0.75` 仅保留为 LLM 失败时的确定性兜底阈值 | **原方案“不额外调 LLM、按 0.75 挂”经真机证伪**：题目↔知识点名的余弦上限约 0.55，`0.6*cos` ≤0.33，20 题最高分 0.688，0.75 不可达——首次实测只挂上 1 条。改为候选内选择后 20/20 题挂上、共 32 条。代价：每卷多约 20 次 LLM 调用、耗时增加约 20–40s |
| D-11 | 卷头：有大题标题时丢弃首个标题前的整段，无标题时丢弃首个题号前的整段；页码/答题卡行**全局**剔除 | 避免把解答题里的“某中学”“姓名”误删；页脚可能出现在任意两题之间，不能只看卷尾 |
| D-12 | `verified` 语义扩展：卷面自带答案 → `true`；答案由 LLM 补写 → `false`；无答案 → `false` | 沿用方案 6.5“答案是否可信”的含义，并区分来源 |
| D-13 | 不做题级进度，`async_tasks.result` 只存最终结果 | 20 题实测约 132.5s（含知识点对齐的 LLM 调用），可接受；不为进度改 S2-7 已有表 |
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
    degraded: bool                  # True = 规则切分不可信，改用 block 模式逐块抽取
    warnings: list[str]             # 跳号、块数不符等，进任务日志与 result
```

### 4.2 步骤

1. **拼行**：`ParsedDocument.blocks` 按顺序展开为行，保留 `page_no`。
2. **大题标题识别**（正则）：
   `^\s*([一二三四五六七八九十]+)\s*[、.．]\s*(选择题|多选题|填空题|解答题|判断题|计算题|证明题)`
   命中后记录大题序号、题型提示，并从同段解析声明题数：`共\s*(\d+)\s*小题` 或 `\((\d+)\s*小题`。
3. **首题号定位**：每个大题段内，第一处匹配 `^\s*(\d{1,2})\s*[.．、]\s*\S` 的行（**必须行首**）之前的内容丢弃（引言/说明）。
4. **卷头清理**：有大题标题时，**首个大题标题之前的内容整段丢弃**；无大题标题时，首个题号之前的内容整段丢弃。不做关键词白名单逐行删除——避免把正文里的“某中学”“姓名”误删。
5. **主题号切分**：首题号之后，行首匹配 `^\s*(\d{1,2})\s*[.．、]\s*` 且题号递增视为新题起点；大题声明了题数时切够即停（防解答题内部的列表编号），跳号仍另起题并记 `warnings.append("题号跳号: 3 → 5")`；未声明题数时只认 `current + 1`，非连续题号行归入当前题。
6. **小问不切**：`（1）` `(1)` `1)` `①`–`⑩` 等一律视为题内内容。
7. **页脚/答题卡全局剔除**：命中 `第\s*\d+\s*页|共\s*\d+\s*页|答题卡` 的行在**任意两题之间**都删除，不只看卷尾。
8. **判定兜底**：
   - `expected_count` 有值且 `detected_count != expected_count` → `degraded=True`；
   - 无任何大题标题（`sections <= 1`）且 `detected_count < 3` → `degraded=True`；
   - 注意：`expected_count` 只在**全部大题都声明了题数**时求和，避免部分声明导致偏小误判。
9. `degraded=True` 时**不重新喂整卷**：仍按规则切出的 block 逐个用 `mode="block"` 抽取（同 schema 允许一个 block 返回多条，按 `expected_count` 截断）；若规则一个 block 都没切出，任务直接 failed（「未识别到任何题目」），不做静默整卷重切。

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
- 单题模式（`mode="single"`）下 `len(questions) != 1` → 视为失败并重试；`mode="block"` 在 `expected_count` 有值时超出部分截断并记 warning，`expected_count=None` 时不截断。
- **`max_tokens` 按模式/题数伸缩**：单题固定 `1500`；整卷兜底 `min(8192, max(2048, 400 * expected_count))`（20 题 → 8000）。原固定 2048 时 20 题 JSON 必然被截断成非法 JSON，重试只是重复超限，故按每题约 400 token 估预算并封顶 8192。
- Prompt 的学科名取 `subjects.name`（任务侧查询；查不到回退 `"高中数学"` 并记 WARNING）；`expected_count=None` 时“总数应接近 N 条”整句不渲染，避免把 `None` 写进 Prompt。
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

**`exclude_ids`（拆分/合并专用）**：源题在提交前仍留在库里，拆出的子串/合并后的拼接与原题余弦必然 ≥0.92，不排除会把“自己”判成重复并直接 409。`check_duplicate` 增加 `exclude_ids` 参数，`split_question` 传 `[question_id]`、`merge_questions` 传全部源题 id；其余场景不传，判重语义不变。

### 5.4 知识点对齐（`question_service.align_knowledge_points`）

```text
召回：同 subject 全部知识点（embedding 已由 ensure_kp_embeddings 补齐），按 cos 取 top-10 候选
选择：LLM 在候选内选择（extract_matches(note_title="试题", note_excerpt=题干, candidates=...)，
      复用 ai/prompts/kp_align_v1.md 的候选内选择 prompt）
过滤：只接受候选内 kp_id 且 confidence ≥ 0.5（LLM_MIN_CONFIDENCE）
权重：weight = combine(cos, keyword, prior) = 0.6*cos + 0.3*keyword + 0.1*prior（6 位小数）
      cos     = clamp(1 - cosine_distance, 0, 1)          # 题干向量 vs 节点向量
      keyword = max(keyword_score(kp.name, 题干), keyword_score(kp.name, " ".join(kp_names)))
      prior   = tree_prior(kp.level, kp.ancestor_names, tags=kp_names, title=题干前 200 字)
```

- 每题最多写 3 个知识点（按 `weight` 降序），避免一题挂满全树。
- **`0.75` 不是“是否挂”的门禁**：它只在 LLM 调用失败时作为确定性兜底（`_align_by_score`）的阈值。LLM 失败记 WARNING `question_align_llm_failed` 后走兜底，建题不失败。
- 打分与常量直接复用 `ai/align/scoring.py` 的 `combine / keyword_score / tree_prior / AUTO_THRESHOLD / LLM_MIN_CONFIDENCE`，**不复制常量**。
- 为什么改：题目↔知识点名的余弦上限实测约 0.55，`0.6*cos` ≤0.33，0.75 对题目语料不可达（首次实测 20 题只挂上 1 条）。见 D-10 与 DECISIONS D-044。

## 6. 接口（API.md 新增 §5.5）

### POST /api/v1/questions/import
- 权限：`student` / `teacher` / `admin`
- 类型：异步任务
- 入参：multipart `file`（.pdf/.docx）+ `subject_id`（int，必填）+ `origin`（`upload` 默认；student 只能 `upload`，teacher/admin 可选 `exam/mock/textbook`）
- 出参：**202** `Envelope[TaskOut]`（`id` / `name`=`question.extract` / `status` / `created_at`）
- 笔记：原件落 `files`（`parse_status=done`），不入 `parse.document` 队列
- 错误：`400/40000` 缺 `file` / 类型不支持或非 PDF/DOCX / 非法 `origin`；`403/40300` student 选了非 `upload` 的 origin；`404/40400` subject 不存在；`422/42200` 缺 `subject_id`；`500/50000` 队列不可用（沿用 S2-7，spec 原写 `503/50300`，已按实现回填）

### GET /api/v1/tasks/{task_id}
- 复用 S2-7，**不新增**。`result` 结构（数值为真机验收实测）：
```json
{"file_id": 96, "subject_id": 7, "detected_count": 20, "expected_count": 20,
 "created": 20, "duplicated": 0,
 "failed_items": [{"index": 13, "reason": "题目抽取失败（已重试 2 次）：选择题至少需要 2 个选项"}],
 "degraded": false, "warnings": [], "elapsed_ms": 131948}
```
- `failed_items` 只装单题失败，任务仍 `succeeded`；`index` 为卷面题号（1-based），`reason` 截断到 200 字；整卷无文本/扫描件/全部失败才 `failed`，`error` 写明原因。

### GET /api/v1/questions
- 权限：登录用户（公共题库）
- 类型：同步分页
- 入参：`page` / `page_size` / `subject_id` / `qtype` / `kp_id` / `origin` / `mine`（`true` 只看自己导入的；原写 `created_by=me`，实现为布尔 `mine`）/ `verified` / `keyword`（题干模糊）/ `source_file_id`（按导入试卷筛选）/ `sort_by`（白名单：`created_at` `id` `difficulty`）+ `order`
- 出参：`Envelope[PageData[QuestionSummary]]`（`kp_names: list[str]` 由一页一次 `IN` 批查填充）
- 排序：主排序后追加 `id DESC` 兜底，同 `created_at` 的题翻页不重复/漏行
- 错误：`422/42200` 分页越界或非法排序字段

### GET /api/v1/questions/{question_id}
- 权限：登录用户
- 出参：`Envelope[QuestionDetail]` = `QuestionSummary` + `options_json` / `answer_md` / `analysis_md` / `stem_latex` / `tags` / `kps[]`（`kp_id/kp_name/kp_code/weight`；`weight` 为 JSON number，DB 仍 NUMERIC）。**没有 `kp_ids` 字段**，前端从 `kps[].kp_id` 取
- 错误：`404/40400`

### POST /api/v1/questions
- 权限：`student` / `teacher` / `admin`
- 入参：`{subject_id, stem_md, options?(list), answer_md?, analysis_md?, qtype, difficulty, kp_ids?, origin?}`
- 行为：规范化 → 判重（命中返回 **409/40900**，message 不携带已存在 id）→ 补 embedding → 落库 → 按 `kp_ids` 直写 `question_kps(weight=1.0)`（人工指定不参与打分）；`verified` 固定 `false`（人工录入没有卷面答案来源）
- 题型/选项交叉校验：单选/多选至少 2 个选项且 key 不重复，填空/解答不得带选项，违反 → `422/42200`
- 出参：**201** `Envelope[QuestionDetail]`
- 错误：`409/40900` 判重命中；`422/42200` 字段非法 / 题型与选项不自洽 / 知识点不存在或不属于该学科；`404/40400` subject 不存在

### PATCH /api/v1/questions/{question_id}
- 权限：创建者本人 / teacher / admin（否则 `403/40300`）
- 入参：上述字段的可选子集 + `kp_ids?`（传则整体替换）；`answer_md/analysis_md/tags/options=null` 清空；`qtype/difficulty/origin/verified` 传 `null` → `422/42200`
- 行为：题干**原始串**变化 → 重算 `stem_hash` + 重算 `embedding` + 重新自动对齐知识点（`kp_names=[]`），只改空格/标点也落库；判重撞其他题或 `UPDATE` 撞唯一键（含并发）→ `409/40900`；题型/选项按更新后的有效状态交叉校验（422）；`kp_ids` 传空数组 = 清空
- 出参：`Envelope[QuestionDetail]`

### POST /api/v1/questions/{question_id}/split
- 权限：同 PATCH
- 入参：`{"split_at": "（2）"}`（1–50 字；在题干中**首次出现**该标记处切开，标记保留在第二题开头）
- 行为：按标记切成两题，各自重算 hash/embedding/知识点；判重时 `exclude_ids=[question_id]` 排除原题自身（否则子串会自撞 409）；原题硬删
- 出参：`Envelope[list[QuestionDetail]]`（长度 2，顺序与原题干一致）
- 错误：`422/42200` `split_at` 为空 / 题干中找不到标记 / 标记位于开头 / 任一半去空白后 < 5 字；`409/40900` 拆出的题已存在于题库 / 原题被错题引用

### POST /api/v1/questions/merge
- 权限：同 PATCH（要求对**全部** id 都有权）
- 入参：`{"ids": [a, b]}`（2–10 个；去重后仍须 ≥2）
- 行为：按 id 升序拼接题干（空行分隔），`subject_id/qtype/origin/created_by/source_file_id` 取 id 最小的题，`difficulty` 取其中最大值，`verified=all(true)`，`options_json/tags` 置空，答案与解析按同样顺序拼接（跳过空值）；新题重算 hash/embedding/知识点，判重 `exclude_ids` 排除全部源题；原题硬删
- 出参：`Envelope[QuestionDetail]`
- 错误：`422/42200` 少于 2 个 / 题目不属于同一 subject（原写 `400/40000`，按 `InvalidParamError` 统一 422）；`409/40900` 合并后的题目已存在 / 任一原题被错题引用；`403/40300` 任一题无权

### DELETE /api/v1/questions/{question_id}
- 权限：同 PATCH
- 行为：硬删；`question_kps` 级联删除
- 出参：**204**
- 错误：`403/40300` 无权；`404/40400` 题目不存在；`409/40900` 被 `mistakes.question_id` 引用（`mistakes` 表不存在时跳过该检查，见 D-15）

## 7. 组件契约

### `models/question.py`

按 `SCHEMA.md` §5.1：`id`（BIGINT IDENTITY）、`subject_id`（FK subjects）、`origin`、`source_file_id`（FK files，可空）、`stem_md`、`stem_latex`、`stem_hash`、`options_json`（JSONB）、`answer_md`、`analysis_md`、`qtype`、`difficulty`（SMALLINT）、`tags`（TEXT[]）、`verified`、`embedding`（VECTOR(1024)）、`created_by`（FK users，可空）、`created_at`。

约束：`ck_questions_origin`、`ck_questions_qtype`（值集常量进 `models/enums.py`：`QuestionOrigin` / `QuestionType`）、`ck_questions_difficulty`（1–5）、`uq_questions_subject_stem_hash`、`ix_questions_subject_id`、`ix_questions_origin`、`ix_questions_qtype`、`ix_questions_embedding_hnsw`、GIN(`tags`)。

### `models/question_kp.py`

复合 PK `(question_id, kp_id)`；两列 FK 均 `ON DELETE CASCADE`；`weight NUMERIC(8,6)`（存对齐分，人工指定为 `1.000000`）；`ix_question_kps_kp_id`。

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
- `views/questions/ReviewView.vue`：左列表（按 `source_file_id` 或 `subject_id` 筛选）+ 右卡片编辑；支持新增、合并（左侧勾选 2–10 题）、拆分（填「第二道题开头的文字」标记，按标记首次出现处切分）、知识点多选（`el-select multiple`，选项来自知识点树）、KaTeX 渲染预览（复用 S3-8 的 Markdown + KaTeX 渲染组件）。
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
7. `mode="single"` 返回 2 条 → 触发重试，3 次仍不为 1 才算失败（§5.1 与实现一致；原写“截断并 warning”是笔误）
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

### 9.4 本次实测（2026-11-03，真实 Qwen + 本人自编 20 题卷）

- 首次全量导入（修复后干净跑，任务 id 98）：`succeeded`，`detected_count=20 / expected_count=20 / created=20 / duplicated=0 / failed_items=[] / degraded=false / warnings=[]`，`elapsed_ms=131948`（**132.5s**）。
- 二次导入（幂等）：`created=0 / duplicated=20`，**80.3s**。
- 知识点：**20/20 题挂上**，共 **32 条**链接（1 条×12 题、2 条×4 题、3 条×4 题）。对齐改为 LLM 候选内选择前，首次实测只挂上 1 条（见 D-10）。
- 题型 `单选 8 / 填空 4 / 解答 8`；`difficulty` 1 分×4、2 分×12、3 分×4；`verified` 全 `true`。
- 拆分：`POST /questions/{id}/split {"split_at":"（2）"}` → **200** 返回 2 题，原题随即 `404`，题库题数 +1；左半挂「通项公式与性质」、右半挂「数列求和」（按半题重新对齐）。
- 合并：`POST /questions/merge`（两道单选）→ **200** 返回新题 id 45，原 2 题随即 `404`，合并题挂 3 条知识点（拼接后重新对齐）；只给 1 道题、含不存在/跨学科 id → **422/42200**。
- 其他：删单题 **204** 且 `question_kps` 残留 **0**；删 1 题后重导 `created=1 / duplicated=19`；PATCH 改答案/难度后重新 GET 读到新值；难度非法值（9）`422/42200`；PNG 导入 `400/40000`。
- 测试基线：后端 **865 passed, 1 warning**；前端 **125 passed / 30 files**（均为终审修复后实测）。

## 10. 文档同步

- `SCHEMA.md` §5.1（`stem_hash`、`verified` 语义、判重规则）、§5.2（索引与 weight 语义）——**已完成**。
- `API.md`：新增 `## 5.5 题库与试卷切题（S4-1 定稿）`，8 个新接口 + 复用 `GET /tasks/{task_id}`；§3 `POST /files` 的 `parse` 参数说明补充“试卷原件传 false”。
- `AGENTS.md` §9.2 增补题库规则（不生成笔记、两道闸判重、LLM 候选内挂知识点且 0.75 仅兜底、硬删+引用保护）；§9.6 增补“题库/切题锚点”。
- `DECISIONS.md` 新增 D-044（题库公共化 + `stem_hash` 契约变更 + 部分成功语义 + D-10 重写）。
- `PROGRESS.md` 状态、清单勾选、变更日志、遗留（拍照切题待 S4-2）。
- `docs/AI协作开发实施计划.md` 第 14 章 S4-1 勾选 + 第 7 章 S4-1 实施记录。
- 提交：`docs(s4-1): 题库与试卷切题文档同步（API/进度/决策/规范/实施计划）`。

## 11. 已知限制

- 只认 PDF/DOCX；图片与扫描件明确失败（S4-2 补多模态）。
- 规则预切依赖规范题号；不规范卷子改用 `mode=block` 逐块抽取，兜底漏题率高于逐题模式，`degraded` 标记会暴露但不会自动修复；一个题号都切不出时任务直接失败。
- 知识点对齐是近似的：复合题（如“导数 + 数列”）通常只能挂上 1–2 个最显著的知识点；每卷多约 20 次 LLM 调用，耗时增加约 20–40s。
- `difficulty` 由 LLM 主观判断，实测 20 题集中在 **1–3**（1 分×4、2 分×12、3 分×4），组卷时可选难度区间被压缩。
- `stem_latex` 本次未落库（保留 `NULL`）：题干公式目前只在 `stem_md` 里用 `$...$` 表达。
- LLM 补写的答案不可信（`verified=false`），界面必须标注。
- 判重对“同题换数字”（变式题）不拦，只拦近似重复（cos ≥ 0.92）。
- 试卷原件留在 `files` 表（`parse_status=done`），文件页会与普通附件混排；本卡不区分用途。
- 合并/拆分是硬删原题，操作不可撤销；前端必须二次确认。
- 题库公共：任何登录用户可见全部题目，仅写权限受限；多用户环境下存在“学生导入低质量题”的风险，本卡不建审核流。
- 任务耗时随题量线性增长（20 题实测 132.5s，约 6.6s/题，含知识点对齐的 LLM 调用），无题级进度；中断后重跑整卷（已入库题会被跳过）。

## 12. 与 spec 的偏差（2026-11-03 按实现回填）

> 本节记录本文早期版本与已落地实现的差异，正文对应小节已按“实际实现”改过；事实以代码与真机为准。

| # | 原 spec 写法 | 实际实现 | 原因 |
|---|---|---|---|
| a | 列表入参 `created_by=me` | `mine: bool`（前端传 `mine=true`） | 布尔过滤比字符串 `me` 更直接，和分页参数风格一致 |
| b | 详情出参含 `kp_ids` | 只有 `kps[{kp_id,kp_name,kp_code,weight}]` | 关联表已有 `weight`，前端从 `kps[].kp_id` 取，避免冗余字段 |
| c | 队列不可用 `503/50300` | `500/50000`（沿用 S2-7） | 不改 S0-5 异常体系；同类入队失败已是 50000 |
| d | split/merge 参数错误 `400/40000` | `422/42200`（`InvalidParamError`） | 仓库既有参数错误统一 422；跨学科/切点非法都属于参数校验 |
| e | D-10：不额外调 LLM，按 0.75 挂 | 向量 top-10 候选内由 LLM 选择；0.75 只作 LLM 失败兜底 | 题目↔知识点名余弦上限 ~0.55，`0.6*cos` ≤0.33，0.75 不可达（首次实测仅 1 条）；代价每卷 +约 20 次 LLM、+20–40s |
| f | SCHEMA §5.1 无 `created_at` | 迁移 `0009_s4_1` 新增 `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` | 列表默认按创建时间倒序，必须有该列 |
| g | §4.2 卷头关键词白名单、卷尾清理 | 首个大题标题前整段丢弃；页码/答题卡行全局剔除 | 白名单会误删正文里的“某中学”；全局剔除更稳 |
| h | §8 单题模式多返回 → 截断并 warning | 触发重试，3 次仍不为 1 才失败 | 与 §5.1 一致；静默截断会丢题 |
| i | merge 取第一题的 difficulty | 取全部源题 `difficulty` 的最大值 | 合并后的题不应比任一源题更容易 |
| j | 判重不排除源题自身 | split 传 `exclude_ids=[question_id]`、merge 传全部 `unique_ids` | 源题提交前仍在库，子串/拼接余弦 ≥0.92 会自撞 409（真机发现并修复） |
| k | 前端拆分“在 textarea 光标位置切” | 填切分标记，后端按标记首次出现处切 | 契约是 `split_at` 字符串；前端算光标偏移易错 |
| l | §4.2 步骤 9 / D-5：degraded 时把整卷文本交给 block 模式 | 仍按规则切出的 block 逐个走 block 模式；一个 block 都切不出直接 failed | 复用已切出的块，避免整卷再喂一遍；没有可靠边界时失败比静默重切更诚实 |