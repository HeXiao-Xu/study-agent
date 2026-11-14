# S5-2 组卷 API + 预览页 设计

> 任务卡：`docs/AI协作开发实施计划.md` §14 S5-2（产出：papers 表、`api/v1/papers.py`、`views/papers/Generate.vue`）
> 上游：S5-1 组卷内核（`docs/spec/s5-1-paper-planning.md`，commit `5c4942d`）
> 契约依据：`docs/SCHEMA.md` §6.1（papers）、`docs/API.md` §8（组卷与作答）
> 确认记录：本 spec 的 8 项设计取舍已经用户逐项确认（2026-11-13，见 §11）

## 1. 背景与目标

S5-1 已交付**纯函数**组卷内核（配额 → 打分 → 贪心 → 校验），不碰库、不开接口。本卡把它接到 HTTP 与页面，落 `papers` 表，打通最小闭环：

> 选知识点 → 生成试卷 → 预览并换题/删题/调序 → 保存草稿 → 按 id 读回。

任务卡验收原文：**选 5 个知识点生成 20 题卷子，预览可手动换掉 3 道题**。

真实题库现状（S5-1 验收实测，`.sdd/s5-1/acceptance-evidence.md`）：56 道题只有 25 道挂了知识点，排除 14 天内做过后只剩 **19 道可用**，5 个知识点范围内更少。因此本卡验收**诚实地分两条路径**：

1. **shortage 路径**：5 个知识点 + 20 题 → 接口 200 返回 `ok=false` 与具体缺口，页面显示「题库不足，已出 N 题」；
2. **可行路径**：真实库能出的题量（10 题级）→ 换 3 道 → 保存 → 读回。

不为了让演示好看去造题、改数据或伪造结果。

## 2. 非目标

- 不建 `answers` / `review_items`（S5-4 / S5-5），不做在线作答与掌握度回写。
- 不做 PDF 导出（S5-3）、不做草稿列表/删除/改名（S5-7）。
- 不做异步任务：组卷是纯函数 + 两次批量查询，毫秒级，同步返回即可（API.md 里「异步 ⚠ TODO」就此定死为同步）。
- 不做「AI 补题」：题不够就报缺口（AI 变式题走 S4-4 独立入口）。
- 不加依赖、不加环境变量、不改已提交迁移。

## 3. 范围（文件清单）

**后端新增**

| 文件 | 职责 |
|---|---|
| `backend/alembic/versions/0014_s5_2.py` | 建 `papers` 表（`down_revision = "0013_s4_7"`） |
| `backend/app/models/paper.py` | `Paper` ORM（严格对齐 SCHEMA §6.1） |
| `backend/app/schemas/paper.py` | 4 个接口的入参/出参 Pydantic 模型 |
| `backend/app/services/paper_plan_service.py` | DB 层：取候选、生成预览、换题、保存、读取（调用 S5-1 纯函数） |
| `backend/app/api/v1/papers.py` | 4 个路由，只做参数校验 → service → `Envelope` |
| `backend/tests/test_paper_plan_service.py` | 服务层单测（FakeSession） |
| `backend/tests/test_papers_api.py` | 接口单测（TestClient + 依赖覆盖） |

**后端修改**：`app/models/enums.py`（两个新枚举）、`app/models/__init__.py`（注册 `Paper`）、`app/api/router.py`（`include_router(papers.router)`）、`docs/API.md` §8、`docs/SCHEMA.md` §6.1。

**前端新增**

| 文件 | 职责 |
|---|---|
| `web/src/types/papers.ts` | 与后端出参一一对应的 TS 类型 |
| `web/src/api/papers.ts` | 4 个接口的封装（只经 `http.ts`） |
| `web/src/views/papers/Generate.vue` | 约束表单 + 预览表 + 保存 |
| `web/src/views/papers/Generate.spec.ts` | 页面交互单测 |
| `web/src/api/papers.spec.ts` | API 封装单测 |

**前端修改**：`router/index.ts`（`/papers/generate`，`roles: ['student']`，`nav: 'papers'`）、`layouts/nav.ts`（「组卷」）、`layouts/MainLayout.spec.ts`（导航 9→10 项）。

## 4. 数据契约

### 4.1 `papers` 表（迁移 `0014_s5_2`）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | BIGINT | 否 | Identity(always) | PK |
| user_id | BIGINT | 否 | — | FK `users.id` ON DELETE CASCADE，`ix_papers_user_id` |
| title | TEXT | 否 | — | 1–100 字符 |
| constraint_json | JSONB | 否 | — | 归一化后的约束（结构见 §5.1） |
| question_ids | BIGINT[] | 否 | — | **有序**题目列表，保存顺序即卷面顺序 |
| total_score | INTEGER | 否 | — | 服务端按 `question_ids` 重算，不信任前端 |
| duration_min | INTEGER | 是 | — | 1–1440 |
| status | TEXT | 否 | `'草稿'` | CHECK ∈ 草稿/已生成/已提交 |
| generated_by | TEXT | 否 | `'manual'` | CHECK ∈ manual/ai_agent |
| created_at | TIMESTAMPTZ | 否 | `now()` | |

**与 SCHEMA §6.1 的两点落地说明**（写入 SCHEMA §6.1 备注，不改口径）：

1. `total_score` 用 **INTEGER** 而不是 NUMERIC：S5-1 的题分是整数（3/4/4/8），Python 侧求和即整数，用 NUMERIC 只会引入 `Decimal` 转换噪音；与 AGENTS §9.2「分数用整数存储，不用 float」一致。
2. 索引名 `ix_papers_user_id`（SCHEMA 只标 ⚠「需要索引」，不指定名字）；不额外建 `(user_id, created_at)` 复合索引，草稿列表接口（S5-7）到时按需加。

### 4.2 枚举（`app/models/enums.py`）

```python
class PaperStatus(StrEnum):
    DRAFT = "草稿"
    GENERATED = "已生成"
    SUBMITTED = "已提交"

class PaperGeneratedBy(StrEnum):
    MANUAL = "manual"
    AI_AGENT = "ai_agent"

PAPER_STATUSES = tuple(item.value for item in PaperStatus)
PAPER_GENERATED_BY = tuple(item.value for item in PaperGeneratedBy)
```

CHECK 约束名 `ck_papers_status` / `ck_papers_generated_by`，文本由 `in_check()` 生成（D-021）；默认值用 `server_default=text("'草稿'")`。本卡只写 `草稿` 与 `manual`，另外两个值留给 S5-3/S5-4 的状态推进。

## 5. API 契约（同步写入 `docs/API.md` §8）

### 5.1 `POST /api/v1/papers/generate`

权限：`require_role("student")`；同步 200。**不写库**。

入参 `PaperGenerateIn`：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| kp_ids | int[] | 是 | 1–500 个，去重 | 覆盖的知识点 |
| total_questions | int | 是 | 1–100 | 期望题量 |
| qtype_ratio | object | 是 | 键 ∈ 单选/多选/填空/解答，值 ≥0，至少一个 >0 | 题型配比，服务端归一化 |
| difficulty_dist | object | 是 | 键 ∈ 1–5，值 ≥0，至少一个 >0 | 难度分布，服务端归一化 |
| total_score | int | 是 | 1–300 | 目标总分 |
| duration_min | int? | 否 | 1–1440 | 只回显与保存，不参与算法 |
| exclude_recent_days | int | 否 | 0–365，默认 14 | 「近期做过」的硬排除窗 |
| seed | int? | 否 | 0–2^31−1 | 不传则服务端随机，**回显**；前端「重新生成」换新 seed |
| kp_weights | object? | 否 | 键 ⊆ kp_ids，值 >0 | kp 权重，默认全 1.0 |

归一化：`qtype_ratio` / `difficulty_dist` 除以各自和；`kp_ids` 保序去重；`kp_weights` 补全为全量映射后存回显。分值表**不开放**给前端（恒为 `{"单选":3,"多选":4,"填空":4,"解答":8}`）。

出参 `PaperPreviewOut`：

| 字段 | 类型 | 说明 |
|---|---|---|
| constraint | object | 归一化后的入参回显（含 `qtype_ratio`/`difficulty_dist`/`kp_weights`/`score_by_qtype`） |
| seed | int | 本次使用的种子 |
| ok | bool | `violations` 为空即 true |
| items | PaperItemOut[] | 有序试卷项，见下 |
| total_score | int | 实选题目分值合计（可能 < 目标，若 shortage） |
| target_score | int | 入参目标总分 |
| quota_by_qtype / quota_by_difficulty / quota_by_kp | object | 原始配额（借位前，用于解释缺口） |
| counts_by_qtype / counts_by_difficulty / counts_by_kp | object | 实际选中计数 |
| violations | object[] | `{code, message, detail}`，code ∈ QTYPE_SHORTAGE / DIFFICULTY_SHORTAGE / KP_SHORTAGE / TOTAL_SCORE_OUT_OF_TOLERANCE / NO_CANDIDATES |
| warnings | string[] | 如「题型「单选」按配比取整为 0 题」 |

`PaperItemOut`：`question_id`、`qtype`、`difficulty`、`score`、`kp_ids`、`parts`（`difficulty_match`/`mastery_match`/`novelty`/`quality`/`total`）、`subject_id`、`stem_md`、`options`（`[{key,text}]`，无选项为 `[]`）、`answer_md`、`analysis_md`、`verified`、`origin`。

「题干与答案分离」的落法：同一响应里题干/答案字段分开给，页面**默认折叠答案**，可一键展开核对；S5-3 的 PDF 默认只排题干。

### 5.2 `POST /api/v1/papers/replace-item`

权限 student；同步 200；**无状态、不写库**。

入参 `PaperReplaceIn`：`constraint`（同 §5.1 的字段，平铺）+ `selected_question_ids: int[]`（当前卷面全部题，0–100）+ `replace_question_id: int`。

规则（确定性，无随机；`constraint.seed` 在此接口不参与打分，只为与 generate 入参同构）：

1. 用 `constraint` 重建候选池（`prepare_pool`，含近期排除）；
2. 剔除 `selected_question_ids` 与 `replace_question_id`；
3. 第一优先：与**原题同题型 + 同难度**，按 S5-1 `score_parts.total` 降序、`question_id` 升序取第一；
4. 第二优先：与**原题同题型**、任意难度，同法取第一；
5. 都没有 → `{replaced: false, item: null, reason: "没有可替换的候选题"}`（200，不 409）。

出参 `PaperReplaceOut`：`replaced: bool`、`item: PaperItemOut | null`、`reason: string | null`。

### 5.3 `POST /api/v1/papers`

权限 student；201；保存草稿。

入参 `PaperSaveIn`：`title`（1–100）、`constraint`（同 §5.1，校验后原样存 `constraint_json`）、`question_ids`（1–100，**去重**，顺序即卷面）、`duration_min?`。

服务端校验与改写：

- 所有 `question_id` 必须存在，缺失 → `422/42200`（消息带缺失 id，最多 10 个）；
- 重复 id → `422/42200`；
- `total_score = Σ DEFAULT_SCORE_BY_QTYPE[question.qtype]`（不读前端）；
- `status='草稿'`、`generated_by='manual'`、`user_id=当前用户`；
- 一次事务提交。

出参 `PaperOut`：`id`、`title`、`status`、`total_score`、`duration_min`、`question_ids`、`created_at`。

### 5.4 `GET /api/v1/papers/{id}`

权限 student；本人数据。不存在 → `404/40400`；别人的 → `403/40300`（不泄露存在性，沿用 S2-3）。

出参 `PaperDetailOut`：`PaperOut` 全部字段 + `constraint_json` + `items: PaperItemOut[]`（按保存顺序）+ `missing_question_ids: int[]`（题目被硬删后跳过的 id，不 500、不伪造）。

### 5.5 错误码汇总

| 场景 | HTTP / code |
|---|---|
| 未登录 | 401 / 40100 |
| 非 student | 403 / 40300 |
| 约束非法（`PaperPlanError` / Pydantic） | 422 / 42200 |
| 保存时题目不存在 / 重复 | 422 / 42200 |
| 试卷不存在 | 404 / 40400 |
| 读别人的试卷 | 403 / 40300 |

## 6. 服务层设计（`paper_plan_service.py`）

只做「取数据 + 调 S5-1 + 落库」，算法一律复用 `paper_service`，禁止复制实现。

```
load_candidates(session, *, kp_ids, user_id, exclude_recent_days, now)
    ① select Question.id/qtype/difficulty/verified/origin, QuestionKp.kp_id/weight
       join question_kps，where kp_id in (:kp_ids)          —— 一次查询
    ② select Mistake.question_id, last_review_at, created_at
       where user_id = :user_id and question_id in (:候选 id) —— 一次查询
       在 Python 里取 max(last_review_at, created_at) 作为 last_done_at
    ③ mastery_service.mastery_values(session, user_id, kp_ids) —— 一次批量（S4-7 既有）
    → (candidates, mastery_by_kp)

build_constraints(in) -> PaperConstraints（seed 缺省随机并回显）

generate_preview(session, *, user_id, in, now) -> PreviewPlan
    load_candidates → paper_service.plan_paper → 按 items 的 id 一次 IN 查题干/选项/答案/解析
    → 组装 PaperPreviewOut

replace_item(session, *, user_id, in, now) -> PaperReplaceOut
    同 load_candidates → prepare_pool → 剔除 → 同题型同难度 → 同题型 → 组装

save_draft(session, *, user_id, in) -> Paper
    校验题目存在/去重 → 重算总分 → 插行 → commit → refresh

get_paper(session, *, user_id, paper_id) -> PaperDetailOut
    session.get(Paper) → 归属校验 → 按 question_ids 一次 IN 查题 → 跳过缺失
```

时间统一 UTC；`now` 由路由层传 `datetime.now(timezone.utc)`（便于单测注入）。

## 7. 前端设计（`views/papers/Generate.vue`）

**路由与导航**：`/papers/generate`，`name: 'paper-generate'`，`meta: { title: '组卷', nav: 'papers', roles: ['student'] }`；`NAV_ITEMS` 在「题库」之后插入「组卷」。`MainLayout.spec.ts` 的导航数从 9 改 10，并断言新项文本与 `to`。

**页面结构（单页两段，不跳转）**

1. 顶栏 `PageHeader`「组卷」+ 副标题「按掌握度与题库覆盖自动配卷」。
2. 约束表单（`el-form`）：
   - 学科下拉（复用 `listSubjects`，默认第一个）→ 知识点**多选树**（`getKpTree`，`el-tree` + `show-checkbox`，父子联动；选中非叶子时取其自身与子节点 id）；
   - 题量（数字，默认 10）、总分（默认 60）、时长（默认 60，可清空）；
   - 题型配比：四个 `el-input-number`（单选/填空/解答默认 0.4/0.2/0.4，多选默认 0）；多选保持 0 时页面不提示，若用户填 >0 而题库没有多选题，由后端 `QTYPE_SHORTAGE` 的原话在预览区提示（前端不自定义文案）；
   - 难度分布：d1–d5 五个 `el-slider`（0–100），默认 d2=50、d3=50、其余 0；
   - 高级项（`el-collapse`）：「排除近 N 天做过的题」默认 14。
   - 校验：kp ≥1、题量 1–100、总分 1–300、题型/难度各自至少一个 >0；不通过不发请求。
3. 「生成试卷」按钮 → loading → `POST /papers/generate`。
4. 预览区（生成后出现）：
   - 头部：`ok` 徽标、`total_score/目标`、实选题量、`seed`（只读，便于复现）；`violations` 用 `el-alert` 逐条列出（可折叠），`warnings` 一行灰字；
   - 全局「显示答案」开关（默认关）；
   - 结果表（`el-table`）：序号、题型、难度、知识点（id 列表，悬停 title）、分值、打分分项（难度/掌握/新颖/质量/合计，保留 4 位）、题干摘要（前 60 字）、操作列「换一题 / 删除 / 上移 / 下移」；
   - 换题：`POST /papers/replace-item`（带当前卷面全部 id + 该题 id），成功则原位替换并重算表内总分；`replaced=false` 时 `ElMessage.warning` 原话；
   - 删除：直接删除该行；上移/下移：首尾禁用；
   - 「重新生成」：清空预览、换新 seed 再请求；
   - 「保存为草稿」：0 题禁用；弹 `ElMessageBox.prompt` 填标题（默认 `2026-11-13 组卷（N 题）`，可改）→ `POST /papers` → 成功提示「已保存试卷 #id」并展示 `status`；保存后再点生成/换题视为新卷，可再次保存。
5. 空态：未生成时预览区不渲染或显示引导文案；接口错误由 `http.ts` 统一弹错，组件只处理字段级校验与业务提示。

**状态**：`form`（reactive）、`preview: PaperPreview | null`、`generating/saving/replacingId`、`showAnswer`；不引 Pinia（单页局部状态，刷新丢失是有意为之——保存后才有持久化）。

## 8. 测试设计

**后端（新增约 30 条）**

- `test_paper_plan_service.py`（FakeSession 喂 `execute` 结果，按查询顺序断言）：
  - `load_candidates` 组装多 kp 题目、缺失 mastery 不出现在字典、近期题交给 `prepare_pool` 排除；
  - `generate_preview` 调 `plan_paper` 后补齐题干/选项、`ok=false` 时 violations 透出；
  - `replace_item` 三条优先级各 1 条 + `replaced=false`；
  - `save_draft` 重算总分（不信任前端）、重复 id 报 422、缺失 id 报 422（列出 id）、`status='草稿'`/`generated_by='manual'`；
  - `get_paper` 404 / 403 / `missing_question_ids` 容错；
  - `build_constraints` 归一化与 seed 回显（seed 缺省时落在 0–2^31−1）。
- `test_papers_api.py`（TestClient + `dependency_overrides`）：401 无 token、403 teacher、422 非法约束、200 生成含 `items[0].stem_md`、200 换题 `replaced=true/false`、201 保存、200 读回、403 读他人、404 不存在。
- `test_papers_migration.py`：`alembic heads == 0014_s5_2`；`papers` 列名/类型/CHECK 名与 SCHEMA 一致；`down_revision == 0013_s4_7`。

**前端（新增约 12 条 + 1 条改）**

- `api/papers.spec.ts`：4 个封装走对应方法与路径（mock `http`）。
- `Generate.spec.ts`：表单默认值；kp 未选不发请求；生成成功渲染行数与总分；shortage 显示 `ok=false` 与 violations；换题替换目标行；删除后总分重算；上移/下移边界禁用；保存时传 title 与当前 `question_ids`；0 题保存禁用；答案开关默认隐藏。
- `MainLayout.spec.ts`：9 → 10 项，断言「组卷」链接。

## 9. 验收步骤（真机）

环境：`docker compose -f deploy/docker-compose.dev.yml up -d` + `scripts/check_services.py` 3/3；`uvicorn app.main:app --port 8032`；`npm run dev`。

1. **shortage 路径（任务卡原句）**：5 个知识点 + 20 题 → `200`、`ok=false`、`items` 少于 20、`violations` 含题型/难度/知识点缺口；页面显示「题库不足」与缺口原话。
2. **可行路径**：真实库能出的题量（10 题级，全知识点/选中足够 kp）→ `ok=true` → 连续换 3 道，每次 `replaced=true` 且卷面不重复 → 保存 → `GET /papers/{id}` 顺序与内容一致。
3. **权限**：无 token 401；teacher 403；他人试卷 403；不存在的 id 404；非法约束（空 kp、总分 0、未知题型）422。
4. **浏览器**：Chrome headless（CDP，沿用 S4-8 方式，不加依赖）打开 `/papers/generate`，真实点击生成、换 3 道、保存，截图 + 断言表行数与总分文本；若环境不允许则如实标注「浏览器级未做，仅有组件单测」。
5. 证据落 `.sdd/s5-2/acceptance-evidence.md`：命令、原始输出、截图、发现的问题、未覆盖项。**禁止伪造数字**。

## 10. 风险与取舍

1. **真实题库不足**：20 题卷在真实库必然 shortage（S5-1 已实测）。取舍：不降题量、不造假题，接口如实返回 `ok=false` + violations，页面如实展示——这本身是「约束满足」特性的演示点。
2. **换题可能换不动**：候选池小时同题型同难度无备选，降级到同题型任意难度；再没有就 `replaced=false`。不自动放宽题型（会把卷面配比换歪）。
3. **草稿与题库漂移**：题目硬删后，`GET /papers/{id}` 会缺题；本卡返回 `missing_question_ids` 如实告知，不 500、不用错题顶替。草稿的编辑/修复留给 S5-7。
4. **保存不重算配额**：`constraint_json` 原样存用户提交的约束（含 seed），不校验「这份卷子是否仍满足约束」——换题本来就是人工干预，记录约束即可。
5. **组卷只看本人掌握度**：mastery 按当前用户查；题库是公共语料（S4-1 口径），越权风险为 0（只读公共题库 + 只写本人 papers）。
6. **前端纯组件测试**：不引 Playwright（§2.1），浏览器级验证用既有 CDP 脚本方案；测不到真实滚动/长列表性能，如实记录。

## 11. 决策记录（2026-11-13 用户逐项确认）

| # | 决策 | 选择 |
|---|---|---|
| 1 | 生成方式 | 同步 200，不做异步任务 |
| 2 | 落库时机 | 生成不落库；「保存为草稿」才写 `papers` |
| 3 | 换题机制 | 无状态 `POST /papers/replace-item`，后端实时挑下一名 |
| 4 | 题库不足 | 200 + `ok=false` + violations + 部分卷；0 题不允许保存 |
| 5 | 页面结构 | 单页「表单 + 预览」，不跳转、不做草稿列表 |
| 6 | 表单形态 | 题型配比四个数 + 难度五档滑块；默认 10 题/60 分/时长 60 |
| 7 | 表口径 | 严格按 SCHEMA §6.1，不扩展列；`total_score` 落 INTEGER |
| 8 | 接口清单 | 4 个：generate / replace-item / POST papers / GET papers/{id} |

## 12. 文档同步

- `docs/API.md` §8：三个新接口 + generate 契约替换 TODO + 同步/200 口径；
- `docs/SCHEMA.md` §6.1：`total_score` INTEGER 说明、迁移 `0014_s5_2`、索引名；
- `docs/DECISIONS.md`：D-059（组卷接口与落库口径）；
- `docs/PROGRESS.md`：S5-2 勾选、当前状态、验收记录、变更日志；待解决问题（题库不足、换题降级、草稿漂移）；
- `AGENTS.md` §9.6：组卷 API 锚点；
- `docs/AI协作开发实施计划.md`：S5-2 勾选。