# S3-4 上下文组装 + Prompt 版本管理 Spec

> 任务卡：`docs/AI协作开发实施计划.md` S3-4。产出：`prompt_templates` 表、`services/prompt_service.py`、管理接口。
> 状态：设计已确认，待实现。

## 1. 目标

- 把问答 Prompt 从 `ai/prompts/qa_v1.md` 迁到 `prompt_templates` 表，按 `name + version` 管理不可变版本。
- 管理员可新建版本、启用版本、查历史；启用后下一次问答立即使用新内容，无需重启。
- 模板渲染继续用 Jinja2 `StrictUndefined`：缺变量必须报错，不能静默渲染成空。
- 改动留痕：`created_by`、`created_at`、`updated_at`（启用时刷新）。
- 上下文组装沿用 S1-6 `build_context`（预算/排序/引用不变），本卡只换 Prompt 来源。

## 2. 已确认决策

1. **初始化**：迁移内联种子 `qa/v1`（内容取自当前 `qa_v1.md`，末尾多一个换行，渲染无影响；`variables_json=["context","question"]`，`is_active=true`，`created_by=NULL`）；生产链路只读库，库无 active 抛错；`answer_question` 保留可选 `prompt_template`，缺省读文件仅用于单测/兼容。
2. **版本模型**：版本行不可变；`POST` 新建，`PUT /{id}/activate` 显式启用；仅 admin。
3. **留痕**：补 `created_at`、`updated_at`；部分唯一索引保证每个 name 最多一条 `is_active=true`。
4. **生效链路**：`answer_question(..., prompt_template: str | None)`；`prompt_service.get_active_prompt()` 读库；`scripts/ask.py` 取库内容传入；S3-5 再接 API/SSE。
5. **范围**：本轮只迁 QA Prompt；`rewrite_v1`、`kp_align_v1` 继续读文件；不改检索/改写/前端。

## 3. 架构与数据流

```
admin API ──> services/prompt_service.py ──> prompt_templates
                                             │
scripts/ask.py ── get_active_prompt("qa") ───┘
      │
      └─ answer_question(..., prompt_template=content)
             │
             ├─ retrieve_hybrid_reranked + build_context   （S1-4/S1-6，不改）
             ├─ render_prompt_text(content, context, question) （Jinja2 StrictUndefined）
             └─ LLM 调用 + 引用校验                        （S1-6，不改）
```

- 生产只读库；`qa_v1.md` 保留为单测/兼容缺省，不再作为脚本实际来源。
- 每次问答查一次 active 行（单行索引查询），不缓存，保证启用即时生效。
- `render_prompt_text` 是唯一 Jinja2 文本入口；文件版 `render_prompt` 复用它，禁止再写 `{{var}}` 替换。

## 4. 数据模型（SCHEMA §8.3）

`prompt_templates`：

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | PK |
| name | TEXT | 否 | — | 如 `qa` |
| version | TEXT | 否 | — | 如 `v1`、`v2` |
| content | TEXT | 否 | — | Jinja2 模板正文 |
| variables_json | JSONB | 是 | — | 变量名数组，如 `["context","question"]` |
| model_hint | TEXT | 是 | — | 适用模型提示 |
| is_active | BOOLEAN | 否 | false | 当前启用版本 |
| created_by | BIGINT | 是 | — | FK `users.id`；系统种子为 NULL |
| created_at | TIMESTAMPTZ | 否 | now() | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | now() | 启用时刷新 |

约束/索引：

- `UNIQUE(name, version)` → `uq_prompt_templates_name_version`。
- 部分唯一索引 `uq_prompt_templates_active_name ON prompt_templates(name) WHERE is_active`（PG）。
- `ix_prompt_templates_name_created_at(name, created_at)` 供历史查询。

ORM：`backend/app/models/prompt_template.py`，并在 `models/__init__.py` 显式导入。

## 5. AI 层与上下文组装

`ai/rag/prompt_builder.py`：

```python
def render_prompt_text(
    template_text: str,
    *,
    context: str,
    question: str,
) -> str:
    ...
```

- 使用 `Environment(undefined=StrictUndefined, autoescape=False)`；`TemplateError/UndefinedError` 统一包 `PromptTemplateError`，消息不携带上下文正文。
- 原 `render_prompt(context, question, *, template_path=None)` 保留签名：先校验文件存在，再读文本调用 `render_prompt_text`；现有单测不变。
- `build_context` 不改：token 预算、rerank 排序、去重、截断、引用编号全部沿用 S1-6。

`ai/rag/answerer.py`：

```python
def answer_question(
    session,
    question,
    *,
    user_id: int,
    top_k: int = 20,
    threshold: float | None = None,
    embedding_client=None,
    rerank_client=None,
    llm_client=None,
    prompt_template: str | None = None,
) -> AnswerResult:
```

- `prompt_template is None` → 现有 `render_prompt(built.text, question)` 行为不变。
- 非 None → `render_prompt_text(prompt_template, context=built.text, question=question)`。
- 不改 `AnswerResult` 字段、拒答/引用/重试逻辑。

## 6. 服务层 `services/prompt_service.py`

常量：`QA_PROMPT_NAME="qa"`、name/version 正则、`MAX_CONTENT_CHARS=20000`。

```python
def get_active_prompt(session, *, name: str = QA_PROMPT_NAME) -> PromptTemplate
def list_prompts(session, *, name: str | None = None) -> list[PromptTemplate]
def create_prompt_version(
    session, *, name: str, content: str, version: str | None = None,
    variables_json: list[str] | None = None, model_hint: str | None = None,
    created_by: int | None = None, activate: bool = False,
) -> PromptTemplate
def activate_prompt(session, prompt_id: int) -> PromptTemplate
```

行为：

- `get_active_prompt`：`name + is_active` 单行查询；无 active 抛 `PromptTemplateError("Prompt 未启用：<name>")`（不返回文件兜底）。
- `list_prompts`：name 可选；`created_at DESC, id DESC`。
- `create_prompt_version`：
  - 服务层再校验 name/version/content/variables（防脚本绕过 Pydantic）；非法抛 `InvalidParamError`。
  - `version=None` → 查同 name 版本，取 `v(\d+)` 最大 +1（无数字从 1 起），冲突则递增。
  - 显式重复 → `ConflictError("Prompt 版本已存在")`。
  - `activate=True` 时同事务把同 name 旧版 `is_active=False`，新版 true；False 时不改动当前 active。
  - `commit` + `refresh` 后返回 ORM。
- `activate_prompt`：不存在 → `NotFoundError("Prompt 版本不存在")`；查出同 name 全部行，目标 true、其余 false，刷新 `updated_at`，单事务提交。
- 并发：依赖 `uq_prompt_templates_active_name`；激活冲突由 DB 唯一约束兜底（本卡不加重试，单管理员场景）。

## 7. 管理接口（仅 admin，API.md §11）

### GET `/api/v1/admin/prompts?name=qa`

- 权限：admin（其他 403/40300；匿名 401/40100）。
- `name` 可选，需匹配 `^[a-z][a-z0-9_]{0,63}$`，非法 422/42200。
- 出参：`Envelope[list[PromptTemplateOut]]`，按 `created_at DESC, id DESC`；含 content。

### POST `/api/v1/admin/prompts`（201）

入参 `PromptCreate`：

```json
{
  "name": "qa",
  "content": "...Jinja2...",
  "version": "v2",
  "variables_json": ["context", "question"],
  "model_hint": null,
  "activate": true
}
```

- `name` 必填 + 正则；`content` 1–20000 字（strip 后非空）；`version` 可选 + 正则；`variables_json` 字符串数组（元素非空）；`model_hint` ≤100；`activate` 默认 false。
- 出参：`Envelope[PromptTemplateOut]`；`created_by` 取当前 admin。
- 错误：409/40900 版本重复；422/42200 校验失败；403/401 同上。

### PUT `/api/v1/admin/prompts/{id}/activate`

- 路径 `id` 正整数；不存在 404/40400「Prompt 版本不存在」。
- 行为：同 name 全部停用后启用目标，刷新 `updated_at`；返回 200 `Envelope[PromptTemplateOut]`。

`PromptTemplateOut` 字段：`id/name/version/content/variables_json/model_hint/is_active/created_by/created_at/updated_at`。

## 8. 迁移与种子

- 新迁移 `backend/alembic/versions/0006_s3_4_prompt_templates.py`，`revision="0006_s3_4"`，`down_revision="0005_s2_8"`。
- `upgrade()`：建表 + 唯一约束 + 部分唯一索引 + 普通索引 + FK；内联插入 `qa/v1`（内容取自 `qa_v1.md`，末尾多一个换行；`variables_json` 用 `json.dumps`/`sa.text` 绑定，`is_active=true`）。
- `downgrade()`：按依赖顺序 drop index/table。
- 不修改历史迁移；种子只插一次，重复迁移不会重复。

## 9. 测试

| 文件 | 条数 | 覆盖 |
|---|---|---|
| `tests/test_prompt_model.py`（新） | 2 | 表字段/可空；`uq_prompt_templates_active_name` 与普通索引存在 |
| `tests/test_prompt_builder.py`（改） | +2 | `render_prompt_text` 正常渲染；缺变量抛 `PromptTemplateError` |
| `tests/test_answerer.py`（改） | +2 | 自定义模板生效且含 marker；自定义模板缺变量抛错 |
| `tests/test_prompt_service.py`（新） | 12 | 自动版本 v2；显式版本；重复 409；非法 name/content；`activate=true` 停旧启新；激活未知 404；激活互斥；列表过滤/排序；active 读取；无 active 抛错；created_by 传递 |
| `tests/test_prompt_admin_api.py`（新） | 8 | list 200；teacher 403；匿名 401；create 201；重复 409；非法 body 422；activate 200；未知 id 404 |
| 既有 | 610 保持全绿 | 全量预计 **636 passed, 1 warning** |

外部 LLM 全部 fake；服务测试用 FakeSession（不连 DB）。

## 10. 验收

1. `alembic upgrade head`；SQL 确认 `qa/v1` 存在且 `is_active=true`、`variables_json` 正确。
2. 基线：`scripts/ask.py --user-id 18 "错位相减法怎么用"`（当前 active v1）。
3. 管理接口：TestClient + 真实 DB，临时 admin 登录 → `POST /admin/prompts` 创建 `qa/v2`（内容在 v1 末尾加“回答末尾必须写【PROMPT-V2】”），`activate=true`；`GET` 能看到 v1/v2；`PUT /{v1_id}/activate` 能切回。
4. 立即生效：启用 v2 后运行同一 `ask.py` 问题，回答末尾出现【PROMPT-V2】；切回 v1 后同一问题标记消失。
5. 历史：`GET /admin/prompts?name=qa` 返回 v2/v1（按时间倒序），v1 为 active。
6. 清理：删除临时 admin（先把其 `created_by` 置 NULL）；v2 保留为 inactive 历史。
7. 全量 `pytest -q` 636 绿；`scripts/ask.py` 不再读 `qa_v1.md`（可用改文件内容不影响答案来证明）。

## 11. 已知限制

1. 本轮只有 QA Prompt 走库；rewrite/kp_align 仍读文件，风格暂时不统一。
2. 每次问答多一次 DB 查询；量小可接受，S3-7 可加短 TTL 缓存（需带版本失效）。
3. `variables_json` 只做元数据/类型校验，不校验模板实际引用的变量；缺变量在渲染时抛错。
4. 无删除/停用接口；历史版本只增不减，长期需归档策略。
5. 激活并发由部分唯一索引兜底，不做自动重试；多管理员同时激活可能一方 409/500。
6. Prompt 内容无审核/回滚预览；上线前仍需人工在测试库验证。
7. 无 API 端到端审计日志（谁在何时启用）；`created_by/updated_at` 只覆盖行级留痕。

## 12. 实施记录（2026-10-31）

- 提交：`3a7aaad` 表/迁移/种子 → `a8b097a` 文本渲染/answerer → `4282bc4` service → `8193ada` admin 接口 → `226a65f` 激活 flush 修复 → `b1345e9` ask.py 接入；worktree 干净，未 push。
- 迁移：`0006_s3_4` 实跑成功；`qa/v1` active、`variables_json=["context", "question"]`、`created_by=NULL`；与 `qa_v1.md` 仅差末尾一个换行（DB 260 / 文件 259 字符，渲染无影响）。
- 测试：新增 26 条；全量 **636 passed, 1 warning**（基线 610）。
- 真实验收（真实 Postgres + DashScope LLM，`test1` id=18）：
  - v1 基线：回答正常、末尾 `Prompt：qa/v1`；tokens 685/866/1551，cost ¥0.002280。
  - HTTP `POST` 建 `qa/v2`（v1 + “回答末尾必须写【PROMPT-V2】”，`activate=true`，201）→ 同一问题回答出现【PROMPT-V2】、`Prompt：qa/v2`；tokens 699/802/1501，cost ¥0.002163。
  - `GET` 历史 v2/v1；`PUT /1/activate` → v1 active、v2 inactive；同一问题标记消失、`Prompt：qa/v1`；tokens 685/862/1547，cost ¥0.002272。
  - 临时 admin 已删除（`created_by` 置 NULL），v2 inactive 保留为历史。
- 偏差/修复：首次真实激活触发 `uq_prompt_templates_active_name` 冲突（同一 flush 旧 false/目标 true）。改为全部置 false → `flush()` → 目标 true → commit；`test_activate_prompt_switches_exclusive` 增加 flush 断言。此偏差为实测发现的正确性修复，未改变 spec 契约。
- 文档：API §11、SCHEMA §8.3、D-038、PROGRESS、AGENTS §9.2/§9.6、实施计划 S3-4、本 spec 与 plan 执行记录。