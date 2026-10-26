# S2-1 数据模型与迁移（第一批）spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-1（users / roles / user_roles / user_relations / subjects / knowledge_points / knowledge_edges）
- 日期：2026-10-26
- 状态：已实施并验收（2026-10-26）；实测证据见 PROGRESS 2026-10-26（S2-1）与 plan「执行记录」
- 上游：S1-3 首个迁移 `0001_s1_3`（note_chunks）、S0-4 三件套、S0-5 配置/日志基座
- 下游：S2-2 认证、S2-3 RBAC、S2-5 笔记表与 FK 回补、S2-9 知识点树
- 产物：`backend/app/models/{enums,user,user_relation,subject,knowledge_point,knowledge_edge}.py`、`backend/alembic/versions/0002_s2_1_*.py`、`backend/tests/test_models_s2_1.py`

## 1. 目标

把阶段 2 的第一批业务表落成可正反执行的 Alembic 迁移，让 S2-2 起的认证、权限、笔记、知识点功能有稳定的数据结构底座。本卡只交付**模型 + 迁移**，不交付任何 API。

验收标准（任务卡）：`alembic upgrade head` 成功；`\d knowledge_points` 字段齐全；`alembic downgrade -1` 能回退。

## 2. 范围

### 2.1 做

- 5 张表：`users`、`user_relations`、`subjects`、`knowledge_points`、`knowledge_edges`
- 枚举常量（`app/models/enums.py`）+ 由常量生成的 CHECK 约束
- 每个表一个 ORM 模型文件，统一 `id BIGINT IDENTITY` 主键、`created_at/updated_at`、`uq_/ix_/ck_` 命名
- 迁移 `0002_s2_1`：upgrade 建 5 表 + 索引；downgrade 逆序删表
- 模型契约单元测试（字段 / 可空性 / 类型 / 约束 / 索引 / 外键目标 / 枚举值）
- 契约文档与项目宪法同步（SCHEMA / AGENTS / DECISIONS / PROGRESS）
- `scripts/smoke.py` 的 `REQUIRED_TABLES` 填入本批 5 张表（S0-7 预留的维护点）

### 2.2 不做

- 不建 `roles` / `user_roles` 两张表（见 §2.3-1）
- 不做注册/登录/JWT/RBAC（S2-2 / S2-3）
- 不改 `note_chunks` 的列与索引；不补它的外键（见 §2.3-3）
- 不写种子数据（学科/知识点树导入属 S2-9）；不创建 demo 用户
- 不做分页/接口层（S2-4 起）
- 不引入任何新依赖

### 2.3 偏离任务卡（均为 2026-10-26 用户拍板或契约优先）

1. **表数 7 → 5**：任务卡列出的 `roles` / `user_roles` 在 `SCHEMA.md` 中不存在；契约文档用 `users.role` 单列枚举（§10.1），API.md 权限与 S2-3 的 `require_role()`、S2-2 的「JWT 含 user_id/role/exp」也都按单角色设计。按 AGENTS §8「冲突时以 SCHEMA 为准」→ 不建这两张表，任务卡条目视为 SCHEMA 成文前的旧稿。
2. **认证路线**：S2-2 任务卡倾向 `fastapi-users`，但其 SQLAlchemy 适配器是 async 专用（`AsyncSession` + `asyncpg`，官方文档明确 "SQLAlchemy ORM with asyncio"），本项目是同步 `psycopg` 栈（S1-3 定稿），且它要求 `email/hashed_password/is_active/is_verified/is_superuser` 与 SCHEMA 的 `username/password_hash/...` 不符。用户拍板 → users 按 SCHEMA 建，S2-2 改用 FastAPI 官方安全示例（pwdlib/bcrypt + PyJWT），不引入 fastapi-users。
3. **`note_chunks` 外键延后到 S2-5**：库中 83 行 `user_id=1` 没有对应 users 行，现在加 FK 会直接让迁移失败。S1-3 记录的「S2-1 建齐后补」改为「S2-5 建 notes/files 时一起补」；SCHEMA §4.3 的注记同步修正。
4. **枚举落地方式**：任务卡要求「PostgreSQL enum 或 varchar+CHECK，选一种并写进 AGENTS.md」→ 选 **TEXT + CHECK**（理由见 §5.3）。

## 3. 契约复核（PROGRESS 遗留问题 #1）

`SCHEMA.md` 中带 ⚠ 的推断项，本批 5 张表逐条复核结论：

| 位置 | SCHEMA 原写法 | 本卡结论 |
|---|---|---|
| §0 主键 | `id BIGINT GENERATED ALWAYS AS IDENTITY` ⚠ | 沿用 S1-3 `Identity(always=True)`，5 张表一致 |
| §0 数组字段 | `TEXT[]/BIGINT[]`，TEXT[] vs JSONB「S2-1 定」 | 定：**原生数组** `TEXT[]` / `BIGINT[]`，标签检索用 GIN；不用 JSONB。本批无数组字段，规则先在 §0 写死，S2-5 `notes.tags` 直接用 |
| §2.1 users.id / username | PK ⚠ / UNIQUE ⚠ | 采纳：`Identity(always=True)`；`username TEXT NOT NULL UNIQUE` |
| §2.1 users.role | 默认 `'student'` ⚠，枚举 §10.1「S2-2 定稿」 | 默认值与 4 值现在就定（CHECK 必须落库）：student/teacher/parent/admin |
| §2.1 users.grade | 取值「TODO」 | 保持 `TEXT NULL`，取值规则归 S2-2（注册入参） |
| §2.2 user_relations | 复合 UNIQUE ⚠，无时间列 | 采纳 UNIQUE(teacher_id, student_id)；补 created_at/updated_at；**新增** `ix_user_relations_student_id`（反查「这个学生被谁绑定」，SCHEMA 未列）与 `ck_user_relations_not_self`（禁止自己绑自己） |
| §2.3 subjects.code | UNIQUE ⚠ | 采纳 `uq_subjects_code`；`stage` 默认 `'高中'` 采纳 |
| §3.1 knowledge_points | subject_id/parent_id idx ⚠、UNIQUE(subject_id, code) ⚠、embedding HNSW ⚠建议、order_no 默认 0 ⚠ | 全部采纳；`level` 是 ✅ 方案 1–4 → 加 `CHECK 1..4`；`exam_weight` 用无精度 `NUMERIC`（权重取值范围方案未定，先不加精度） |
| §3.2 knowledge_edges | 复合 UNIQUE ⚠、dst idx ⚠、relation/source 枚举 ✅ | 全部采纳；**新增** `ck_knowledge_edges_not_self`（自环无意义）；`weight` 无精度 `NUMERIC` |
| 全表时间列 | 任务卡「所有表加 created_at/updated_at」 | 5 张表都补（users 只补 updated_at）；维护方式见 §6.3 |

复核后**没有**再遗留的 ⚠「待定」项；`users.grade` 取值与 `questions.tags` 等后续表的问题不属于本批（分别在 S2-2 / S2-5）。

## 4. 数据模型

### 4.1 users

| 字段 | 类型 | 可空 | 默认值 | 约束/说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | PK |
| username | TEXT | 否 | — | `uq_users_username` UNIQUE |
| password_hash | TEXT | 否 | — | S2-2 写入；本卡不存任何口令 |
| nickname | TEXT | 否 | — | 显示名 |
| grade | TEXT | 是 | — | 年级；取值规则 S2-2 定 |
| role | TEXT | 否 | `'student'` | `ck_users_role` ∈ student/teacher/parent/admin |
| created_at | TIMESTAMPTZ | 否 | `now()` | |
| updated_at | TIMESTAMPTZ | 否 | `now()` | 应用层 `onupdate` |

### 4.2 user_relations

| 字段 | 类型 | 可空 | 默认值 | 约束/说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | PK |
| teacher_id | BIGINT | 否 | — | FK→`users.id`；语义为「查看方」，家长复用此列（方案原文） |
| student_id | BIGINT | 否 | — | FK→`users.id`；`ix_user_relations_student_id` |
| created_at / updated_at | TIMESTAMPTZ | 否 | `now()` | |

- `uq_user_relations_teacher_student` UNIQUE(teacher_id, student_id)
- `ck_user_relations_not_self` CHECK(teacher_id <> student_id)

### 4.3 subjects

| 字段 | 类型 | 可空 | 默认值 | 约束/说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | PK |
| name | TEXT | 否 | — | 学科名，如「数学」 |
| code | TEXT | 否 | — | `uq_subjects_code` UNIQUE，如 `math` |
| stage | TEXT | 否 | `'高中'` | 学段 |
| config_json | JSONB | 是 | — | 难度分布 / 题型配比默认值 |
| created_at / updated_at | TIMESTAMPTZ | 否 | `now()` | |

### 4.4 knowledge_points

| 字段 | 类型 | 可空 | 默认值 | 约束/说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | PK |
| subject_id | BIGINT | 否 | — | FK→`subjects.id`；`ix_knowledge_points_subject_id` |
| parent_id | BIGINT | 是 | — | 自引用 FK→`knowledge_points.id`；根为 NULL；`ix_knowledge_points_parent_id` |
| name | TEXT | 否 | — | 知识点名称 |
| code | TEXT | 否 | — | 如 `MATH-FUNC-012`；`uq_knowledge_points_subject_code` UNIQUE(subject_id, code) |
| level | SMALLINT | 否 | — | 1–4；`ck_knowledge_points_level` |
| description | TEXT | 是 | — | 说明 |
| exam_weight | NUMERIC | 是 | — | 考纲权重（复习优先级 / 组卷打分用） |
| embedding | VECTOR(1024) | 是 | — | **建列但本卡不填**；`ix_knowledge_points_embedding_hnsw` HNSW(vector_cosine_ops, m=16, ef_construction=64) |
| order_no | INTEGER | 否 | `0` | 同层排序 |
| created_at / updated_at | TIMESTAMPTZ | 否 | `now()` | |

### 4.5 knowledge_edges

| 字段 | 类型 | 可空 | 默认值 | 约束/说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | PK |
| src_kp_id | BIGINT | 否 | — | FK→`knowledge_points.id` |
| dst_kp_id | BIGINT | 否 | — | FK→`knowledge_points.id`；`ix_knowledge_edges_dst_kp_id` |
| relation | TEXT | 否 | — | `ck_knowledge_edges_relation` ∈ prerequisite/related/confusable/contains |
| weight | NUMERIC | 是 | — | 关系强度 |
| source | TEXT | 否 | — | `ck_knowledge_edges_source` ∈ ai/manual |
| created_at / updated_at | TIMESTAMPTZ | 否 | `now()` | |

- `uq_knowledge_edges_src_dst_relation` UNIQUE(src_kp_id, dst_kp_id, relation)
- `ck_knowledge_edges_not_self` CHECK(src_kp_id <> dst_kp_id)

### 4.6 外键删除策略

全部用 PostgreSQL 默认 `NO ACTION`（等价于 RESTRICT）：被引用的 user / subject / knowledge_point 还有引用时删除会失败。理由：本卡不做级联删除业务；S2-3/S2-9 明确删除语义后再用新迁移改，避免现在猜错策略导致静默丢数据。

## 5. 枚举与常量

### 5.1 `app/models/enums.py`

```python
class UserRole(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    PARENT = "parent"
    ADMIN = "admin"

class EdgeRelation(StrEnum):
    PREREQUISITE = "prerequisite"
    RELATED = "related"
    CONFUSABLE = "confusable"
    CONTAINS = "contains"

class EdgeSource(StrEnum):
    AI = "ai"
    MANUAL = "manual"
```

### 5.2 CHECK 由枚举生成

`enums.py` 提供 `in_check(column: str, values: Iterable[str | StrEnum]) -> str`，把枚举值拼成 `"role IN ('student', 'teacher', 'parent', 'admin')"`。模型侧写 `CheckConstraint(in_check("role", UserRole), name="ck_users_role")`。目的：**枚举值的唯一来源是 Python 常量**，SCHEMA 的 CHECK 文本与 Python 后续 Pydantic 校验不会各写一份而漂移。

### 5.3 为什么 SELECT TEXT + CHECK 而不是 PostgreSQL ENUM

- 改值集只需 `ALTER TABLE ... DROP/ADD CONSTRAINT`，不用 `ALTER TYPE ... ADD VALUE`（PG 的 enum 加值不可回滚，`downgrade` 会变成不可执行）；
- 本卡要求 downgrade 能真实回退；
- 与既有 `note_chunks.chunk_type` 的 `TEXT + server_default` 风格一致；
- 中文枚举值（S4 的 `mistakes.status` 等）用 TEXT 更自然。
- 代价：不享受 PG enum 的类型安全；值约束在 CHECK 里，写入前由应用层 Pydantic 兜底。该结论写进 `AGENTS.md §4`。

## 6. 模型层与迁移设计

### 6.1 文件布局

```
backend/app/models/
  __init__.py          # 显式导入全部模型，Alembic target_metadata 才能发现
  enums.py             # StrEnum + in_check()
  user.py              # User
  user_relation.py     # UserRelation
  subject.py           # Subject
  knowledge_point.py   # KnowledgePoint
  knowledge_edge.py    # KnowledgeEdge
backend/alembic/versions/
  0002_s2_1_business_tables.py   # revision="0002_s2_1", down_revision="0001_s1_3"
backend/tests/
  test_models_s2_1.py
```

### 6.2 迁移

- 单文件、单 revision；upgrade 顺序：users → user_relations → subjects → knowledge_points → knowledge_edges（被引用表先建）。
- 索引在 `create_table` 后用 `op.create_index` 建；HNSW 参数与 `0001` 完全一致。
- downgrade 逆序 `op.drop_table`；表的索引与约束随表一起删除（与 `0001` 的写法一致），不单独 drop_index。
- 不写 `CREATE EXTENSION vector`（`0001` 已建；全新库也会先执行 `0001`）。
- 不修改 `0001`（AGENTS §6 禁止修改已提交迁移）。

### 6.3 时间列维护口径

`created_at`：`server_default=func.now()`，插入即写。
`updated_at`：`server_default=func.now()` + SQLAlchemy `onupdate=func.now()`，即**应用层经 ORM 更新时刷新**（与 SCHEMA §4.2 注记「应用层维护」一致），不建数据库触发器。代价：绕过 ORM 的裸 SQL 更新不会刷新 `updated_at`，在 S2-5 的验收里用 ORM API 验证。

## 7. 校验与错误处理

本卡无 HTTP 层，错误处理体现在迁移执行与约束上：

| 场景 | 期望行为 |
|---|---|
| 非法 `role` / `relation` / `source` | CHECK 约束拒绝，`psycopg.errors.CheckViolation` |
| 重复 `username` / `subjects.code` / `(subject_id, code)` / `(teacher_id, student_id)` / `(src, dst, relation)` | UNIQUE 约束拒绝 |
| 自绑关系 / 自环边 | CHECK 约束拒绝 |
| `level` 不在 1–4 | CHECK 约束拒绝 |
| 删除仍被引用的 subject / kp / user | FK 约束拒绝（NO ACTION） |
| 空表建 HNSW / 空 embedding | 允许（HNSW 跳过 NULL 行） |
| `alembic downgrade -1` | 5 表逆序删除，回到 `0001_s1_3` |

迁移失败时必须整事务回滚（Alembic 默认 transactional DDL，PG 支持），不留下半建状态。

## 8. 测试

单测不连数据库（与现有测试套件一致：外部依赖一律 fake/mock），用 SQLAlchemy metadata 断言契约；真实 DDL 由 §10 的验收命令覆盖。

`backend/tests/test_models_s2_1.py` 覆盖：

1. 5 张表名与列集合（照 `test_note_chunk_model.py` 的 `_EXPECTED_COLUMNS` 写法）；
2. 可空性逐列断言（与 §4 表格一致）；
3. 类型断言：`id` 为 `BigInteger` + `Identity`，`embedding` 为 `Vector(1024)`，`config_json` 为 `JSONB`，`level` 为 `SmallInteger`，时间列为 `DateTime(timezone=True)`；
4. 约束断言：5 个 UNIQUE 的三元组正确、7 条 CHECK 存在且文本含正确枚举值、`updated_at` 有 `onupdate`；
5. 索引断言：6 个 btree 索引名/列正确；HNSW 索引 `postgresql_using="hnsw"`、`vector_cosine_ops`、`m=16`、`ef_construction=64`；
6. 外键断言：`user_relations` 两列、`knowledge_points.subject_id/parent_id`、`knowledge_edges.src/dst` 指向的表名与列名正确；
7. 枚举断言：`UserRole`/`EdgeRelation`/`EdgeSource` 值集与 SCHEMA §10 一致；`in_check()` 输出格式正确（引号、逗号）。
8. `app.models.__all__` 包含全部 5 个模型（Alembic 发现依赖它）。

## 9. 验收（实施后逐条真实执行并贴输出）

```bash
cd backend
../.venv/Scripts/python.exe -m alembic upgrade head

# 表结构逐个核对（Windows 控制台先 chcp 65001）
docker exec study-agent-postgres psql -U study -d study_agent -c "\d users"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d user_relations"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d subjects"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d knowledge_points"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d knowledge_edges"

# 反向约束验证（事务内制造违规后 ROLLBACK，不污染库）
# ① 非法 role ② 重复 username ③ 自环边 ④ 删除被引用学科
docker exec study-agent-postgres psql -U study -d study_agent <<'SQL'
BEGIN;
INSERT INTO users(username, password_hash, nickname, role) VALUES ('t_u1','x','测试用户_1','hacker');  -- 期望 CheckViolation
ROLLBACK;
...（逐条同法）
SQL

# 回退 + 前滚
../.venv/Scripts/python.exe -m alembic downgrade -1
docker exec study-agent-postgres psql -U study -d study_agent -c "\dt"   # 5 表消失、note_chunks 仍在
../.venv/Scripts/python.exe -m alembic upgrade head

# 回归
../.venv/Scripts/python.exe -m pytest -q          # 现有 191 + 新增全绿
cd .. && .venv/Scripts/python.exe scripts/smoke.py   # 核心表 6/6 在位（本批 5 张 + note_chunks）
```

测试数据全部用「测试用户_1」式明显假数据（AGENTS §9.4），不写真实姓名/学校。

## 10. 文档同步

| 文档 | 改动 |
|---|---|
| `SCHEMA.md` | §0 数组字段拍板；users 补 `updated_at`；user_relations/subjects/knowledge_points/knowledge_edges 补时间列与新索引/约束；§4.3 注记改为 FK 延后 S2-5；§10.1 role 定稿 |
| `AGENTS.md` | §4 增「枚举一律 TEXT + CHECK，不用 PG ENUM」；§9.6 增模型锚点（`app/models/user.py`） |
| `DECISIONS.md` | 新增 D-021（本卡 4 条决策：5 表、官方安全示例、TEXT+CHECK、FK 延后） |
| `PROGRESS.md` | S2-1 打勾、当前状态、变更日志（实测数字） |
| `.env.example` / `requirements.txt` | **不变**（无新配置、无新依赖） |
| `scripts/smoke.py` | `REQUIRED_TABLES` = 本批 5 张 + 既有 `note_chunks`（共 6 张） |

## 11. 风险

| 风险 | 应对 |
|---|---|
| 迁移已提交后不可改（AGENTS §6） | spec/plan 先经用户确认；迁移内容在 plan 里写死 |
| `Identity(always=True)` 导致导入数据无法指定 id | S2-9 导入知识点树用默认自增 + `code` 业务键，不指定 id；若确需，`OVERRIDING SYSTEM VALUE` |
| `knowledge_points.parent_id` 自引用删除顺序 | 本卡不删数据；S2-9 删除逻辑先删子节点再删父节点 |
| 空表建 HNSW 索引 | pgvector 支持；与 `note_chunks` 同参数已验证 |
| 约束过严影响后续业务（如一人多角色） | 若 S2-3 确认需要多角色，用新迁移加关联表并放宽 CHECK，不改本迁移 |

## 12. 自检

- [x] 每张表都能在 SCHEMA.md 找到来源（users §2.1、user_relations §2.2、subjects §2.3、knowledge_points §3.1、knowledge_edges §3.2）
- [x] 任务卡「先建 embedding 列但不填」已满足（§4.4）
- [x] 任务卡「所有表加 created_at/updated_at」已满足（§6.3）
- [x] 任务卡「枚举选一种并写进 AGENTS.md」已满足（§5.3 + §10）
- [x] 任务卡「分批迁移，本批 7 张」→ 5 张，偏离理由与拍板记录在 §2.3-1
- [x] 遗留问题 #1（SCHEMA ⚠ 复核）已在本批范围内逐条结案（§3）
- [x] 无 TBD/TODO 留给实施者（`users.grade` 取值属 S2-2 业务规则，非本卡占位）