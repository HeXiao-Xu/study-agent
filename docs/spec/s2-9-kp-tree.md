# S2-9 知识点树 CRUD + 导入脚本 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-9
- 日期：2026-10-26
- 状态：已实施并验收（2026-10-26；写权限 / 覆盖语义 / 种子数据来源 已拍板）
- 上游：S2-1 已建 `subjects`/`knowledge_points`/`knowledge_edges`（含 level CHECK、code 唯一、HNSW 索引），S2-5 已建 `note_kps`
- 下游：S2-10 用树做知识点对齐与打分；S2-14 前端树管理
- 产物：`api/v1/kp.py`、`schemas/kp.py`、`services/kp_service.py`、`services/kp_import.py`、`scripts/import_kp_tree.py`、`data/kp_math.json`

## 1. 目标

1. 知识点树**一次查询、内存组树**（禁止 N+1 递归）；提供读树、建/改/删节点接口。
2. 写接口限 `admin`/`teacher`；读接口登录即可（API.md §4 原写 student，本卡放宽为登录用户，仍覆盖学生）。
3. 节点 `code` 在 subject 内唯一；`level` 由父节点推导（根 1，最深 4）；移动节点时校验环与子树深度。
4. 删除有保护：有子节点、被 `note_kps` 或 `knowledge_edges` 引用时返回 409 并说明原因。
5. 导入脚本支持 `append`（只 upsert）与 `overwrite`（同步，引用节点保护），打印新增/更新/删除/跳过统计，支持 `--dry-run`。
6. 种子数据：高中数学 4 层 ≈110 节点，AI 生成草稿 + 用户人工校对后导入。

非目标：知识点对齐（S2-10）、前端页面（S2-14）、`knowledge_edges` CRUD、知识点 embedding（S2-10）、多学科种子。

## 2. 范围

### 2.1 做

- `app/schemas/kp.py`：`SubjectOut`、`KpNodeOut`、`KpTreeOut`、`KpCreate`、`KpUpdate`。
- `app/services/kp_service.py`：`list_subjects`、`get_tree`、`create_kp`、`update_kp`、`delete_kp`。
- `app/services/kp_import.py`：`load_tree_file`（校验）、`flatten_tree`、`plan_sync`（纯函数）、`import_tree`（落库）。
- `app/api/v1/kp.py`：4 个读/写接口 + subjects 列表；`api/router.py` 挂载。
- `backend/scripts/import_kp_tree.py`：CLI（`--subject`、`--mode append|overwrite`、`--file`、`--dry-run`）。
- `backend/data/kp_math.json`：高中数学 4 层种子（≥100 节点）。
- 测试：`tests/test_kp_service.py`（12）、`tests/test_kp_import.py`（12）、`tests/test_kp_api.py`（10）。
- 文档：API.md §4、SCHEMA.md 注记、AGENTS §9.2/§9.6、DECISIONS D-029、PROGRESS、实施计划勾选、spec/plan 执行记录。

### 2.2 不做

- 不新增迁移：`knowledge_points` 字段已齐（S2-1），`subjects` 由导入脚本种 `math`。
- 不做批量移动/拖拽排序接口；`order_no` 通过单节点 PATCH 调整。
- 不做 `knowledge_points.embedding` 写入。
- 不提供删除 subject 的接口；不级联删除节点。
- 不做 `GET /kp/{id}` 单点详情（树接口已含全部字段）。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 读接口用 `?subject=math`（学科 **code**），沿用 API.md §4 既有契约 | 契约先行；前端不需要先拿 subject_id |
| 2 | 写接口 `require_role("admin", "teacher")`；读接口 `get_current_user` | 全局树不应由学生改；teacher 可自助注册，便于真实 curl 验收（admin 需改库） |
| 3 | 组树：`SELECT ... WHERE subject_id=? ORDER BY level, order_no, id` 一次查完，内存 `id→node` 拼 children | 任务卡明确禁止 N+1 递归 |
| 4 | `level` 由父节点推导，不接受客户端传；根 1、最深 4 | 避免客户端造出非法层级 |
| 5 | 移动节点（改 `parent_id`）时校验：目标必须同 subject、不能是自身/后代；子树高度 + 新层级 ≤ 4；成功后 BFS 重算所有后代 level | 环与超深会破坏树与 CHECK |
| 6 | `code` 不可修改（PATCH 忽略/拒绝） | 导入脚本与后续对齐按 code 稳定识别；改 code 等价于换节点 |
| 7 | 删除保护：有子节点 409「存在子知识点」；被 `note_kps` 引用 409「已被笔记引用」；被 `knowledge_edges` 引用 409「存在知识点关系」 | 避免静默丢数据；S2-10 数据不能被误删 |
| 8 | 重复 code 建/改父冲突 → 409「知识点编码已存在」 | 依赖 `uq_knowledge_points_subject_code`，先查再插仍兜底捕获 IntegrityError |
| 9 | 导入 `append`：按 code upsert，不删除；`overwrite`：按 code 同步 + 删除文件缺失项 | 任务卡要求两种模式 |
| 10 | 覆盖删除顺序：从叶子向上；仍有子节点或被引用 → 保留并计入 skipped，打印 code/原因 | 引用保护优先于“完全同步” |
| 11 | 导入统计：`created/updated/deleted/skipped/unchanged`；`--dry-run` 只打印计划不落库 | 可预演、可核对 |
| 12 | 种子数据每节点含 `code/name/description/exam_weight/order_no/children`；`exam_weight` 0.1–1.0，同层之和不必为 1 | 复习优先级与 S2-10 打分用；文档说明非考纲精确值 |
| 13 | 导入脚本自身建 subject（`math`/`高中数学`/`高中`），已存在则复用 | `subjects` 目前为空，S2-9 必须能独立跑通 |
| 14 | 脚本退出码：0 成功、2 数据/参数错误（JSON 非法、重复 code、深度 >4、subject 不存在且未允许创建）、1 数据库错误 | 便于 CI/人工判断 |

## 4. 数据

**无迁移**。使用现有表：

- `subjects`：脚本确保 `code='math'`, `name='高中数学'`, `stage='高中'`。
- `knowledge_points`：`(subject_id, code)` UNIQUE、`level 1..4` CHECK、`parent_id` 自引用（NO ACTION）、`order_no`、`exam_weight NUMERIC`、`description`。
- `note_kps`/`knowledge_edges`：删除保护查询。

种子节点字段：`code` 形如 `MATH-FUNC-01`；`name` 中文；`description` 一句话；`exam_weight` 0.1–1.0；`order_no` 同层 0 起。

## 5. 接口（API.md §4 定稿）

### GET /api/v1/kp/subjects
- 权限：登录用户
- 出参：`Envelope[list[SubjectOut]]`：`id/name/code/stage`
- 错误：`401/40100`

### GET /api/v1/kp/tree?subject=math
- 权限：登录用户
- 入参：`subject` 学科 code，必填，1–30
- 出参：`Envelope[KpTreeOut]`
  ```json
  {"subject": {"id":1,"name":"高中数学","code":"math","stage":"高中"},
   "nodes": [{"id":1,"subject_id":1,"parent_id":null,"name":"高中数学","code":"MATH","level":1,
              "description":"...","exam_weight":1.0,"order_no":0,"children":[...]}]}
  ```
- 错误：`404/40400`「学科不存在」；`422/42200` 缺 `subject`

### POST /api/v1/kp
- 权限：`admin`/`teacher`（其他 403/40300）
- 入参：`{"subject":"math","parent_id":null,"code":"MATH-FUNC-01","name":"函数的概念","description":null,"exam_weight":0.8,"order_no":1}`
- 成功：**201** `Envelope[KpNodeOut]`（不含 children）
- 校验：`code` 1–50、`name` 1–100、`description` ≤500、`exam_weight` 0–1、`order_no` ≥0
- 错误：`404` 学科/父节点不存在；`409` 编码已存在；`422` 层级超 4 / 父节点不属于同一学科

### PATCH /api/v1/kp/{kp_id}
- 权限：`admin`/`teacher`
- 入参：`name/description/exam_weight/order_no/parent_id` 均可选；`code`/`subject` 不可改
- 成功：200 `Envelope[KpNodeOut]`
- 错误：`404` 节点/新父节点不存在；`422` 成环 / 子树超深 / 跨学科；`409`（保留）
- 说明：改父后自动重算该节点及全部后代的 `level`

### DELETE /api/v1/kp/{kp_id}
- 权限：`admin`/`teacher`
- 成功：**204**（无响应体）
- 错误：`404`；`409`「存在子知识点，请先删除子节点」/「已被笔记引用，无法删除」/「存在知识点关系引用，无法删除」

## 6. 组件契约

### services/kp_service.py

```python
def list_subjects(session: Session) -> list[Subject]
def get_tree(session: Session, *, subject_code: str) -> KpTreeOut
def create_kp(session: Session, *, payload: KpCreate) -> KnowledgePoint
def update_kp(session: Session, *, kp_id: int, payload: KpUpdate) -> KnowledgePoint
def delete_kp(session: Session, *, kp_id: int) -> None
```

实现要点：
- `get_tree`：`select(KnowledgePoint).where(subject_id==...).order_by(level, order_no, id)`；`children_map: dict[int|None, list]`；`KpNodeOut` 递归构造。
- `create_kp`：subject by code → 404；`parent_id` 存在且同 subject → 否则 422；level=parent.level+1 或 1；>4 → 422；查重 code → 409；插入、commit、refresh。
- `update_kp`：取节点（404）；逐字段 set；改 `parent_id` 时：不能等于自身、必须同 subject、不能是后代（用同 subject 全量 `id→parent_id` 向上追溯或 BFS 子树）、子树高度 `h` 满足 `new_level+h-1<=4`；重算后代 level（BFS）；commit。
- `delete_kp`：取节点（404）；`exists(select(KnowledgePoint).where(parent_id==id))` → 409；`exists(select(NoteKp).where(kp_id==id))` → 409；`exists(select(KnowledgeEdge).where(or_(src==id, dst==id)))` → 409；delete、commit。

### services/kp_import.py

```python
class SeedNode(BaseModel):
    code: str; name: str; description: str | None = None
    exam_weight: float | None = None; order_no: int = 0
    children: list["SeedNode"] = []

def load_tree_file(path: Path) -> list[SeedNode]      # 读 JSON + Pydantic 校验；文件根为 {"subject":{"code":"math","name":"高中数学"},"nodes":[...]}
def flatten_tree(nodes: list[SeedNode], *, subject_code: str) -> list[FlatSeed]
def plan_sync(existing: list[KnowledgePoint], incoming: list[FlatSeed], *, referenced_codes: set[str], mode: str) -> SyncPlan
def import_tree(session: Session, *, payload: TreeFile, mode: str, dry_run: bool) -> ImportStats
```

`plan_sync` 纯函数（可单测，不碰 DB）：
- 以 code 对齐；`create`（新 code）、`update`（字段有变化）、`unchanged`；
- `overwrite` 下 `delete` = existing 中不在 incoming 的 code，且无子节点残留（按 level 降序处理）、不在 `referenced_codes`；
- 其余保留项进 `skipped`，附原因 `has_children` / `referenced`。

`import_tree`：
1. `load_tree_file` → 校验深度 ≤4、subject 内 code 无重复（重复 → `ValueError` 带 code）。
2. subject：按 code 查 `subjects`，无则创建（`name` 来自文件，`stage='高中'`）。
3. 读 existing（同 subject）；读 referenced codes（`note_kps` join `knowledge_points`，及 `knowledge_edges` 两端）。
4. `plan_sync`；`dry_run` 打印计划返回统计。
5. 落库顺序：先 create/update 根→叶（父 id 映射 code→id），再 delete 叶→根；每步 flush；最后 commit。
6. 返回 `ImportStats(created, updated, deleted, skipped, unchanged)`。

### scripts/import_kp_tree.py

```bash
python scripts/import_kp_tree.py --file data/kp_math.json --mode append
python scripts/import_kp_tree.py --file data/kp_math.json --mode overwrite --dry-run
```
- `--mode` 默认 `append`；`--subject` 默认取文件内 `subject.code`；`--dry-run` 不落库。
- 输出：`导入完成 subject=math mode=append created=… updated=… deleted=… skipped=… unchanged=…`；skipped 逐条 `skip code=… reason=…`。
- 异常：数据错误打印 `数据错误: …` 退出 2；DB 错误退出 1。

## 7. 种子数据（backend/data/kp_math.json）

结构：

```json
{"subject": {"code": "math", "name": "高中数学", "stage": "高中"},
 "nodes": [{"code": "MATH", "name": "高中数学", "description": "…", "exam_weight": 1.0, "order_no": 0,
            "children": [{"code": "MATH-SET", "name": "集合与常用逻辑用语", "…": "…", "children": []}]}]}
```

覆盖 11 个二级模块、约 110 节点、4 层：

| 二级模块 | code 前缀 | 三级/四级示例 |
|---|---|---|
| 集合与常用逻辑用语 | MATH-SET | 集合表示/关系/运算、充分必要条件、量词 |
| 一元二次函数、方程和不等式 | MATH-QUAD | 不等式性质、基本不等式、一元二次不等式 |
| 函数 | MATH-FUNC | 概念与表示、单调性、奇偶性、周期性、幂/指/对函数、图象变换、零点 |
| 三角函数 | MATH-TRIG | 弧度制、诱导公式、恒等变换、图象性质、解三角形 |
| 平面向量与复数 | MATH-VEC | 线性运算、坐标、数量积、复数运算 |
| 数列 | MATH-SEQ | 等差/等比、求和、递推通项 |
| 立体几何 | MATH-GEO | 几何体、平行/垂直、空间向量、角与距离 |
| 解析几何 | MATH-ANA | 直线、圆、椭圆、双曲线、抛物线、位置关系 |
| 导数及其应用 | MATH-DER | 运算、单调性、极值最值、不等式 |
| 概率与统计 | MATH-PROB | 古典概型、条件概率、随机变量、抽样、回归、独立性检验 |
| 计数原理 | MATH-COUNT | 两个原理、排列组合、二项式定理 |

要求：同层 `order_no` 唯一递增；`exam_weight` 0.1–1.0；`description` 一句话；节点总数 ≥100（测试断言）。

## 8. 测试计划（实际 37 条）

`tests/test_kp_service.py`（12）
1. `get_tree` 一次查询组出正确层级与 children 顺序（FakeSession 记录 execute 次数=1）
2. `get_tree` 学科不存在 → 404
3. `create_kp` 根节点 level=1
4. `create_kp` 子节点 level=父+1
5. `create_kp` 第 5 层 → 422
6. `create_kp` 同 subject 重复 code → 409
7. `create_kp` 父节点跨学科 → 422
8. `update_kp` 改名/权重成功
9. `update_kp` 父节点设为自身/后代 → 422（成环）
10. `update_kp` 移动后子树超 4 层 → 422
11. `update_kp` 移动成功且后代 level 全部 +1
12. `delete_kp` 有子节点/被 note_kps 引用/被 edge 引用 → 409；叶子删除成功

`tests/test_kp_import.py`（12）
1. `load_tree_file` 合法 JSON → 嵌套 SeedNode
2. 文件不存在 → FileNotFoundError
3. JSON 非法 → ValueError
4. 文件内重复 code → ValueError
5. 深度 5 → ValueError
6. `flatten_tree` 生成 parent_code/level/order_no
7. `plan_sync append`：新增/更新/不变分类正确，不产生 delete
8. `plan_sync overwrite`：缺失叶子进 delete
9. `plan_sync overwrite`：有子节点残留 → skipped(has_children)；被引用 → skipped(referenced)
10. `plan_sync` 字段无变化 → unchanged

`tests/test_kp_api.py`（10）
1. `GET /kp/subjects` 返回列表
2. `GET /kp/tree?subject=math` 200 且嵌套
3. 缺 `subject` → 422
4. 学科不存在 → 404
5. student POST → 403
6. teacher POST → 201
7. 重复 code → 409
8. PATCH 改父 → 200 且 level 更新
9. DELETE 有子 → 409
10. DELETE 叶子 → 204

## 9. 验收（真实 Postgres + uvicorn + 导入脚本，已完成）

1. `python scripts/import_kp_tree.py --file data/kp_math.json --mode append` → 打印 `created≈110`、退出 0；psql `subjects` 1 行、`knowledge_points` ≥100 行、`level` 1–4 分布合理。
2. 再跑一次 append → `created=0 updated=0 unchanged≥100`（幂等）。
3. 启动 uvicorn，注册 teacher；`GET /kp/subjects`、`GET /kp/tree?subject=math` → 200，节点数与库一致；student 写 → 403。
4. teacher 建一个叶子节点 → 201；PATCH 改名/移动 → 200 且 psql level 正确；DELETE → 204。
5. 删除有子节点的根 → 409「存在子知识点」；给某叶子插一条 `note_kps` 引用后删除 → 409「已被笔记引用」，清理后 204。
6. `--mode overwrite --dry-run` 打印计划不落库；用删掉一个叶子的临时 JSON 跑 overwrite → `deleted=1`，该 code 从库消失；被引用节点保留并打印 `skip ... reason=referenced`。
7. 清理 notes/note_kps/knowledge_points/subjects/edge；pytest 全绿。

## 10. 文档同步（已完成）

- API.md §4：补全 5 个接口、权限、错误码、树出参。
- SCHEMA.md §3.1：补注“S2-9 起由导入脚本写入；父节点删除由业务保护”。
- AGENTS.md §9.2：知识点树规则（一次查询组树、level 推导、删除保护、code 稳定）；§9.6 锚点。
- DECISIONS.md D-029。
- PROGRESS.md 状态/清单/遗留/日志；实施计划勾选 S2-9。
- spec/plan 执行记录。

## 11. 执行记录

- 提交：`942fa45` 服务与校验、`ffdbc3b` 导入计划与落库、`39cd18c` 种子与 CLI、`52e4868` 接口、`daad0e5` 引用保护修复、`docs(s2-9)` 文档。
- pytest：**462/462**（425 + 37；seed 3、import 12、service 12、api 10）。
- 真实导入：append `created=108`，`subjects=1`，level 分布 1/11/68/28；二次 append `created=0 unchanged=108`；tree total=108。
- 权限：student 读 200、匿名 401、student 写 403/40300；teacher 建 201（level=4）。
- 校验：PATCH 移动 200（level=2）；删根 409「存在子知识点」；`note_kps` 引用删 409「已被笔记引用」，清引用后 204。
- overwrite：`--dry-run` 与正式执行都 `deleted=1 skipped=1`，被引用节点保留并打印 `skip code=MATH-COUNT-02-02 reason=referenced`；再 append 补回 `created=1`。
- 偏差：首版 `import_tree` 把引用 **id** 当 **code** 比较，真实 overwrite 触发 `fk_note_kps_kp_id`；已改为 `referenced_codes_for(existing, ids)` 并补单测（`daad0e5`）；测试数由 32 增至 37。

## 12. 已知限制

- 种子树是 AI 草稿，需用户人工校对；`exam_weight` 为经验值，非官方考纲。
- 无节点拖拽/批量排序；`order_no` 冲突不做唯一约束，按 `order_no,id` 稳定排序。
- 删除节点是物理删除；被 S2-10 引用时需先处理引用。
- 覆盖导入不做跨 subject；只处理文件内 subject。
- 无并发锁：两个导入同时跑可能竞争同一 code（唯一约束兜底，第二个报错）。
- 导入脚本直接连库执行，不在事务外做备份；覆盖前建议先 `pg_dump`。