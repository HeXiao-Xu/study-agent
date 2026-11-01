# S3-8 前端问答页（流式 + 引用跳转）Spec

- 日期：2026-11-02
- 任务卡：`docs/AI协作开发实施计划.md` §S3-8
- 相关契约：`docs/API.md` §5、`docs/SCHEMA.md` §7
- 状态：待用户确认后进入 plan

## 1. 背景与目标

S3-5/S3-6/S3-7 已完成问答后端：SSE 事件为 `meta → delta* → done/error`，回答在生成与引用校验完成后才发 `delta`；S3-7 增加 `done.cached` 与管理端用量。前端 `/qa` 仍是 `ComingSoonView`，用户无法实际使用，更没有引用跳转。

S3-8 目标：

1. 学生能在 `/qa` 选择学科/笔记本/时间范围，连续提问并实时看到 Markdown + KaTeX 回答。
2. 回答附引用卡片，点击后跳到只读笔记详情并定位/高亮引用片段。
3. 会话可新建、切换、重命名、删除；刷新后能恢复当前会话与消息。
4. 拒答、缓存命中、生成失败都有明确且不误导的 UI 状态。

## 2. 范围

### 2.1 包含

- 后端补齐会话读取/管理契约（现有后端没有列表、回放、改名、删除接口）。
- 前端 `api/`、`types/`、`utils/`、`views/qa/`、`components/qa/`、只读笔记页。
- 路由、导航、前端单测、后端 service/API 测试、真实联调验收。
- API.md 契约更新；不涉及数据库表结构变更。

### 2.2 不包含

- 不新增第三方依赖；复用 `md-editor-v3` 的 `MdPreview` 与 KaTeX。
- 不做语音、图片提问、流式 token 级后端改造。
- 不做会话标题的 AI 摘要；沿用 S3-5 首问 50 字自动标题，允许手动改名。
- 不把 `refusal_reason`/`suggestions` 落库；历史拒答只能恢复样式与固定建议，不能恢复当时的准确原因。
- 不做多用户共享会话、导出、全文搜索会话。
- 不实现 429 限流；沿用 S3-7 的调用日志。

## 3. 后端契约

所有接口使用统一响应壳 `{code,message,trace_id,data}`；权限均为 `student` 且仅能访问 `Conversation.user_id == current_user.id` 的会话。不存在与越权统一 `404/40400`，不泄露目标是否存在。

### 3.1 `GET /api/v1/qa/conversations`

- 入参：`limit` 可选，默认 50，范围 1–100。
- 出参：`Envelope[QaConversationOut[]]`，按最近消息时间倒序（无消息用 `created_at`），同时间按 `id` 倒序。
- `QaConversationOut`：

```json
{
  "id": "12",
  "title": "错位相减法怎么用？",
  "scope": {
    "subject_id": 1,
    "folder": "数列",
    "start_date": "2026-01-01",
    "end_date": null
  },
  "created_at": "2026-11-02T10:00:00+00:00",
  "last_message_at": "2026-11-02T10:00:08+00:00",
  "message_count": 2
}
```

- `id` 用字符串（与 `POST /qa/ask` 的 `conversation_id` 一致，避免 BIGINT 前端精度问题）。
- `title`：`conversations.title` 去空白；为空时回退第一条 user 消息前 50 字；仍为空则 `"新对话"`。
- `scope`：`conversations.scope_json`，非法/空为 `null`。
- `last_message_at`：该会话最新消息时间；无消息为 `null`。
- `message_count`：user + assistant 消息总数。

### 3.2 `GET /api/v1/qa/conversations/{id}/messages`

- 入参：路径 `id` 为正整数。
- 出参：`Envelope[QaConversationDetailOut]`：

```json
{
  "conversation": { "...": "同 QaConversationOut" },
  "messages": [
    {
      "id": 30,
      "role": "user",
      "content_md": "错位相减法怎么用？",
      "created_at": "2026-11-02T10:00:00+00:00",
      "refused": false,
      "citations": []
    },
    {
      "id": 31,
      "role": "assistant",
      "content_md": "错位相减用于……[1]",
      "created_at": "2026-11-02T10:00:08+00:00",
      "refused": false,
      "citations": [
        {
          "index": 1,
          "note_id": 55,
          "chunk_id": 255,
          "title": "数列笔记",
          "heading_path": "数列/错位相减法",
          "page_no": null,
          "snippet": "错位相减用于……",
          "score": 0.91,
          "note_available": true
        }
      ]
    }
  ]
}
```

- 消息按 `id` 升序；只返回 `role in ('user','assistant')`。
- 引用按 `rank,id` 升序；`index = rank`（`rank` 为空时用 0）。
- `title`/`heading_path` 从 `notes`/`note_chunks` 左连接；笔记软删或切片已删时字段可为 `null`。
- `note_available=false` 表示笔记已软删或不存在，前端不提供跳转。
- `refused = role=='assistant' and content_md.strip() == REFUSAL_TEXT`；不新增字段。
- 不对消息正文做改写或截断。

### 3.3 `PATCH /api/v1/qa/conversations/{id}`

- 入参：`{"title": "新标题"}`；trim 后 1–80 字，空白串 422/42200。
- 出参：`Envelope[QaConversationOut]`（更新后的 summary）。
- 只改 `title`，不改 `scope_json`；不重新生成标题。

### 3.4 `DELETE /api/v1/qa/conversations/{id}`

- 出参：`204` 无响应体。
- 物理删除会话；依赖 `messages.conversation_id ON DELETE CASCADE` 与 `message_citations.message_id ON DELETE CASCADE` 清空消息与引用。
- 不存在/越权 404/40400。

### 3.5 现有接口保持不变

`POST /qa/ask`、`GET /qa/messages/{id}/citations` 的请求/响应不变；`done.cached`、拒答字段继续使用 S3-6/S3-7 契约。S3-8 只读消费，不改生成链路。

## 4. 后端实现

### 4.1 模块

- `backend/app/schemas/qa.py`：新增 `QaConversationOut`、`QaConversationRename`、`QaConversationDetailOut`、`QaHistoryMessageOut`、`QaHistoryCitationOut`。
- `backend/app/services/qa_service.py`：新增 `list_conversations`、`get_conversation_detail`、`rename_conversation`、`delete_conversation`，复用 `_find_conversation`、`_stored_scope`。
- `backend/app/api/v1/qa.py`：新增 4 个路由；路由只做参数校验、service 调用、`Envelope` 组装。

### 4.2 查询约束

- 列表一次聚合查询：`conversations LEFT JOIN messages`，`count/max` + 关联子查询取首条 user 消息；禁止按会话 N+1。
- 详情先按 owner 查会话（1 条），再一次查消息（1 条），再一次按 `message_id IN (...)` 查引用并左连接 `notes/note_chunks`（1 条）；禁止逐消息查引用。
- 所有查询显式 `Conversation.user_id == user_id`；引用查询经由本人会话的消息 id 集合约束。
- 删除在同一事务内 `session.delete(conversation)` + commit；由数据库级联，不在 Python 循环删消息。

## 5. 前端架构

### 5.1 文件

| 文件 | 职责 |
|---|---|
| `web/src/types/qa.ts` | 会话/消息/引用/SSE/scope 类型 |
| `web/src/api/qa.ts` | 会话 CRUD + `fetch` SSE 请求 |
| `web/src/utils/sse.ts` | SSE 字节流切帧与 `event/data` 解析 |
| `web/src/utils/typewriter.ts` | 非阻塞打字机队列 |
| `web/src/utils/highlight.ts` | 只读页文本高亮与标题定位 |
| `web/src/views/qa/Chat.vue` | 页面状态、会话侧栏、消息区、输入区 |
| `web/src/components/qa/ChatMessage.vue` | 单条消息、Markdown、拒答样式、建议 |
| `web/src/components/qa/CitationCard.vue` | 引用卡片与跳转 |
| `web/src/views/notes/NoteReadView.vue` | 只读笔记 + 引用片段定位 |
| `web/src/router/index.ts` | `/qa` 真实页、`/notes/:id` 只读页 |

### 5.2 状态

`Chat.vue` 维护：

- `conversations: QaConversation[]`、`activeId: string | null`
- `messages: QaUiMessage[]`，其中 `QaUiMessage` 额外含 `localId`、`streaming`、`error`、`done`
- `scope`：`{subjectId: number|null, folder: string, dateRange: [string,string] | null}`
- `streaming`、`loadingMessages`、`loadingConversations`、`listError`
- `AbortController` 每个请求一个；切换/新建/删除当前会话时 abort。

### 5.3 发送状态机

1. 校验问题非空、未在流式中、避免重复提交。
2. 本地追加 user 消息（临时 `localId`）和 assistant 占位。
3. `fetch POST /qa/ask`，携带 Bearer token、问题、scope、当前 `activeId`。
4. 收到 `meta`：设置 `conversation_id`、user message id、引用；若 URL 没有会话参数则 `router.replace({query:{conversation:id}})`。
5. 收到 `delta`：把 `text` 推入打字机队列；队列按固定节奏更新 assistant `content_md`。
6. 收到 `done`：记录 `message_id`、tokens、latency、refused、refusal_reason、suggestions、cached；等队列排空后结束 `streaming`，刷新会话列表。
7. 收到 `error` 或网络错误：保留 user 消息，assistant 显示错误态；`AbortError` 静默清理占位。
8. 流未收到 `done` 就结束：视为协议错误，显示错误，不把半截回答当成功。

SSE 解析必须支持：空行分帧、`\r\n`、多行 `data:`、注释行、UTF-8 跨 chunk 解码。HTTP 非 2xx 先按 JSON 壳取 `message`，不是 SSE。

### 5.4 打字机

- 以 16ms 定时器按块揭示（约每帧 12–20 字符），不阻塞主线程。
- `done` 先到达时，队列继续排空；队列为空才把 `streaming` 置 false。
- 切换会话、取消请求、组件卸载时清定时器并丢弃队列。
- 不使用 `setTimeout` 递归阻塞式渲染；Markdown 只随可见文本更新。

### 5.5 引用跳转与只读页

- `CitationCard` 展示：序号、笔记标题、`heading_path`、页码（有则显示）、片段。
- 点击：`router.push({name:'note-read', params:{id:note_id}, query:{snippet, heading, page, chunk}})`。
- `note_available=false` 时禁用点击并提示“原笔记已删除”。
- `NoteReadView` 调 `getNote(id)`，用 `MdPreview` 渲染 `content_md`；`nextTick` 后：
  1. 在 DOM 文本中做空白归一化匹配 `snippet`，支持跨文本节点，把命中区间用 `<mark class="citation-hit">` 包起来并滚动到首个命中。
  2. 匹配失败时按 `heading_path` 最后一段找标题元素并滚动；顶部展示“引用片段”提示，明确“未能精确定位”，不伪装成功。
- 只读页提供“编辑”按钮跳 `/notes/:id/edit`；不自动保存、不触发草稿。

### 5.6 scope

- 学科：`listSubjects()` 下拉，提交 `subject_id`。
- 笔记本：文本框，trim 后提交 `folder`；不新增文件夹接口。
- 时间：`el-date-picker` 日期范围，提交 `start_date/end_date`（YYYY-MM-DD）。
- 新会话创建时由后端保存 scope；重开会话用 `conversation.scope` 回填。
- 前端保证 `end_date >= start_date`；非法时阻止提交并提示。

### 5.7 路由/权限

- `/qa` 的 `meta.roles = ['student']`；教师/家长访问走现有 403。
- `/notes/:id(\\d+)` 命名为 `note-read`，登录用户可读（笔记详情权限由后端 `GET /notes/{id}` 决定）。
- 导航文案保持“智能问答”。

## 6. 测试计划

### 6.1 后端

- `test_qa_conversations.py`（service）：
  - 列表只含本人会话、按最近消息排序、标题回退、scope 回填；
  - 详情按 id 升序返回消息；引用批量组装、`note_available` 正确；
  - 重命名 trim/空白校验；越权/不存在 404；
  - 删除只删本人会话。
- `test_qa_conversations_api.py`：
  - 列表 200 + 结构；`limit` 非法 422；
  - 详情 200；越权 404；
  - PATCH 200；空白标题 422；DELETE 204；
  - 非 student 403。
- 现有 QA 测试全部回归。

### 6.2 前端

- `sse.spec.ts`：多帧、多行 data、CRLF、跨 chunk UTF-8、坏 JSON。
- `typewriter.spec.ts`：按块揭示、done 后继续排空、reset 丢弃。
- `highlight.spec.ts`：单节点/跨节点/空白归一化/未命中返回 false。
- `CitationCard.spec.ts`：字段渲染、点击 push、note_available=false 禁用。
- `ChatMessage.spec.ts`：Markdown 容器、拒答样式、suggestions、错误态。
- `Chat.spec.ts`：加载会话、发送流、meta/delta/done、错误、切换会话、重命名、删除、scope 载荷。
- `NoteReadView.spec.ts`：加载笔记、查询参数高亮、无匹配回退提示、编辑跳转。

## 7. 真实验收

1. 真实登录学生 `test1`，打开 `/qa`，问 10 轮（含至少 1 个拒答、1 个缓存命中、1 个多轮追问）。
2. 记录每轮：首字时间、结束时间、tokens、`cached`、是否落库；确认流式不卡 UI、答案 Markdown/公式正常。
3. 点击至少 3 条不同笔记引用：落到只读页，片段高亮/章节滚动正确；删除一条引用笔记后点击应提示不可用（可用临时笔记验证）。
4. 刷新页面：URL 带会话 id，消息与引用恢复；切换历史会话正常。
5. 重命名后刷新仍保留；删除当前会话后回到新会话，列表减少，消息级联清除。
6. 后端全量 `pytest`、前端 `vitest run`、`npm run build` 全绿；实际数字写回 PROGRESS/DECISIONS。

## 8. 风险与已知限制

- 历史拒答的 `refusal_reason`/`suggestions` 未落库，刷新后只能显示固定建议；实时回答不受影响。
- `message_citations` 不保存 `heading_path/title`，历史回放依赖 `note_chunks/notes` 左连接；切片重建或笔记删除后可能缺失，UI 必须容忍。
- 引用跳转依赖片段文本匹配；公式/强排版导致匹配失败时只能定位章节并展示片段，不能保证像素级高亮。
- 会话列表固定最多 50 条，无分页；超出后旧会话不显示，后续需要再加分页。
- 打字机是前端展示节奏，不改变后端“先生成后发块”的首字延迟。
- 切换会话会 abort 当前 SSE；后端保留 user 消息、不落 assistant，历史里会看到未回答的问题。
- 前端无 E2E 浏览器自动化依赖；真实验收以手工界面路径 + 单元测试 + build 为准，若环境具备浏览器自动化再补。

## 9. 实施记录（2026-11-02）

- 交付与 spec 一致：4 个会话接口、会话回放、只读 `/notes/:id`、SSE 流解析、打字机、引用卡片、scope、拒答样式、会话切换/改名/删除；无新增依赖、无迁移、无 SCHEMA 变更。
- 测试：后端 **735 passed, 1 warning**（+16）；前端 **114 passed / 29 files**（+29）；build 0（仅 775KB chunk 警告）。
- 真实 10 轮（真实 Postgres/Redis/DashScope）：总耗时 93.7s、tokens 22,092、首字 1.590–34.627s；缓存命中 248ms，拒答 2.868s；20 条消息/30 条引用/1 条拒答；列表 22 条，改名 200，临时删除 204→404/40400。
- 真实 Chrome（headless + CDP）：`/notes/55` 与 `/notes/49` 均命中 `mark.citation-hit`，无回退；刷新恢复 22 条消息/32 条引用；UI 新建→改名→删除临时会话成功；教师 `/qa` → `/403`。
- 与 spec 的差异（已由用户确认的 plan 内实现调整）：① 含 LaTeX 的片段先尝试原始文本，再尝试去公式/仅非公式行，命中正文而非整段回退；② 标注时机从 `nextTick` 改为 `on-html-changed` 后 80ms 去抖，修复“预览未完成时标注导致段落丢失”；③ 测试用 PreviewStub 在 mounted 时触发 `onHtmlChanged`，与真实事件路径一致。
- 仍存在的限制：会话列表有界 50 条；历史拒答原因/建议不恢复；公式/强排版可能退化为章节定位；删除物理级联不可恢复；CI 无 E2E 依赖，本轮用本机 Chrome CDP。