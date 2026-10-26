# S2-4 通用分页/排序/筛选 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-4
- 日期：2026-10-26
- 状态：已实施并验收（2026-10-26）；pytest 280/280，20 条新增用例全绿（证据见 plan 执行记录与 PROGRESS）
- 上游：S2-2/S2-3（鉴权与数据隔离）、API.md §0 分页约定
- 下游：S2-5 笔记列表、S4-2 错题列表、S4 题目/组卷列表——所有列表接口统一复用
- 产物：`backend/app/utils/pagination.py`、`backend/app/schemas/common.py`（新增 `PageData`）

## 1. 目标

把「每页多少条、第几页、按什么排、非法参数怎么报」收敛成一套可复用件：

1. 统一 query 参数：`page`（默认 1，≥1）、`page_size`（默认 20，1–100）；
2. 统一响应 `data`：`{items, total, page, page_size}`，仍套 `Envelope`；
3. 统一排序：`sort_by` + `order`（`asc`/`desc`），字段白名单由各接口声明，非白名单一律 `422/42200`；
4. 查询执行交给 `fastapi-pagination`（count 与 limit/offset 不手写）。

## 2. 范围

### 2.1 做

- `schemas/common.py`：新增泛型 `PageData[T]`
- `utils/pagination.py`：`PageParams` / `SortParams` 依赖、`paginate_query()`、`apply_sort()`
- 测试：SQLite 内存库真执行（不连 PostgreSQL、不访问网络）+ 测试内临时 FastAPI 应用验证参数校验与响应形状
- 依赖：`fastapi-pagination==0.16.1`（2026-10-26 用户批准；`pip --dry-run` 已确认只新增 1 个包，与 FastAPI 0.143 / Pydantic 2.14 无冲突）
- 文档：API.md §0 分页/排序定稿、AGENTS §9.2/§9.6、DECISIONS D-024、PROGRESS、requirements.txt

### 2.2 不做

- 不实现任何具体列表接口（笔记 S2-5、错题/题目 S4 才有）；本卡不新增生产路由
- 不做 cursor/keyset 分页（数据量变大再议；见 §8）
- 不做多字段排序（`sort_by=a,b`）——单字段足够当前列表需求
- 不做通用筛选 DSL（任务卡要求「筛选条件用显式参数而非拼接」，各接口显式声明）
- 不做 `pages` 字段（任务卡只要求 4 个字段；前端用 `ceil(total/page_size)` 即可）
- 不做 count 缓存/近似计数

### 2.3 关键决策（2026-10-26 用户确认）

| # | 决策 | 理由 |
|---|---|---|
| 1 | 引入 `fastapi-pagination==0.16.1` | 任务卡与 API.md 点名；count 查询会剥掉 ORDER BY、limit/offset 由库生成；依赖仅 1 个且无版本冲突 |
| 2 | 响应 `data = {items, total, page, page_size}`，query 用 `page` / `page_size` | 与任务卡逐字一致；库原生 `{items,total,page,size,pages}` 通过适配层转换，不把库的形状泄给前端 |
| 3 | `page_size` 上限 100、下限 1，`page` 下限 1 | 防止一次拉全库（DoS/内存）；越界由 FastAPI Query 校验 → `422/42200` |
| 4 | 排序白名单：每个接口显式传 `allowed={字段名: 列}` 映射 | 从结构上杜绝 `order_by(f"...{user_input}")` 注入；非法字段报 422 并列出可选字段 |
| 5 | 默认排序由调用方给（`default_sort`），全局默认方向 `desc` | 列表通常「最新在前」；具体字段是资源知识，不放进通用件 |
| 6 | 筛选只用显式参数 | 任务卡要求；通用 DSL 会让 SQL 形状不可预测、难以做索引审查 |
| 7 | 测试用 SQLite 内存库（`StaticPool` + `check_same_thread=False`） | 分页逻辑需要真实 SQL 执行才可信；SQLite 是进程内库，不算外部服务（AGENTS §9.4）；StaticPool 让 TestClient 线程与夹具共用同一内存库 |

## 3. 契约（同步写入 API.md §0）

### 3.1 分页参数（所有列表接口）

| 参数 | 类型 | 默认 | 约束 | 说明 |
|---|---|---|---|---|
| page | int | 1 | ≥1 | 页码，从 1 开始 |
| page_size | int | 20 | 1–100 | 每页条数 |

- 越界/非整数 → `422/42200`。
- 超过最后一页返回空 `items`，`total` 不变（不报错）。

### 3.2 响应形状

```json
{"code": 0, "message": "ok", "trace_id": "...", "data": {
  "items": [ ... ], "total": 42, "page": 2, "page_size": 20 }}
```

- `items` 元素类型由各接口 `PageData[ItemOut]` 决定。
- 不返回 `pages`、`size` 等库原生字段。

### 3.3 排序参数（所有列表接口）

| 参数 | 类型 | 默认 | 约束 |
|---|---|---|---|
| sort_by | string | 各接口默认字段 | 必须在白名单内，否则 `422/42200`「不支持的排序字段：xxx（可选：...）」 |
| order | string | `desc` | 只能是 `asc` / `desc` |

- 无排序参数的接口仍需有稳定默认排序（由接口通过 `default_sort` 声明），保证分页不漂移。
- 筛选：各接口显式声明（如 `subject=math&tag=函数`），不做通用 filter DSL。

## 4. 函数契约（utils/pagination.py）

```python
@dataclass(frozen=True)
class PageParams:
    page: int = 1
    page_size: int = 20

@dataclass(frozen=True)
class SortParams:
    sort_by: str | None = None
    order: str = "desc"

def page_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PageParams

def sort_params(
    sort_by: str | None = Query(None),
    order: Literal["asc", "desc"] = Query("desc"),
) -> SortParams

def paginate_query(
    session: Session,
    stmt: Select,
    params: PageParams,
    *,
    item_model: type[T],          # Pydantic 出参模型
) -> PageData[T]

def apply_sort(
    stmt: Select,
    *,
    sort_by: str | None,
    order: str,
    allowed: Mapping[str, Any],
    default_sort: str | None = None,
) -> Select
```

- `paginate_query`：`fastapi_pagination.ext.sqlalchemy.paginate(session, stmt, params=Params(page=..., size=...))` → `Page` → 转成 `PageData[T]`，并用 `item_model.model_validate` 逐条转换（响应模型即出参模型，不做二次转换）。
- `apply_sort`：`sort_by or default_sort`；都没有则原样返回；非法字段/方向抛 `InvalidParamError`（`42200`，HTTP 422）。
- 所有函数有类型标注；通用件不 import 任何具体模型（`item_model` 由调用方传入）。

## 5. 使用约定（S2-5 起）

```python
NOTE_SORT_FIELDS = {"created_at": Note.created_at, "updated_at": Note.updated_at}

@router.get("/notes", response_model=Envelope[PageData[NoteOut]])
def list_notes(
    params: PageParams = Depends(page_params),
    sorting: SortParams = Depends(sort_params),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[NoteOut]]:
    stmt = select(Note).where(Note.user_id == current_user.id, Note.deleted_at.is_(None))
    stmt = apply_sort(stmt, sort_by=sorting.sort_by, order=sorting.order,
                      allowed=NOTE_SORT_FIELDS, default_sort="created_at")
    return Envelope(trace_id=get_trace_id(), data=paginate_query(session, stmt, params, item_model=NoteOut))
```

- 列表查询必须显式 `where(user_id == 已授权学生)`（S2-3 规则），分页件不负责鉴权。
- `allowed` 只能用真实列对象，禁止字符串拼接。

## 6. 测试（20 条）

测试用 SQLite 内存库（`sqlite://`）建一张测试专用 `pagination_demo` 表（5 行），不连 PostgreSQL。

### 6.1 `tests/test_pagination.py`（单元，12 条）

1. `PageParams()` 默认 1 / 20
2. `page_params(2, 10)` 返回 `PageParams(page=2, page_size=10)`
3. 第一页 `page=1, page_size=2` → 2 条、total=5、page=1、page_size=2
4. 第二页 → 剩余 2 条（id 3、4）
5. 超出末页 → `items=[]`、`total=5`、不抛异常
6. `item_model=DemoOut` → items 全是 `DemoOut` 实例
7. `apply_sort` 升序 → 执行顺序正确
8. `apply_sort` 降序 → 执行顺序正确
9. 非白名单字段 → `InvalidParamError`，`code=42200`，message 含「不支持的排序字段」
10. 非法方向 `sideways` → `InvalidParamError`
11. `sort_by=None` 且无 `default_sort` → 不改写语句（编译后无 ORDER BY）
12. `sort_by=None` + `default_sort="id"` → 使用默认字段

### 6.2 `tests/test_pagination_api.py`（接口，8 条）

夹具：测试内 `FastAPI` 应用挂 `GET /demos`，`get_db` 覆盖为 SQLite Session；`response_model=Envelope[PageData[DemoOut]]`。

1. 默认请求 → 200，`data` 键恰为 `{items,total,page,page_size}`（无 `pages`/`size`）
2. `page=2&page_size=2` → 2 条且 id 正确
3. `page=0` → 422 + `42200`
4. `page_size=101` → 422 + `42200`
5. `sort_by=unknown` → 422 + `42200`，message 含「不支持的排序字段」
6. `order=sideways` → 422 + `42200`
7. `sort_by=name&order=asc` → 按 name 升序
8. `total` 不随分页变化（两次不同页都返回 5）

## 7. 验收

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_pagination.py tests/test_pagination_api.py -q   # 20 passed
../.venv/Scripts/python.exe -m pytest -q                                                         # 基线 260 + 20 = 280
```

- 本卡无生产列表接口，**没有 curl 证据**；笔记/错题/题目三个列表接入后（S2-5、S4），由那些卡补真实 curl。
- 复用验收：S2-5 笔记列表必须使用 `page_params` + `paginate_query` + `apply_sort`，不出现手写 `limit/offset` 或字符串 `order_by`；S4 同。

## 8. 已知限制（写进 PROGRESS / D-024）

- `total` 依赖 count 查询：大表深分页时 count 与 offset 都会变慢（当前数据量小；量大后改 keyset/cursor）。
- 无 `pages`、无 `links`、无多字段排序。
- `page_size` 上限 100 是经验值，后续如有批量导出需求另开接口。
- SQLite 只用于测试分页逻辑，不保证与 PostgreSQL 的执行计划一致；真实 SQL 形态由 S2-5 的 curl 验收覆盖。

## 9. 文档同步

| 文档 | 改动 |
|---|---|
| `API.md` | §0 分页/排序两行定稿（参数表、响应形状、错误码） |
| `AGENTS.md` | §9.2 增「列表接口统一分页件」；§9.6 增分页锚点 |
| `DECISIONS.md` | 新增 D-024 |
| `PROGRESS.md` | S2-4 打勾、当前状态、变更日志、遗留（深分页、多字段排序） |
| `requirements.txt` | 新增 `fastapi-pagination==0.16.1` |
| `SCHEMA.md` | 不改 |

## 10. 自检

- [x] 任务卡产出 `schemas/common.py`、`utils/pagination.py` → §4
- [x] 统一 `{items,total,page,page_size}` → §3.2 / §6
- [x] 排序字段白名单（防注入）→ §3.3 / §4 / §6.1-9
- [x] 筛选显式参数 → §2.2 / §3.3
- [x] 不手写分页 SQL → §2.3-1 / §4
- [x] 三个列表接口复用 → §5 / §7（S2-5、S4 接入时验收）
- [x] 新依赖已获用户批准 → §2.1
- [x] 无 TBD 留给实施者