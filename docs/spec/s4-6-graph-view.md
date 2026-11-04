# S4-6 图谱可视化前端 —— 设计 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S4-6「图谱可视化前端」
- 前置依赖：S4-5（图谱关系构建 + 人工校验）已交付并 merge 到 `main`（`cd3f7ce`）
- 分支：`feature/s4-6-graph-view`
- 状态：设计已与用户逐节确认（2026-11-04），随后落 plan 再写码

## 1. 背景与目标

S4-5 已经把知识图谱的**数据**做出来了：学科 7（高中数学）108 个知识点、357 条边（approved 264 / pending 50 / rejected 43）。但数据只以表格形式出现在知识库页的「图谱关系」tab 里，给老师审核用，学生看不到、也看不出结构。

本卡要交付**图谱可视化页**：力导向图一眼看出章节结构与前置关系，点节点看详情（描述、前置、相关笔记、错题），支持按模块折叠、搜索定位，节点规模过大时降级为子图。

目标（可验收）：
1. 打开 `/graph` 首屏 **<3s**，108 节点 + 264 条 approved 边流畅拖拽缩放。
2. 点「导数与函数的单调性」能看到**前置节点**与**关联笔记**（笔记为空时如实显示空态）。
3. 四类关系（`contains`/`prerequisite`/`related`/`confusable`）样式可区分，前置有方向。

## 2. 范围

**做**：
- 后端 2 个只读接口：`GET /kp/graph/snapshot`、`GET /kp/graph/nodes/{kp_id}`。
- 前端新路由 `/graph` + 侧栏第 08 项「图谱」+ `views/kp/Graph.vue` + `useGraphData.ts`（纯函数）+ `api/graph.ts` + `types/graph.ts`。
- 新增前端依赖 `echarts`（按需引入 `echarts/core` + `GraphChart` + `CanvasRenderer` + `TooltipComponent`）。
- 组件测试（纯函数 + 页面）+ 后端接口测试。

**不做**（明确留给后续）：
- **真实掌握度配色**：掌握度模型是 S4-7。本卡用「当前用户在此知识点下的错题数」做临时热力，页面角落标注「临时指标，S4-7 换真实掌握度」，**不伪装成掌握度**。
- 图谱编辑（增/删/改边）：只能在「图谱关系」tab 审核，本页只读。
- 节点描述补全：`knowledge_points.description` 目前 108/108 为 NULL，本卡只做空态，**不用 LLM 编描述**（§6 禁止假数据）。
- 导出图片、3D、时间轴、跨学科切换（先按当前 subject 一次一个）。

## 3. 契约变更（先改契约再写码）

本卡**无数据库变更**（无迁移、`alembic heads` 仍 `0012_s4_5`），只有 API 与前端依赖变化。

### 3.1 API.md 新增两条（并入 §4.5 知识图谱）

#### GET /api/v1/kp/graph/snapshot
- 权限：**任意登录用户**（登录即可；图谱结构不是隐私数据）
- 入参：`subject_id`（必填，int ≥1）
- 出参：`Envelope[GraphSnapshotOut]`

```json
{
  "subject": {"id": 7, "name": "高中数学"},
  "nodes": [
    {"id": 12, "name": "导数与函数的单调性", "level": 3, "parent_id": 9,
     "exam_weight": 0.800, "mistake_count": 2}
  ],
  "edges": [
    {"src_kp_id": 3, "dst_kp_id": 12, "relation": "prerequisite", "weight": 0.950}
  ],
  "stats": {
    "nodes": 108, "edges": 264, "pending_edges": 50,
    "by_relation": {"contains": 107, "prerequisite": 114, "related": 4, "confusable": 39}
  }
}
```

- `edges` **只含 `review_status='approved'`**（S4-5 口径：人工通过才算数，未校验的不给学生看）。
- `stats.pending_edges` 给老师一个「还有 N 条待校验」的提示入口，但**不返回 pending 边本身**。
- `mistake_count` 口径：`mistakes(user_id=当前用户) → questions → question_kps` 去重计数，`status` 不限；老师/管理员也是**本人**口径（不越权统计学生）。
- 错误：`401/40100`、`404/40400`（学科不存在）、`422/42200`。

#### GET /api/v1/kp/graph/nodes/{kp_id}
- 权限：任意登录用户
- 入参：路径参数 `kp_id`
- 出参：`Envelope[GraphNodeDetailOut]`

```json
{
  "id": 12, "name": "导数与函数的单调性", "level": 3, "parent_id": 9, "subject_id": 7,
  "path": ["高中数学", "导数及其应用", "导数的概念与运算"],
  "description": null, "exam_weight": 0.800, "mistake_count": 2,
  "prerequisites": [{"kp_id": 3, "name": "函数的单调性", "weight": 0.950}],
  "successors":    [{"kp_id": 19, "name": "函数的极值与最值", "weight": 0.950}],
  "related": [], "confusable": [],
  "notes": [{"id": 5, "title": "导数单调性整理", "updated_at": "2026-11-03T10:00:00Z"}],
  "mistakes": [{"id": 9, "question_id": 33, "status": "unmastered",
                "created_at": "2026-11-02T09:00:00Z", "stem": "已知函数 f(x)=…"}]
}
```

- `path`：根 → 该节点的 `name` 数组（面包屑；含主体名本身）。
- 四类邻居**只取 approved**；`prerequisite` 里该节点是 `dst`（`prerequisites`）或 `src`（`successors`）。
- `notes`：`note_kps.confirmed=true` 且 `notes.deleted_at IS NULL` 且 `notes.user_id=当前用户`；按 `updated_at DESC`，最多 20 条。
- `mistakes`：当前用户在该知识点下的错题，按 `created_at DESC` 最多 20 条；`stem` 为 `questions.stem_md` 前 60 字。
- 错误：`401/40100`、`404/40400`（知识点不存在）、`422/42200`。

### 3.2 前端依赖

`web/package.json` 增加 `echarts`（按需引入，不引全量包）。**这是本卡唯一的新增依赖，已经用户确认**（见 §11）。

## 4. 后端设计

`services/graph_service.py` 增两个只读用例，沿用「一个用例一个事务、只读不提交」：

```python
def snapshot(session, *, subject_id: int) -> GraphSnapshotOut
def node_detail(session, *, kp_id: int, user_id: int) -> GraphNodeDetailOut
```

- `snapshot`：1 次 nodes 查询 + 1 次 approved 边查询 + 1 次 `by_relation` 聚合 + 1 次 pending 计数 + 1 次错题计数（`GROUP BY kp_id`）。**5 条 SQL，无 N+1**。
- `node_detail`：节点 + 祖先链（沿 `parent_id` 安全上溯，守卫 10 层）+ 四类邻居（1 条 SQL，按 `src/dst` 分流）+ 笔记 + 错题（各 1 条，均带 `user_id` 过滤）。
- `schema` 放 `app/schemas/kp.py`：`GraphSnapshotOut`/`GraphSnapshotNode`/`GraphSnapshotEdge`/`GraphSnapshotStats`/`GraphNodeDetailOut`/`GraphNeighborOut`/`GraphNoteBrief`/`GraphMistakeBrief`。
- 路由放 `app/api/v1/kp.py`，每条 ≤30 行。**注意注册顺序**：`/graph/snapshot` 与 `/graph/nodes/{kp_id}` 与既有 `/graph/edges` 系列不冲突（前缀不同），无需特殊排序。

## 5. 前端设计

### 5.1 文件

| 文件 | 职责 |
|---|---|
| `web/src/types/graph.ts` | 快照/详情的 TS 类型 |
| `web/src/api/graph.ts` | `fetchGraphSnapshot(subjectId)`、`fetchGraphNode(kpId)` |
| `web/src/views/kp/useGraphData.ts` | **纯函数**：颜色/大小/边样式/章归属/模块过滤/降级子图/搜索匹配/ECharts option 组装 |
| `web/src/views/kp/Graph.vue` | 页面：ECharts 画布 + 顶部工具栏 + 右侧 `el-drawer` |
| `web/src/router/index.ts` | `path: 'graph'`，`name: 'graph'`，`meta.title: '图谱'` |
| `web/src/layouts/nav.ts` | 第 08 项 `{ index: '08', label: '图谱', name: 'graph', path: '/graph' }` |

### 5.2 视觉映射

| 元素 | 规则 |
|---|---|
| 节点大小 | `8 + 22 × clamp(exam_weight, 0, 1)` → 8–30px |
| 节点颜色（**临时热力**） | 错题 0 → `#9aa4b2`（灰蓝）；1–2 → `#f0b429`（琥珀）；≥3 → `#e5484d`（红） |
| `contains` | 灰 `#cfd6e0` 细实线，无箭头，默认**隐藏**（父子关系已由章折叠表达；工具栏可开） |
| `prerequisite` | 蓝 `#3b82f6` 实线 + 终点箭头（src=前置 → dst=后继） |
| `related` | 绿 `#22c55e` 虚线 |
| `confusable` | 橙 `#f59e0b` 点线 |
| 标签 | 默认显示，`fontSize: 10`，`labelLayout.hideOverlap: true` 自动避让 |
| 布局 | `layout: 'force'`，`roam: true`、`draggable: true`、`repulsion: 220`、`gravity: 0.06`、`edgeLength`：contains 40 / 其它 90 |
| 图例 | 顶部四项 checkbox，同时承担「边类型说明 + 开关」 |

### 5.3 交互

- **点节点**：`chart.on('click', params => dataType==='node')` → 打开右侧抽屉，按需请求 `nodes/{id}`（带 loading 与错误提示）。
- **抽屉内容**：面包屑 → 名称/层级/考纲权重/我的错题数 → 描述（空态「暂无描述」）→ 前置/后继/相关/易混（各分组，可点击跳转到该节点并高亮）→ 关联笔记（空态「暂无关联笔记」）→ 错题列表（空态「暂无错题」，有则显示状态 + 时间 + 题干摘要）。
- **模块折叠**：顶部「模块」多选（level-2 章名），只影响渲染集合，不改后端数据；被折叠节点上的边一并隐藏。
- **搜索定位**：输入框 + 下拉匹配（`el-select filterable` 或 `el-autocomplete`）→ 选中后：若所在章被折叠则自动展开 → `dispatchAction({type:'highlight'})` → 打开抽屉。**不强制居中**（力导向下强行居中会打断用户视角，且坐标不稳定）。
- **重建入口**：工具栏右侧「刷新」重新拉快照；老师/管理员额外显示「还有 N 条待校验」链接跳到知识库页「图谱关系」tab（`stats.pending_edges>0` 时）。

### 5.4 降级（>300 节点）

- 快照 `nodes.length > 300` 时进入**子图模式**：初始只渲染「搜索/选中的节点 + 一跳邻居」，顶部横幅「节点过多（N 个），已降级为子图模式」+ 「显示全部（可能卡顿）」按钮。
- 未选中任何节点时，子图模式默认取错题数最多的节点作为焦点（保证首次打开不是空白）。
- 当前 108 节点不触发；降级分支靠单测覆盖 + 真机把阈值临时改成 20 验证一次（验证完改回，写进证据文档）。

### 5.5 性能

- 首屏 2 次请求：快照（~30KB）+ 学科列表（已有）；ECharts canvas 渲染 108 节点 + 264 边 <1s。
- `notMerge: false` 增量 `setOption`，切换模块/图例不重建实例；`dispose` 在 `onBeforeUnmount`。
- 抽屉详情按需请求，不预取 108 个节点的详情。

## 6. 测试

**后端**（`tests/test_graph_snapshot.py`、`tests/test_graph_node_detail.py`）：
- 快照只返回 approved 边；pending 只进 `stats.pending_edges`。
- `by_relation` 与 nodes 数一致；空学科返回空数组（不报错）。
- `mistake_count` 按用户隔离（另一个用户的错题不计入）。
- 详情：节点不存在 404；面包屑层级正确；四类邻居只取 approved；笔记过滤 `confirmed=true` + 未删除 + 本人；错题按本人过滤 + 截断 60 字；无关联时返回空数组（不是 null）。
- 权限：未登录 401；学生可访问（与 S4-5 的审核接口不同）。

**前端**（`useGraphData.spec.ts`、`Graph.spec.ts`）：
- 颜色三档边界（0/1/2/3）；大小 clamp（负值、>1）。
- 边样式映射四类；`contains` 默认不构建进 option，开关打开后构建。
- 章归属（level-2 祖先）与模块过滤（折叠后边不残留）。
- 降级：301 节点 → 只留焦点 + 一跳；无焦点时取错题最多者。
- 搜索匹配（大小写、中文子串）。
- 页面：mock `echarts/core`（jsdom 无 canvas）；测空态文案、降级横幅、点节点开抽屉（mock api）、抽屉内跳转。

## 7. 验收口径（真机）

1. `/graph` 首屏 **<3s**（Chrome DevTools Performance：navigation start → 画布出现节点；记录实测值）。
2. 点「导数与函数的单调性」：抽屉出现**前置节点列表**且可点击跳转；关联笔记区显示笔记或**空态文案**（库里只有 2 条 note_kps 关联，若目标节点没有则显示空态，**不补假数据**）。
3. 四类边样式可区分：打开 `contains` 开关后能看到灰色细线；`prerequisite` 有箭头；`related` 虚线；`confusable` 点线。
4. 模块折叠勾掉「解析几何」，该章节点与其边消失，其它章不受影响。
5. 搜索「导数」能定位并高亮，抽屉打开。
6. 降级模式：临时把阈值改 20，确认横幅与子图渲染，再改回 300（证据文档记录这一次临时改动）。
7. 学生账号与老师账号都能打开（权限差异只在「待校验」提示）。

## 8. 风险与已知限制

- **掌握度是临时指标**：用错题密度上色，与 S4-7 的真实掌握度不是一回事；页面必须标注，避免答辩时被问「颜色代表什么」答错。
- **108 个知识点的 `description` 全空**：侧栏描述区恒为空态；若要好看需另开卡片补描述（LLM 生成或人工写）。
- **笔记关联极少**（`note_kps` 仅 2 条）：图谱的「关联笔记」价值在本卡很难演示，属于数据量问题而非功能问题。
- **力导向布局不稳定**：每次打开位置不同（ECharts 未固定随机种子）。答辩演示前建议先刷新一次再讲；不做「记住上次布局」（本卡范围外）。
- **`contains` 默认隐藏**：卡片要求「边样式区分关系类型」，四类样式都实现了，但 `contains` 默认关（107 条树边会把力导向拉成放射状）；开关可开，图例里说明。
- **无浏览器 E2E**：仓库无 Playwright（§2.1），前端只到组件测试 + 手动真机验收；`<3s` 由人工计时记录。
- **echarts 体积**：按需引入后 gzip ≈120KB，构建体积会增加；`npm run build` 的 chunk 警告已存在（>500KB），不额外优化。

## 9. 文档同步

- `docs/API.md` §4.5 追加两条接口（含 `mistake_count` 口径与「只返回 approved」说明）。
- `docs/SCHEMA.md` **不改**（无表结构变更），但在 §3.2 旁注明「图谱读取接口只读，掌握度待 S4-7」。
- `docs/PROGRESS.md` 更新 S4-6 状态、真机数字、后端/前端测试基线。
- `docs/DECISIONS.md` 新增 D-049：临时热力指标、`contains` 默认隐藏、降级阈值 300、依赖选型、力导向不固定布局。
- `README.md` 启动段补 `/graph` 入口说明。
- `.sdd/s4-6/acceptance-evidence.md` + `progress.md`。

## 10. 交付物清单

- [ ] `backend/app/services/graph_service.py`（+2 用例）
- [ ] `backend/app/schemas/kp.py`（+8 模型）
- [ ] `backend/app/api/v1/kp.py`（+2 路由）
- [ ] `backend/tests/test_graph_snapshot.py`、`backend/tests/test_graph_node_detail.py`
- [ ] `web/package.json`（+echarts）
- [ ] `web/src/types/graph.ts`、`web/src/api/graph.ts`
- [ ] `web/src/views/kp/useGraphData.ts`、`web/src/views/kp/Graph.vue`
- [ ] `web/src/views/kp/useGraphData.spec.ts`、`web/src/views/kp/Graph.spec.ts`
- [ ] `web/src/router/index.ts`、`web/src/layouts/nav.ts`（+相关测试）
- [ ] 文档五件套 + `.sdd/s4-6/` 证据

## 11. 已确认决策（用户，2026-11-04）

1. 渲染库：**echarts 按需引入**（新依赖，已确认）。
2. 颜色：**先用错题密度做临时热力**，页面标注「S4-7 换真实掌握度」。
3. 侧栏空内容：**如实空态 + 空态文案**，不造假数据。
4. 入口：**新路由 `/graph` + 侧栏第 08 项「图谱」**。
5. 接口：**新增 2 个只读接口**（snapshot / node detail），不在前端拼装分页。
6. 边可见性：**只显示 approved**；pending 只在老师视角提示条数。