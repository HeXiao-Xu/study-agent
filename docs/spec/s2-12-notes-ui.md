# S2-12 前端笔记列表与编辑器 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-12
- 日期：2026-10-27
- 状态：设计已逐节确认（图片补最小后端 / md-editor-v3 + KaTeX / 本地草稿 / 关键词+学科+排序+分页 / 直接进编辑页）
- 上游：S2-11 应用壳与登录、S2-5 笔记 CRUD、S2-6 文件上传、S2-8 解析状态、S2-10 知识点对齐
- 下游：S2-13 文件与解析状态、S2-14 知识点树、S3 问答引用笔记
- 产物：笔记列表/编辑页、Markdown 编辑器、本地草稿、图片取图契约、Vitest/pytest 用例

## 1. 目标

1. 把 S2-11 的“笔记”占位页换成可用列表：搜索、学科筛选、排序、分页、新建、编辑、删除。
2. 交付 Markdown 编辑页：标题/学科/标签、公式预览、图片插入、保存、快捷键。
3. 用本地草稿 + 离开拦截解决“写一半丢了”的问题，同时不因频繁自动保存刷爆后端对齐任务。
4. 解决图片“能传不能取”的契约缺口：正文存稳定 token，渲染时用鉴权 blob，刷新后仍能显示。
5. 建立前端笔记模块的可测试边界：列表查询逻辑、草稿、图片替换为纯函数/组合式函数单测；编辑器真实渲染交给 Chrome 联调。

## 2. 范围

### 2.1 做

**后端（最小改动，仅图片展示所需）**

- `POST /api/v1/files` 增加 `parse` query 参数（默认 `true`）；`parse=false` 仅接受图片，新记录直接 `done/100`，不入队解析。
- 新增 `GET /api/v1/files/{file_id}/image`：本人或已绑定家长/教师可读，返回图片字节。
- `file_service.upload_file(..., parse: bool)`、`file_service.read_image(...)`。
- 对应 pytest、API.md §3 更新；无迁移。

**前端**

- `src/types/notes.ts`、`src/types/files.ts`、`src/api/notes.ts`、`src/api/files.ts`、`src/api/kp.ts`。
- `src/views/notes/NoteListView.vue`、`NoteEditView.vue`、`useNoteList.ts`、`useNoteEditor.ts`。
- `src/components/notes/{NoteTable,TagInput,MarkdownEditor}.vue`（按需拆分）。
- `src/utils/noteDraft.ts`、`src/utils/noteImages.ts`。
- 路由 `/notes`、`/notes/new`、`/notes/:id/edit`；`RouteMeta.nav`；侧栏 active 按 `meta.nav`；面包屑显示所属模块。
- 运行时依赖：`md-editor-v3@7.1.0`、`katex@0.19.1`（用户 2026-10-27 确认）；编辑器与 KaTeX 样式懒加载。
- Vitest 新增约 20 条；既有 17 条保持全绿。

### 2.2 不做

- 不做笔记阅读页、文件夹 UI、标签筛选、创建时间范围筛选、版本历史、回收站、协同编辑。
- 不做服务端自动保存、草稿跨设备同步、冲突合并（只做“服务器版本更新则丢弃旧草稿”）。
- 不做移动端、深色模式、图片压缩/裁剪/水印、图床、公开桶、文件列表管理。
- 不做知识点对齐状态展示；保存后的 `kp.align` 仍由后端自动入队。
- 不改 `NoteOut/NoteSummary` 字段、不动 `notes` 表结构、不新增迁移。
- 不把 `md-editor-v3` 用于公开内容渲染（本卡只有登录后的编辑页）。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 列表用表格，不用卡片流 | 研究工具需要快速扫标题/学科/更新时间；NoteSummary 无正文，卡片只能放空摘要 |
| 2 | 行点击直接进 `/notes/:id/edit`，不做阅读页 | 任务卡只有 List/Edit；个人工具“打开即改”最省点击 |
| 3 | 本地草稿（800ms 防抖）+ 手动保存 | 每次 PATCH 都会触发 `kp.align`，服务端自动保存会产生任务噪音与半成品笔记 |
| 4 | 图片正文存 `note-file://<id>`，渲染时换鉴权 blob | 预签名 URL 会过期；静态 URL 又需要公开桶；token 稳定且不泄露存储地址 |
| 5 | 新增 `GET /files/{id}/image`，而不是暴露 MinIO URL | 权限与 `parse-status` 一致，浏览器不需要知道对象键/endpoint |
| 6 | 编辑器图片上传走 `POST /files?parse=false` | 图片不需要文档解析；避免每张插图产生一个失败任务 |
| 7 | `md-editor-v3` + `katex`，路由懒加载 | 任务卡指定；工具栏/分栏预览/粘贴上传现成，首屏不引编辑器包 |
| 8 | 列表筛选：关键词 + 学科 + 排序 + 分页 | 后端均已支持；标签/时间是低频需求，首版不堆控件 |
| 9 | 查询状态同步 URL query | 刷新/后退保留筛选与页码，便于连续整理笔记 |
| 10 | 标签用可创建的多选，学科用下拉，folder 不做 UI | 标签是笔记的主要组织方式；folder 当前无列表/筛选价值 |
| 11 | 图片加载失败的 token 保留并提示 | 保存时绝不因一次网络失败丢引用 |
| 12 | 不把 md-editor-v3 拖进 jsdom 单测 | CodeMirror 依赖真实布局/选区；用 stub 测封装逻辑，真实渲染走 CDP |

## 4. 信息架构与路由

| 路径 | name | 组件 | meta |
|---|---|---|---|
| `/notes` | `notes` | `NoteListView` | `title: 笔记`、`nav: notes`、`roles: ['student']` |
| `/notes/new` | `note-new` | `NoteEditView` | `title: 新建笔记`、`nav: notes`、`roles: ['student']` |
| `/notes/:id/edit` | `note-edit` | `NoteEditView` | `title: 编辑笔记`、`nav: notes`、`roles: ['student']` |

- `RouteMeta` 增加 `nav?: string`。
- `SideNav` 的 active 判定：`route.meta.nav ?? route.name`；`aria-current` 同步。
- `TopBar` 面包屑：若 `meta.nav` 存在，显示“所属模块 / 当前标题”，模块可点回 `/notes`；否则沿用“首页 / 当前标题”。
- 编辑页返回按钮 `router.push('/notes')`；若 dirty，走离开确认。
- 列表与编辑页都要求 student；教师/家长不进入工作区（其 API 读取能力不变）。

### 4.1 URL query

列表状态：

| key | 值 | 默认 |
|---|---|---|
| `q` | 关键词，1–100 | 空 |
| `subject_id` | 学科 id | 空（全部） |
| `sort` | `updated` / `created` / `title` | `updated` |
| `page` | ≥1 | 1 |
| `page_size` | 10 / 20 / 50 | 10 |

映射到 API：`updated → sort_by=updated_at&order=desc`、`created → created_at&desc`、`title → title&asc`。
非法/越界 query 回落到默认值并 `router.replace` 规范化，不把错误参数发给后端。

## 5. 笔记列表

### 5.1 结构

- 页头 `PageHeader`：标题“笔记”、说明“按主题整理，保存后自动对齐知识点”、右侧主按钮“新建笔记”。
- 筛选条（卡片内一行）：
  - 关键词 `el-input`，placeholder“搜索标题或正文”，clearable，300ms 防抖。
  - 学科 `el-select`，clearable，选项来自 `GET /kp/subjects`，显示 `name`。
  - 排序 `el-select`：最近更新 / 最近创建 / 标题 A–Z。
- 表格：
  - 标题列（可点击整行；标题超长省略，hover title 全文）。
  - 学科（名称，空显示“未分类”）。
  - 标签（最多展示 3 个 + `+N`）。
  - 更新时间（`YYYY-MM-DD HH:mm`）。
  - 操作：编辑 / 删除；`@click.stop` 防止触发行跳转。
- 分页：右下；`layout="total, sizes, prev, pager, next"`；page size 变化回第 1 页。
- 空态：
  - 无任何笔记：“还没有笔记”“写第一篇笔记”按钮。
  - 有筛选但 0 条：“没有匹配的笔记”+“清空筛选”。
- 加载：`v-loading` 覆盖表格；请求失败显示内联错误 + “重试”，不清空旧数据。
- 删除：`ElMessageBox.confirm` 显示标题；成功 toast；若当前页删空且 page>1，先 `page-1` 再请求。

### 5.2 查询与竞态

- `useNoteList` 负责 query 读写、请求、`loading/error/items/total`。
- 每次请求带递增 `requestId`，只有最新响应落地，避免快速输入时旧结果覆盖新结果。
- 关键词防抖 300ms；`q` 为空时删除 query key。
- 筛选变化重置 `page=1`；翻页不重置筛选。
- 学科列表加载失败：toast 一次，筛选下拉只剩“全部学科”，不影响笔记列表。

## 6. 编辑页、保存与草稿

### 6.1 布局

```text
← 笔记                                      已保存 · 14:32     [保存]
[标题输入（大号无边框，1–200 字）]
学科 [下拉]   标签 [多选 allow-create]
┌────────────────────────┬────────────────────────┐
│ md-editor 编辑区        │ 实时预览（KaTeX）       │
└────────────────────────┴────────────────────────┘
```

- 编辑区高度：`calc(100vh - 顶栏 - 头部 - 元信息 - 留白)`，最小 420px；页面不出现横向滚动。
- 标题输入 `aria-label="笔记标题"`，`maxlength=200`，显示剩余字数可省略。
- 标签 `TagInput`：`el-select multiple filterable allow-create default-first-option`；提交前 trim、去重、空值丢弃；单个 ≤30、总数 ≤20；超限就地提示。
- 学科可清空（`clearable`），提交 `null` 表示未分类。

### 6.2 加载

- `GET /notes/{id}`；404 显示“笔记不存在”，403 显示“无权访问”，均带“返回笔记列表”。
- 加载成功：建立快照 `{title, content_md, subject_id, tags}` 作为 dirty 基线。
- 新建页：空标题/正文/学科/标签，基线为空。
- 编辑器与图片解析完成前显示 loading，不让用户对着空白编辑。

### 6.3 保存

- 新建 `POST /notes`；编辑 `PATCH /notes/{id}`。
- PATCH 只提交相对基线变化的字段；无变化时点保存直接 toast“没有需要保存的修改”，不发请求。
- 校验：标题 trim 后非空且 ≤200；正文 trim 后非空且 ≤200000；标签规则；否则就地提示，不请求。
- 成功后：
  - 用响应更新基线、`noteId`、`updated_at`；
  - 新建时 `router.replace({ name: 'note-edit', params: { id } })`；
  - 清本地草稿；
  - toast“已保存”，状态回“已保存 HH:mm”。
- 失败：保留 dirty 与正文，状态“保存失败”，按钮恢复可用；401 由全局拦截器处理。
- 快捷键 `Ctrl/Cmd + S`：阻止浏览器默认，调用保存；输入法组合中不触发。
- 保存中按钮 loading、禁用重复提交；此时禁止离开路由。

### 6.4 本地草稿

- key：`study-agent:note-draft:v1:new` 或 `study-agent:note-draft:v1:<note_id>`。
- 值：

```json
{"title":"...","content_md":"...","subject_id":7,"tags":["函数"],"draftSavedAt":"2026-10-27T02:00:00.000Z","baseUpdatedAt":"2026-10-27T01:50:00+00:00"}
```

- 编辑后 800ms 防抖写入；标题/正文/学科/标签全空时删除草稿，不写空草稿。
- 状态区显示“草稿已保存 HH:mm”。
- 打开时：
  - 无草稿：正常加载。
  - 有草稿且 `baseUpdatedAt` 等于服务器 `updated_at`（新建页草稿的 base 为 null）：弹“恢复本地草稿？”；`showClose=false`，只有“恢复”“丢弃”两个出口。
  - 有草稿但服务器 `updated_at` 已变（与 base 不一致）：删草稿 + toast“服务器版本已更新，已丢弃旧草稿”。
- 恢复：用草稿覆盖表单并标记 dirty；丢弃：删草稿，用服务器版本。
- 保存成功或用户点“丢弃”后 `localStorage.removeItem`。

### 6.5 离开保护

- `onBeforeRouteLeave`：dirty 为真 → `ElMessageBox.confirm("有未保存的修改，已自动保存为本地草稿。仍要离开吗？")`；“离开”放行，“继续编辑”`return false`。
- 保存中：直接阻止并 toast“正在保存，请稍候”。
- `beforeunload`：dirty 时注册；`event.preventDefault()` + `returnValue=''`；保存成功/unmount 移除。
- 新建页点返回、侧栏导航、浏览器后退都经过同一判定。

## 7. 图片契约

### 7.1 后端接口

#### POST /api/v1/files?parse=false

- `parse`：bool，默认 `true`，query 参数。
- 权限、上传校验、去重、大小限制沿用 S2-6。
- `parse=false` 时只接受 `mime` 以 `image/` 开头；否则 `422/42200`“该文件不是图片”。
- 新记录：`parse_status=done`、`parse_progress=100`、`parse_finished_at=now`、`error_msg=NULL`，**不入队**。
- 去重命中：返回已有记录，不改解析状态，不补入队。
- `parse=true`：行为与 S2-6/S2-8 完全一致（默认路径不变）。

#### GET /api/v1/files/{file_id}/image

- 权限：本人，或已绑定该学生的 parent/teacher；admin 不绕过（复用 `get_file_status`）。
- 仅 `mime` 为 `image/*`，否则 `422/42200`“不是图片文件”。
- 成功 `200`：原始字节，`Content-Type` 用记录 MIME，`ETag: "<sha256>"`，`Cache-Control: private, max-age=300`，`X-Content-Type-Options: nosniff`，`Content-Disposition: inline; filename*=UTF-8''<encoded>`。
- 错误：`404/40400`“文件不存在”、`403/40300`“无权访问该资源”、`500/50000`“文件存储不可用”。
- 首版一次性读入内存；图片上限沿用 60MB，记遗留。

### 7.2 前端 token 与 blob

- 正文稳定引用：`![图片](note-file://<file_id>)`。
- `noteImages.ts`：
  - `extractImageIds(md): number[]`：去重。
  - `replaceImageTokens(md, urlById): string`：token → blob URL，未知 id 原样保留。
  - `replaceImageUrls(md, tokenByUrl): string`：blob URL → token；用字符串替换，不拼正则。
  - `stripImageTokens` 不实现，避免误删用户内容。
- 打开笔记：
  1. 提取 id；
  2. 并发 `GET /files/{id}/image`（`responseType='blob'`，30s）；
  3. `URL.createObjectURL`；
  4. 替换后交给编辑器；
  5. 记录 `blobUrl → token`。
  - 单个失败：跳过替换，累计“N 张图片加载失败”，其余正常显示。
- 保存/写草稿：`replaceImageUrls` 换回 token，再提交/落 localStorage。
- 插入：
  1. 校验 `file.type.startsWith('image/')`；
  2. `POST /files?parse=false`（60s）；
  3. 取 blob/object URL；
  4. `onUploadImg(files, callback)` 里 `callback([url])`；
  5. 记录映射。
- 卸载/切换笔记：`revokeObjectURL` 全部释放。
- 外部图片 URL、普通链接不变。

### 7.3 为什么不用预签名 URL

- 预签名有效期 1h，存进 Markdown 后必然过期；
- 每次渲染重新签名仍需把对象 key/URL 暴露给前端；
- 公开桶会把笔记图片变成可枚举资源；
- blob 方案让浏览器只拿字节，鉴权仍由 Bearer token 控制。

## 8. 模块契约

```text
src/types/notes.ts
  NoteSummary {id,title,subject_id,tags,folder,created_at,updated_at}
  NoteOut extends NoteSummary {content_md, source_file_id}
  NoteListParams {q?,subject_id?,sort_by?,order?,page,page_size}
  NotePayload {title,content_md,subject_id,tags}

src/api/notes.ts
  listNotes(params): Promise<PageData<NoteSummary>>
  getNote(id): Promise<NoteOut>
  createNote(payload): Promise<NoteOut>
  updateNote(id, patch): Promise<NoteOut>
  deleteNote(id): Promise<void>

src/api/files.ts
  uploadImage(file): Promise<FileUploadOut>   // parse=false
  getImageBlob(id): Promise<Blob>

src/api/kp.ts
  listSubjects(): Promise<SubjectOut[]>

src/utils/noteDraft.ts
  DraftState、draftKey(noteId|null)、readDraft、writeDraft、clearDraft、isDraftStale

src/utils/noteImages.ts
  extractImageIds、replaceImageTokens、replaceImageUrls

src/views/notes/useNoteList.ts
  state: items,total,page,pageSize,filters,loading,error
  actions: fetch,setFilter,setPage,setPageSize,resetFilters

src/views/notes/useNoteEditor.ts
  state: form,loading,saving,dirty,noteId,statusText
  actions: load,save,restoreDraft,applyDraft,dispose
```

- `useNoteEditor` 不直接弹 ElMessageBox；离开确认放在视图，便于单测状态。
- `MarkdownEditor` props：`modelValue`、`readonly?`、`uploading?`；emit `update:modelValue`、`save`、`upload-error`。
- `TagInput` 用 `v-model:tags`，内部只做规则提示，不替父组件截断。

## 9. 错误与边界

| 场景 | 表现 |
|---|---|
| 列表 401 | 全局拦截器回登录，带 redirect |
| 列表 500/网络 | 表格内错误条 + 重试，保留旧数据 |
| 详情 404/403 | 页内状态 + 返回列表 |
| 保存 422 | 全局 toast + 页内“保存失败”，正文不丢 |
| 保存 401 | 回登录；draft 已在本地，重新登录后可恢复 |
| 图片上传失败 | toast（后端 message），编辑器内容不变 |
| 图片取图失败 | 保留 token，提示 N 张失败；保存不丢 token |
| 标签超限 | 就地提示，不静默截断 |
| 草稿解析失败（坏 JSON） | 删除该 key，按无草稿处理 |
| localStorage 不可用 | try/catch 降级为仅内存，状态提示“草稿不可用” |
| 服务器版本变新 | 丢弃旧草稿，不覆盖 |
| 重复点保存 | saving 锁 + 按钮 loading |

## 10. 测试计划

### 10.1 前端（约 20 条）

| 文件 | 用例 |
|---|---|
| `utils/noteDraft.spec.ts`（4） | 读写 roundtrip；clear；baseUpdatedAt 不一致判陈旧；new/note key 区分 |
| `utils/noteImages.spec.ts`（5） | 提取 id 去重；token→blob；blob→token；未知 URL 保留；多图替换 |
| `views/notes/useNoteList.spec.ts`（3） | query→API 参数；筛选重置 page；非法 query 回落 |
| `views/notes/NoteListView.spec.ts`（4） | 行渲染/空态/删除确认/筛选触发 |
| `views/notes/NoteEditView.spec.ts`（4–5） | 加载详情；新建 POST payload；编辑 PATCH 只带变更；校验失败不发请求；草稿恢复 |

- API、router、MarkdownEditor 全部 mock/stub；不启动真实后端。
- 既有 17 条不回归。

### 10.2 后端（约 6 条）

| 用例 | 断言 |
|---|---|
| parse=false 新图片 | `done/100`、`parse_finished_at` 非空、队列未调用 |
| parse=false 非图片 | 422/42200 |
| parse=true 默认 | 仍 pending + 入队（回归） |
| GET image 成功 | 字节一致、Content-Type、ETag、nosniff |
| GET image 他人 | 403/40300 |
| GET image 非图片/不存在 | 422 / 404 |

### 10.3 真实联调

Chrome headless + CDP，1440×900，真实 Postgres/Redis/MinIO：

1. 注册/登录学生，进 `/notes`。
2. 新建笔记，填标题、正文含 `$$\int_0^1 x^2 dx$$`，通过工具栏上传 PNG。
3. 预览区 `.katex` 存在、`img.naturalWidth > 0`；正文 token 正确。
4. 保存 → URL 变 `/notes/:id/edit`；数据库 `content_md` 含 `note-file://`，不含 `http://127.0.0.1:9000`/`X-Amz`。
5. 刷新 → 公式/图片仍渲染；正文与保存前一致。
6. 改标题不保存 → 等草稿 → 点侧栏 → 离开确认；取消后内容在；再离开确认恢复草稿。
7. 列表搜索/学科筛选/排序/分页/删除。
8. console error 0；无横向滚动。
9. 截图：列表、编辑页（公式+图片）、草稿/离开确认。
10. 清理验收账号、笔记、文件、任务；`users/notes/files` 计数回 0。

## 11. 验收

- 任务卡：写一篇含公式与图片的笔记，保存后重新打开内容一致、公式渲染正确。
- 图片刷新后仍能显示；只验证“上传 201”不算通过。
- 正文无 MinIO endpoint/预签名参数；存的是 `note-file://<id>`。
- 列表筛选、分页、删除可用；空态/错误态不空白。
- `npm run test:run`、`npm run build`、后端 `pytest` 全绿。
- 截图与真实数据留证；不用假成功描述。

## 12. 文档同步

- `docs/API.md` §3：`parse` 参数、`GET /files/{id}/image`、图片状态语义。
- `docs/DECISIONS.md` D-032：编辑器/草稿/图片 token 决策。
- `docs/PROGRESS.md`：当前状态、S2-12 勾选、遗留（草稿本地、图片内存读、无压缩、无阅读页等）。
- `docs/AI协作开发实施计划.md`：S2-12 勾选。
- 本 spec §15、plan 执行记录：commit、测试数、联调结果、偏差。
- `SCHEMA.md` 不改（无迁移）。

## 13. 已知限制

- `note-file://<id>` 写在正文里，脱离本应用（如导出 Markdown 到别的编辑器）会显示 broken image。
- 图片 endpoint 一次性读内存；大图/多图有内存压力；不做压缩/缩略图。
- 草稿只在当前浏览器 localStorage，换设备/清缓存会丢；不处理多标签页并发写。
- 只按 `baseUpdatedAt` 判断陈旧；同一毫秒的并发更新可能漏判。
- 保存失败后不会自动重试；用户需再点保存。
- 编辑器包与 KaTeX 体积大，首次进编辑页需加载懒加载 chunk。
- 教师/家长不能进工作区，其 API 读取能力未做前端入口。
- 删除笔记不删除关联文件/图片（S2-6 遗留）。
- 不做对齐状态、笔记版本、回收站、移动端。

## 14. 后续衔接

- S2-13：文件列表/上传进度/解析状态可复用 `api/files.ts` 与图片 endpoint；文件删除时需检查 `note-file://` 引用。
- S2-14：待确认队列可复用标签/学科下拉与列表空态模式。
- S3：问答引用跳转到笔记时可直接复用 `NoteEditView` 的加载与只读预览能力（届时再拆阅读页）。

## 15. 执行记录

- 实施日期：2026-10-27；spec 提交 `9691a10`，plan 提交 `e334cf2`。
- 代码提交：`1ff82ae`（后端图片契约）、`9bd5033`（API/类型/工具）、`aa1ef6d`（列表/路由/导航）、`4479991`（编辑页/草稿）、`1f232be`（本地时间与新笔记状态）、`58222a0`（清空筛选取消关键词防抖）；文档收尾提交见本次 HEAD。
- 测试：前端 `npm run test:run` **39 passed / 10 files**（新增 22：列表 5、编辑页 5、草稿 4、图片 5、查询 3；既有 17 不回归）；`npm run build` 通过，编辑页 chunk 405 KB / gzip 140 KB。后端 pytest **506 passed**（基线 500 + 6 条图片契约：`parse=false` 成功/非图片、取图成功/越权/非图片/不存在）。
- 真实联调（Chrome 155 headless + CDP，1440×900，真实 Postgres/Redis/MinIO）：
  - 新建“函数单调性验收”，正文含 `# 单调性`、`$$\\int_0^1 x^2 dx$$`；工具栏“图片”下拉 →“上传图片”选 64×64 PNG；预览 `.katex=1`、`img.naturalWidth=64`。
  - 保存 → `/notes/37/edit`；DB `content_md` 为 `...![](note-file://8)`，无 MinIO endpoint / `X-Amz`；文件 `id=8, mime=image/png, parse_status=done, parse_progress=100, parse_finished_at` 有值，`parse.document` 任务 0 条。
  - 刷新 → 标题/公式/图片仍在，图片经 Bearer blob 重新渲染（`naturalWidth=64`）；编辑页无横向滚动（`scrollWidth=innerWidth=1418`）。
  - 草稿：改标题等 1.3s → localStorage `study-agent:note-draft:v1:37` 存在；点侧栏“文件”弹离开确认，取消后内容仍在；再离开回列表；重开弹“恢复草稿”，恢复后标题为草稿值，保存后 key 删除。
  - 列表：12 条默认 10/页 → 第 2 页 2 条；20/页 12 条；关键词“分页验收 11” 1 条；学科“高中数学” 6 条；标题排序 URL `sort=title`；删除确认后 11 条。
  - 取图接口实测 200 + `image/png` + ETag + `nosniff` + `private, max-age=300`；console error 0。
  - 截图：`web/.tmp-screens/*.png`（未入版本库，收尾删除）；验收数据：笔记 12、文件 1、异步任务 13、用户 1、MinIO `uploads/17/...` 全部清理，计数回 0。
- 与 plan 的偏差（均已实测并补测试/记录）：
  1. 新建保存时 `onCreated` 原先在 `saving=true` 内触发，被 `onBeforeRouteLeave` 误判“正在保存”而拦截；改为 `finally` 置 `saving=false` 后回调（`NoteEditView.spec` 抓到）。
  2. 列表更新时间原按 UTC 字符串截断，改为浏览器本地时区格式化。
  3. 新建空白笔记原显示“已保存”，改为“新笔记”。
  4. 列表行点击单测在 jsdom 下不触发 Element Plus 行事件，测试改为对 `ElTable` 发 `row-click`；浏览器真实流程仍用行/编辑按钮验证。
  5. `md-editor-v3` 图片按钮是下拉（“添加链接/上传图片/裁剪上传”），CDP 先点“上传图片”再对隐藏 input 调 `DOM.setFileInputFiles`；裁剪弹窗在 headless 下不可用，未走裁剪路径。
- 未做项：无阅读页、文件夹、标签筛选、版本历史、回收站、移动端、服务端草稿/自动保存、图片压缩/缩略图、删除笔记联动删图；教师/家长无工作区入口。均与 §13 一致。
