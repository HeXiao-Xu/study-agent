# S2-14 前端知识点树管理 — 设计 Spec

- 日期：2026-10-30
- 状态：待用户复核
- 上游：S2-9 知识点树 CRUD/导入、S2-10 知识点对齐与待确认队列、S2-11 应用壳与路由、S2-13 页面模式
- 下游：S3 问答按知识点过滤、S4 错题诊断与知识图谱
- 任务卡原文：`views/kp/Tree.vue`、`views/kp/PendingAlign.vue`；树用 `el-tree`，支持搜索、拖拽排序、增删改；待确认队列做成“左内容右候选知识点”的确认卡片，支持键盘快捷确认
- 验收：能新增/改名/移动知识点；待确认卡片连续确认 20 条不卡顿

## 1. 目标

把 `/knowledge` 从占位页替换成知识库工作台：

1. 学生可以浏览知识点树、搜索节点、查看知识点详情字段。
2. 教师/管理员可以新增根节点/子节点、改名、改描述/权重、拖拽跨级移动与同级排序、删除叶子节点。
3. 学生可以处理自己笔记的待确认对齐：左侧看笔记摘要，右侧看候选知识点，逐条确认或忽略。
4. 待确认队列支持键盘操作，连续处理 20 条时页面不冻结、不重复提交、不残留旧卡。
5. 学生只读、教师/管理员可编辑；教师/管理员登录后能直接进入知识库，不被 `/notes` 的 403 拦住。

## 2. 非目标

- 不做知识点批量导入 UI、导出、版本历史、撤销/重做。
- 不做待确认的“全部确认/全部忽略”按钮；一次只处理一张卡。
- 不做笔记正文与候选知识点的逐字对照、差异高亮；只显示 300 字摘要。
- 不做知识点图谱可视化、`knowledge_edges` 编辑（S4-5）。
- 不做跨学科拖拽；前端选择学科，后端仍校验同 subject。
- 不新增数据库迁移；`note_excerpt` 是只读派生字段。
- 不新增第三方依赖；继续使用 Element Plus `el-tree`、`el-dialog`、`el-card`。
- 不做移动端适配；沿用全局 `body min-width:1024px`。

## 3. 已确认决策

| # | 决策 | 选择 |
|---|---|---|
| 1 | CRUD 权限 | 只有 `admin/teacher` 可写；`student` 只读。验收临时创建 teacher，测完删除 |
| 2 | 页面结构 | 一个 `/knowledge` 页，顶部两个 tab：知识点树 / 待确认对齐 |
| 3 | 卡片左侧内容 | 后端 `PendingAlignOut` 增加 `note_excerpt`（300 字摘要），不额外请求笔记详情 |
| 4 | 待确认交互 | 一次一张；确认/忽略后自动显示下一条；`Enter` 确认、`Backspace` 忽略 |
| 5 | 拖拽范围 | 跨级移动 + 同级排序；根节点锁定，不能拖动/删除 |
| 6 | 拖拽落库 | 新增 `PUT /api/v1/kp/order`，一次请求原子完成移动/排序 |
| 7 | 登录落点 | 教师/管理员无显式 redirect 时默认 `/knowledge`；学生仍 `/notes` |
| 8 | 搜索 | 前端本地过滤名称/编码，展开命中路径；不新增后端搜索接口 |

## 4. 后端契约

### 4.1 现有接口保持不变

以下接口的权限、字段、错误语义不变，S2-14 前端直接复用：

- `GET /api/v1/kp/subjects`
- `GET /api/v1/kp/tree?subject=math`
- `POST /api/v1/kp`
- `PATCH /api/v1/kp/{kp_id}`
- `DELETE /api/v1/kp/{kp_id}`
- `GET /api/v1/kp/align/pending`
- `POST /api/v1/kp/align/confirm`
- `POST /api/v1/kp/align/reject`

`GET /kp/tree` 仍一次查询同 subject 全部节点、内存组树；树节点按 `level, order_no, id` 排序。`PATCH /kp/{id}` 仍用于改名/描述/权重和普通父级修改；拖拽统一走新接口。

### 4.2 `PUT /api/v1/kp/order`

- 权限：`admin` / `teacher`（其他角色 403/40300）。
- 类型：同步，单事务。
- 入参：

  ```json
  {
    "parent_id": 12,
    "ordered_ids": [34, 35, 36],
    "moved_id": 34
  }
  ```

  - `parent_id`：必填，目标父节点 id；`null` 表示根级。
  - `ordered_ids`：1–200 个，目标父级下**完整的**子节点 id 列表，必须包含 `moved_id`（如果传）。
  - `moved_id`：可选；传了表示把该节点移动到 `parent_id` 下，再按列表写 `order_no`；不传只做同级排序。
- 成功：**204** 无响应体。
- 语义：
  1. 一次性加载目标父节点、被移动节点、`ordered_ids` 对应节点和同 subject 节点。
  2. 校验父节点存在且同 subject；`moved_id` 不能等于 `parent_id`，不能移入自身后代。
  3. 移动时按现有规则重算 `level`，校验移动后子树高度 ≤4，并 BFS 重算后代 `level`。
  4. 校验 `ordered_ids` 无重复、全部同 subject、正好等于移动后目标父级的完整子节点集合；否则 422。
  5. 按 `ordered_ids` 顺序写 `order_no = index`；若发生跨父级移动，源父级剩余子节点也归一化为连续 `order_no`。
  6. 全部修改在同一个事务提交；失败回滚。
- 错误：
  - `404/40400`：父节点/被移动节点/列表中的节点不存在。
  - `422/42200`：`ordered_ids` 为空/重复/与目标兄弟集合不一致、跨学科、成环、层级超 4、`moved_id` 不在列表。
  - `403/40300`：非教师/管理员。

### 4.3 `PendingAlignOut.note_excerpt`

在现有字段后增加：

- `note_excerpt: str`：只读派生值，来自 `notes.content_text`。
- 生成规则：`content_text.strip()` 后取前 300 个字符；超过 300 时追加 `…`；空文本返回空字符串。
- 保留原始换行；前端用 `white-space: pre-wrap` 展示。
- 不新增数据库列，不返回完整正文，不改变现有分页/筛选/排序。
- 权限、`note_id` 过滤、`note_id DESC, kp_id` 排序保持 S2-10 现状。

### 4.4 服务与路由改动

- `schemas/kp.py` 增加 `KpOrderIn`。
- `services/kp_service.py` 增加 `reorder_children(session, *, parent_id, ordered_ids, moved_id=None) -> None`：
  - 复用模块内 `_subtree_height` / `_reassign_descendant_levels` 的树规则；
  - 加载节点禁止循环查库；
  - 失败抛 `NotFoundError` / `InvalidParamError`，不吞异常。
- `api/v1/kp.py` 增加 `PUT /order` 路由，只做参数校验、调用 service、返回 204。
- `schemas/kp_align.py` 增加 `note_excerpt` 字段与截断校验；`services/kp_align_service.list_pending` 的查询保持一次分页查询，不额外逐条查库。
- 不改现有 `POST/PATCH/DELETE /kp` 的入参和错误语义。

### 4.5 API 文档同步

`docs/API.md` §4：

- 增加 `PUT /api/v1/kp/order` 的权限、入参、语义和错误；
- `PendingAlignOut` 示例增加 `note_excerpt`；
- 注明 `note_excerpt` 是 300 字摘要，不是完整正文。

`SCHEMA.md` 不改：没有新表/新列/新索引。

## 5. 前端结构

### 5.1 文件

| 文件 | 职责 |
|---|---|
| `web/src/types/kp.ts` | `KpNode`、`KpTree`、`KpCreate`、`KpUpdate`、`KpOrderIn`、`PendingAlign`、`AlignPair`、`AlignBatchResult` |
| `web/src/api/kp.ts` | 在 `listSubjects` 基础上增加 `getKpTree`、`createKp`、`updateKp`、`deleteKp`、`reorderKp`、`listPendingAlign`、`confirmAlign`、`rejectAlign` |
| `web/src/views/kp/KnowledgeView.vue` | 页面壳、tab、学科选择、加载 subjects、角色判断 |
| `web/src/views/kp/Tree.vue` | el-tree、搜索、CRUD 入口、拖拽排序 |
| `web/src/views/kp/PendingAlign.vue` | 单卡待确认队列、确认/忽略、键盘提示、空态 |
| `web/src/components/kp/KpNodeDialog.vue` | 新增/编辑知识点表单 |
| `web/src/views/kp/treeUtils.ts` | 查找节点、同级 id、拖拽目标父级/顺序等纯函数 |
| `web/src/views/kp/usePendingAlign.ts` | 队列加载、当前卡、确认/忽略、下一条、错误状态 |
| `web/src/router/index.ts` | `/knowledge` 改真实页面，`meta: { title:'知识库', nav:'knowledge' }`；不限制角色 |
| `web/src/utils/redirect.ts` | 增加按角色默认落点；保留 `safeRedirect` 原有行为 |
| `web/src/views/LoginView.vue` | 无显式 redirect 时按角色选择 `/notes` 或 `/knowledge` |

### 5.2 类型与 API 封装

```ts
export interface KpNode {
  id: number
  subject_id: number
  parent_id: number | null
  name: string
  code: string
  level: number
  description: string | null
  exam_weight: number | null
  order_no: number
  children: KpNode[]
}

export interface KpTree {
  subject: SubjectOut
  nodes: KpNode[]
}

export interface KpOrderIn {
  parent_id: number | null
  ordered_ids: number[]
  moved_id?: number
}
```

- `reorderKp` 发送 `PUT /kp/order`，成功无返回；失败由 `http.ts` 统一提示。
- 列表/详情错误不重复弹窗；组件只处理局部 loading/empty/error 状态。
- `PendingAlign` 类型包含 `note_excerpt`。

### 5.3 页面壳与角色

- `KnowledgeView` 挂载时 `listSubjects()`；没有学科显示空态，不伪造数据。
- 学科下拉选择 `code`；默认第一个学科（当前为 `math`）。切换学科重新加载树。
- tab：
  - `tree`：默认；
  - `pending`：进入时加载待确认队列。
- `canManage = auth.user?.role === 'admin' || auth.user?.role === 'teacher'`。
- 学生只读：树没有新增/编辑/删除按钮，节点不可拖拽，页面显示“只读：教师或管理员可编辑知识点”。
- 教师/管理员：显示编辑工具条；待确认 tab 仍只显示自己的笔记（S2-10 权限不变）。

### 5.4 树页面

- `el-tree`：
  - `node-key="id"`、`:data="tree.nodes"`、`default-expanded-keys` 默认展开根节点；
  - 节点模板显示名称、编码、层级/权重辅助信息；
  - 教师/管理员节点悬浮操作：新增子节点、编辑、删除；根节点只显示新增子节点/编辑，不显示删除，不能拖动；
  - 学生不渲染操作区，不启用 `draggable`。
- 搜索：
  - 输入框绑定关键词；
  - `filter-node-method` 匹配 `name` 或 `code`，大小写不敏感；
  - 有条词时展开命中路径；清空后恢复默认展开。
- 新增/编辑：
  - `KpNodeDialog` 表单字段：父节点（只读展示）、名称、编码（新增可填、编辑只读）、描述、权重（0–1）；
  - 前端校验与 Pydantic 保持一致：名称 1–100、编码 1–50、描述 ≤500、权重 0–1；
  - 新增子节点时提交 `parent_id`；新增根节点 `parent_id=null`；`order_no` 默认追加到同级末尾；
  - 编辑只提交 `name/description/exam_weight`，不提交 `code/subject_id`；
  - 成功后关闭弹窗、刷新树并保留展开状态。
- 删除：
  - 二次确认后调用 `DELETE /kp/{id}`；
  - 后端 409（有子节点/被笔记引用/被关系引用）由 `http.ts` 展示 message；组件刷新树，不重复弹错；
  - 删除成功后刷新树。
- 拖拽：
  - `draggable`、`allow-drag`、`allow-drop`、`node-drop`；
  - 根节点 `parent_id === null` 禁止拖动；`allow-drop` 禁止拖到根节点的前/后，禁止把节点拖入 level 4 节点；
  - `node-drop` 后从 Element Tree 当前节点关系计算：
    - 目标父级 id（`inner` 为 drop 节点，`before/after` 为 drop 节点的父级）；
    - 目标父级当前子节点顺序（含被拖动节点）；
    - `moved_id`；
  - 调用 `reorderKp({ parent_id, ordered_ids, moved_id })`；
  - 成功/失败都重新加载树，以服务端顺序为准；失败保留后端错误提示；
  - 拖拽请求期间显示 loading 并阻止重复拖拽。

### 5.5 待确认页面

- 进入 tab 或切换学科后加载 `GET /kp/align/pending?page=1&page_size=20`。
- 状态：
  - `queue: PendingAlign[]`；
  - `current = queue[0]`；
  - `total` 来自分页响应；
  - `busy` 防止重复提交；
  - `error` 局部加载错误。
- 卡片：
  - 左侧：笔记标题、`note_excerpt`（`pre-wrap`，最多 300 字摘要）；
  - 右侧：候选知识点名称、编码、置信度百分比；
  - 顶部显示“第 N 条 / 共 M 条”或“剩余 N 条”；
  - 操作按钮：确认、忽略；
  - 键盘提示：`Enter 确认`、`Backspace 忽略`。
- 操作：
  - 调用 `POST /kp/align/confirm` 或 `/reject`，一次一对；
  - 成功后从本地队列移除当前卡，不整页刷新；
  - `confirmed=0` 或 `skipped>0` 视为状态已变化，提示并重新加载队列；
  - 队列为空时重新拉取第一页；没有数据则显示空态；
  - 失败不盲目前进，保留当前卡并允许重试。
- 键盘：
  - 仅在待确认 tab、无弹窗、无输入焦点、非 busy 时监听 `window.keydown`；
  - `Enter` 确认，`Backspace` 忽略；调用 `preventDefault`；
  - `Escape` 不处理；
  - 输入框、文本域、可编辑元素、Element Plus 弹窗内不触发。
- 性能：
  - 队列一次取 20 条，操作只移除当前项，不重新渲染整表；
  - 连续 20 条确认不累积定时器/监听器；
  - 离开 tab 或卸载时移除键盘监听。

### 5.6 登录落点

- `utils/redirect.ts` 增加按角色的默认路径：

  ```ts
  export function defaultRedirectForRole(role: UserRole): string {
    return role === 'teacher' || role === 'admin' ? '/knowledge' : DEFAULT_REDIRECT
  }
  ```

- `safeRedirect(raw, fallback = DEFAULT_REDIRECT)` 保留原有拒绝开放重定向的规则；非法/缺省时返回 fallback。
- `LoginView` 登录成功后：
  - 有合法 `redirect`：仍按原逻辑回跳；
  - 没有/非法：教师/管理员去 `/knowledge`，学生去 `/notes`。
- 这是为了让教师能直接进入 S2-14 页面，不改变学生和家长的现有落点。

## 6. 数据流

```text
KnowledgeView
  ├─ listSubjects → subject select
  ├─ Tree
  │   ├─ getKpTree(subject) → el-tree
  │   ├─ dialog → createKp / updateKp → refresh tree
  │   ├─ delete → deleteKp → refresh tree
  │   └─ drop → reorderKp → refresh tree
  └─ PendingAlign
      ├─ listPendingAlign(page_size=20) → queue
      ├─ confirmAlign(pair) → remove current / refill
      └─ rejectAlign(pair) → remove current / refill
```

- 所有接口通过 `src/api/kp.ts`，组件不直接使用 axios。
- 树是服务端顺序的唯一真相；拖拽成功后必须重新加载。
- 待确认队列以本地队列为主，操作成功后移除；空队列/异常时重新拉取。

## 7. 错误与边界

| 场景 | 行为 |
|---|---|
| subjects 为空 | 树区域空态“暂无学科数据”，不显示假树 |
| tree 加载失败 | 错误条 + 重试；保留页面壳 |
| 非教师/管理员尝试写接口 | 后端 403；前端本应隐藏入口，若出现则统一错误提示 |
| 新增 code 重复 | 409 message 直接展示；弹窗不关闭，允许修改 |
| 删除被引用节点 | 409 message 直接展示；树刷新但不删除 |
| 拖拽非法（成环/超 4 级/跨学科） | 422 message 展示；重新加载树恢复服务端顺序 |
| `ordered_ids` 与目标兄弟不一致 | 422；前端重新加载树 |
| pending 为空 | 空态“暂无待确认对齐” |
| pending 加载失败 | 错误条 + 重试 |
| 确认/忽略返回 skipped | 提示状态已变化并重新加载，不前进到错误数据 |
| 连续按 Enter | busy 锁只发一次；下一张渲染后才允许下一次 |
| 输入搜索/弹窗时按 Enter/Backspace | 不触发确认/忽略 |

## 8. 测试计划

### 8.1 后端

- `test_kp_service.py`
  - 同级排序按 `ordered_ids` 写连续 `order_no`；
  - 跨父级移动更新 `parent_id/level` 并重算后代 level；
  - `ordered_ids` 重复/缺少兄弟/包含他父节点 → 422；
  - 移入自身后代 → 422；超 4 级 → 422；
  - 父节点不存在 → 404。
- `test_kp_api.py`
  - `PUT /kp/order` 教师 204；
  - 学生/匿名 403/401；
  - 非法 body 422；
  - 确认 `parent_id=null` 根级排序可用。
- `test_align_api.py` / `test_align_service.py`
  - `note_excerpt` 正常截断 300 字；
  - 短文本不加省略号；空文本为空串；
  - 现有 pending 字段、分页、排序不回归。
- 不新增真实 LLM/DB 依赖；沿用 FakeSession/monkeypatch。

### 8.2 前端

- `treeUtils.spec.ts`：查找节点、同级 id、drop 目标父级/顺序、根节点保护。
- `KnowledgeView.spec.ts`：教师显示编辑入口、学生不显示；tab 切换；subjects 加载；错误/空态。
- `KpNodeDialog.spec.ts`：新增必填校验、编辑不提交 code、权重范围。
- `Tree.spec.ts`：搜索过滤、创建/编辑/删除调用、拖拽调用 `reorderKp` 参数、失败重载。
- `usePendingAlign.spec.ts`：加载 20 条、确认后移除并显示下一条、skipped 重新加载、busy 防重复。
- `PendingAlign.spec.ts`：Enter 确认、Backspace 忽略、输入框内不触发、空态。
- `redirect.spec.ts` / `LoginView.spec.ts`：教师默认 `/knowledge`、学生默认 `/notes`、显式 redirect 优先、开放重定向仍被拒绝。

### 8.3 真实联调

1. 临时创建 `teacher` 账号（验收后删除），登录落到 `/knowledge`。
2. 新增一个子节点 → 改名 → 改描述/权重 → 同级拖拽 → 跨级拖拽 → 删除：
   - 每一步刷新后顺序/父子关系保持；
   - 删除有子节点/被引用节点时出现 409 文案。
3. 用 student 登录 `/knowledge`：
   - 树可浏览/搜索，无编辑按钮、不可拖拽；
   - 待确认 tab 可见。
4. 准备 20 条临时待确认数据（真实 `note_kps` 行，验收后删除）：
   - 连续按 Enter 20 次，队列从 20 到 0；
   - 每次只发一次请求，不重复确认；页面无冻结、无旧卡残留；
   - 剩余条数/空态正确。
5. 检查 console error 0、1440×900 无横向溢出、键盘不劫持输入框。
6. 清理临时用户、知识点、笔记/待确认行；不清理用户真实数据。

## 9. 验收标准

- [x] `/knowledge` 不再是占位页。
- [x] 学生只能读树；教师/管理员能新增、改名、移动、删除。
- [x] 拖拽跨级/同级后刷新，顺序和父子关系与操作一致。
- [x] 待确认卡片左侧有 300 字摘要，右侧有候选知识点/置信度。
- [x] Enter/Backspace 可连续处理；20 条连续确认无卡死、无重复请求。
- [x] 教师/管理员无 redirect 登录后进入 `/knowledge`，不出现 `/notes` 403。
- [x] `pytest` 全绿、Vitest 全绿、`npm run build` 通过。
- [x] API.md/DECISIONS/PROGRESS/实施计划/spec/plan 执行记录同步。

## 10. 已知限制

- 树搜索是当前已加载学科的前端过滤，不做跨学科/全文搜索。
- 待确认只展示摘要，不能看完整笔记；确认后不提供撤销。
- 待确认一次一对请求，没有批量确认；20 条可接受但不适合上千条。
- 根节点锁定只在前端；后端仍按通用节点规则处理。
- 拖拽失败依赖重新加载恢复，不做前端乐观回滚动画。
- 没有拖拽撤销、操作历史、并发编辑冲突提示。
- 教师账号目前需手工创建/临时创建，注册页只创建学生（沿用 S2-2）。

## 11. 执行记录（2026-10-30）

- 后端：新增 `KpOrderIn`、`kp_service.reorder_children`、`PUT /api/v1/kp/order`；`PendingAlignOut.note_excerpt` 300 字截断。新增 12 条测试，pytest **524 passed, 1 warning**。
- 前端：新增知识点树工具/表单/树页/待确认队列/页面壳与路由；教师/管理员默认 `/knowledge`。新增 26 条测试，Vitest **82 passed / 19 files**，build 退出 0。
- 真实浏览器（1440×900，CDP DOM + 资源计数）：teacher 登录落 `/knowledge`；新增/改名/跨级拖拽/删除/搜索通过，跨级后 DB `parent_id=117, level=3`；20 条真实待确认按 Enter，confirm 资源 20 次、DB 20 行 `manual+confirmed`、队列无旧卡；Backspace 忽略 1 条；student 登录落 `/notes`，`/knowledge` 只读、0 个可拖拽节点、待确认空态；关键流程 console error 0，两 tab `scrollWidth=innerWidth=1418`。
- 实测偏离：① Element Plus `dragend` 先移除源节点，`dragging.parent` 不可靠，改为从 `dropNode` 的 `childNodes` 取目标兄弟全集（已补测试）；② `KpNodeDialog` 测试因 ElDialog teleport 使用 `ElDialog` stub，产品代码不变；③ Element 树回调参数按 `FilterValue`/`TreeNodeData` 对齐类型。
- 清理：21 条临时笔记 + 21 条 `note_kps` + 2 个临时用户 + 全部 `S214%` 知识点删除，临时残留 0；学科 7 仍 108 知识点，原有 3 条笔记/1 个用户保留。
- 已知限制：搜索仅当前学科前端过滤；无批量确认/撤销/历史/冲突提示；根节点锁定仅前端；待确认一次一对；<1024 视口沿用全局横向滚动（遗留 48）；截图未做人工像素级目视，布局结论来自 DOM 断言。

- 后续补丁（2026-10-30）：教师/管理员点「笔记」「文件」显示「暂不支持查看」占位（`StudentOnlyView`），不跳 403；学生页面不变，前端全量 85 passed / 20 files。
