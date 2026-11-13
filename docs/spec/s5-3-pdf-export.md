# S5-3 PDF 导出 设计（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §8 S5-3 PDF 导出。
> 契约：`docs/API.md §8`；数据：`docs/SCHEMA.md §6.1`（`papers`，本卡不改表）。
> 前置：S5-2 已交付 `GET /papers/{id}` 与组卷页（保存返回 `id`）。

## 1. 背景与验收拆分

S5-2 的卷子只存在库里（`papers.question_ids` + 卷面顺序），学生拿不到能打印的东西。本卡把「保存好的卷子」渲染成两份 A4 PDF：

- **题干卷**（`variant=questions`）：卷头 + 全部题目 + 答题留白，打印出来直接做题。
- **答案卷**（`variant=answers`）：卷头 + 全部题目 + 答案 + 解析，用于讲评/自批。

验收拆两条路径，都要有实测证据：

1. **正常路径**：真实库挑一份 `ok=true` 的卷（S5-2 已验过「解答 5 题 / 40 分」）→ 保存 → 导出两卷 → `pdfplumber` 抽文字校验中文/公式/页码 → 浏览器点按钮能下载。
2. **失败路径**：不存在的卷 404、别人的卷 403、空卷 409、渲染器异常 500（单测注入 fake 触发）。

## 2. 非目标

- 不做异步导出/任务队列、不缓存 PDF、不落 `files` 表。
- 不做试卷列表/详情页（S5-7）。
- 不改 `papers` 表、不加迁移、不改 S5-2 的 4 个接口。
- 不做 Docker 镜像（仓库还没有 Dockerfile）；只在文档里写明上线要预装 chromium 与中文字体。
- 不做答案卷的「只列答案」变体、不做 A3/双栏/文件夹样式。
- 不引入 Markdown 渲染（题干按纯文本 + KaTeX 公式处理，与前端 `MathText` 口径一致）。

## 3. 文件范围

| 动作 | 文件 |
|---|---|
| 新增 | `backend/app/services/pdf_service.py` |
| 新增 | `backend/app/templates/paper_pdf.html` |
| 新增 | `backend/app/static/katex/`（`katex.min.css`、`katex.min.js`、`contrib/auto-render.min.js`、`fonts/`） |
| 新增 | `backend/tests/test_pdf_service.py`、`backend/tests/test_pdf_api.py` |
| 修改 | `backend/app/api/v1/papers.py`（加 1 个路由） |
| 修改 | `backend/requirements.txt`（`playwright`、`pdfplumber`） |
| 修改 | `web/src/api/papers.ts`、`web/src/api/papers.spec.ts` |
| 修改 | `web/src/views/papers/Generate.vue`、`web/src/views/papers/Generate.spec.ts` |
| 修改 | `docs/API.md §8`、`docs/SCHEMA.md`（仅备注「导出不落库」）、`docs/PROGRESS.md`、`docs/DECISIONS.md`（D-060）、`AGENTS.md §9.6`、`docs/AI协作开发实施计划.md` |

## 4. 读取与内容组装

复用 S5-2 的 `paper_plan_service.get_paper(session, user_id, paper_id)` 拿到 `PaperDetailOut`（含 `items`、`missing_question_ids`、`constraint_json`）。导出只读，不写库、不加查询缓存。

- 空卷判定：`items` 为空 → `ConflictError("试卷没有可导出的题目")`（409/40900）。不回退到「导出空白页」。
- 学科名：取 `items[0].subject_id` 查 `subjects.name` 一次；查不到就省略卷头学科（不让导出失败）。
- 题目顺序：完全按 `detail.items` 的顺序（就是 `papers.question_ids` 的顺序）。
- 缺失题：`missing_question_ids` 里的题在 `items` 里本来就被跳过；导出页脚/卷头不提示缺题（属于库内数据问题，避免学生看到内部状态）。

## 5. 接口契约（写入 `docs/API.md §8`）

### GET /api/v1/papers/{paper_id}/export.pdf

- 权限：student（本人）。
- 查询参数：

  | 参数 | 类型 | 必填 | 默认 | 说明 |
  |---|---|---|---|---|
  | variant | string | 否 | `questions` | `questions`=题干卷；`answers`=答案卷；其他值 422/42200 |

- 成功：`200`，`Content-Type: application/pdf`，`Content-Disposition: attachment; filename="paper-<id>-questions.pdf"; filename*=UTF-8''<编码后的标题>-题干卷.pdf`；响应体为 PDF 字节流（**不套 `Envelope`**，与 `GET /files/{id}/image` 一致）。
- 失败：

  | 场景 | 状态码/业务码 | 说明 |
  |---|---|---|
  | 未登录 | 401 / 40100 | 统一鉴权 |
  | 非本人试卷 | 403 / 40300 | 不泄露存在性 |
  | 试卷不存在 | 404 / 40400 | — |
  | `items` 为空 | 409 / 40900 | 「试卷没有可导出的题目」 |
  | `variant` 非法 | 422 / 42200 | Pydantic 枚举校验 |
  | Playwright/模板异常 | 500 / 50000 | 统一 `PdfRenderError`，日志带 trace_id，不把内部路径/堆栈返回给前端 |

- 同步：Playwright 超时 30 s；失败重试 1 次（仅渲染阶段，鉴权/查询不重试）。
- 文件名：`{title}-题干卷.pdf` / `{title}-答案卷.pdf`；`title` 去掉 `\/:*?"<>|` 与控制字符，最长 80 字，空标题回退 `试卷-{id}`。

## 6. 服务设计（`services/pdf_service.py`）

分四层，前两层纯函数、后两层可注入，便于单测全 mock：

```python
@dataclass(frozen=True, slots=True)
class PdfQuestion:
    number: int                 # 卷面序号，从 1 开始
    qtype: str
    score: int
    difficulty: int
    stem_md: str
    options: tuple[OptionOut, ...]
    answer_md: str | None
    analysis_md: str | None
    blank_lines: int            # 题干卷留白：单选/填空 2，解答按 60mm 用 CSS 块，不用行数

@dataclass(frozen=True, slots=True)
class PdfContext:
    title: str
    subject_name: str | None
    variant: str                # questions | answers
    variant_label: str          # 题干卷 | 答案卷
    total_score: int
    duration_min: int | None
    question_count: int
    questions: tuple[PdfQuestion, ...]
    generated_at: datetime
```

- `build_context(detail, *, variant, subject_name, now) -> PdfContext`：纯函数；空 `items` 抛 `ConflictError`；`variant` 只接受两个枚举值（路由层已校验，这里再防御一次）。
- `render_html(context) -> str`：Jinja2 `Environment(FileSystemLoader(app/templates), autoescape=select_autoescape(["html"]))`；模板里 `{{ ... }}` 全部转义，公式原样保留 `$`；`static` 目录的 `file://` 路径用 `Path(...).as_uri()` 注入 `base_href`。
- `build_header_footer(context) -> tuple[str, str]`：纯函数，产出 Playwright 的页眉/页脚模板字符串（标题做 HTML 转义，页脚含 `.pageNumber`/`.totalPages`）。
- `render_pdf(html_text: str, header_html: str, footer_html: str) -> bytes`：Playwright 同步 API；写临时 HTML 到 `tempfile.TemporaryDirectory()`，`page.goto(file://...)`，`wait_for_function("window.__katexReady === true")`，`page.pdf(format="A4", print_background=True, display_header_footer=True, margin=..., header_template=..., footer_template=...)`；`finally` 关闭 page、退出时清理临时目录。
- `export_pdf(session, *, user_id, paper_id, variant, now=None, renderer: Renderer | None = None) -> tuple[bytes, str]`：读卷 → 学科名 → 建上下文 → 渲 HTML → 页眉页脚 → 调 `renderer`（`None` 时用 `render_pdf`，测试注入 fake）→ 校验 `%PDF` 魔数 → 返回 `(pdf_bytes, filename)`；渲染异常统一 `raise PdfRenderError(...) from exc`。
- 渲染线程（关键）：Playwright 同步对象**有线程亲和性**，不能在 FastAPI 线程池的不同线程里复用同一个 browser 实例。因此模块内用 `ThreadPoolExecutor(max_workers=1)` 起**唯一一个渲染线程**，Playwright/Chromium 的启动、`page.pdf()`、关闭都在这个线程里完成；请求线程只 `future.result(timeout=40)` 等结果。这样自然串行化渲染（不需要额外 Semaphore），也不会跨线程踩坑。
- 超时与失败：`page.pdf(timeout=30_000)` + `future.result(timeout=40)`；超时/异常把 worker 标记为 broken（丢弃并重建 executor），当前请求抛 `PdfRenderError`；chromium 启动失败同样转 `PdfRenderError`。`atexit` 里向 worker 投递关闭任务并 `shutdown(wait=False)`。
- 不使用 async Playwright（避免与 FastAPI 事件循环线程冲突）；路由保持 `def`（同步），跑在 FastAPI 线程池。

### 6.1 模板（`app/templates/paper_pdf.html`）

- `<base href="{{ base_href }}">` + `<link rel="stylesheet" href="katex/katex.min.css">`、`<script src="katex/katex.min.js">`、`<script src="katex/contrib/auto-render.min.js">`。
- 行内脚本：`renderMathInElement(document.body, {delimiters: [{left: "$$", right: "$$", display: true}, {left: "$", right: "$", display: false}], throwOnError: false}); document.fonts.ready.then(() => { window.__katexReady = true })`。
- 卷头：标题（h1）、`总分 {{ total_score }} 分 · {{ duration_min }} 分钟 · 共 {{ question_count }} 题`、可选学科名、生成日期（`YYYY-MM-DD`）。
- 题干卷每题：`{{ number }}. （{{ qtype }}，{{ score }} 分）` + 题干 + 选项（A/B/C/D 换行）；单选/填空后 `<div class="blank-2"></div>`（2 行高度），解答题后 `<div class="blank-solve"></div>`（60 mm）。
- 答案卷每题：题干 + `<div class="answer">答案：…</div>` + `<div class="analysis">解析：…</div>`（`analysis_md` 为空则不显示解析块）。
- 打印 CSS：`@page { size: A4; margin: 18mm 16mm 20mm; }`，`body { font-family: "Noto Sans CJK SC", "Microsoft YaHei", "SimSun", sans-serif; font-size: 12pt; }`，`.question { break-inside: avoid; }`（避免题干被分页劈开），行高 1.6。
- 页眉/页脚用 Playwright `header_template` / `footer_template`（内联 CSS，含 `font-size:9pt`）：
  - 页眉左：`{{ title }}`；右：`{{ variant_label }}`。
  - 页脚右：`第 <span class="pageNumber"></span> / <span class="totalPages"></span> 页`。
- `header_template`/`footer_template` 里的标题做 HTML 转义（Jinja2 渲染后再传给 Playwright，注意这是第二份字符串，同样转义）。

## 7. 静态资源与字体

- 从 `web/node_modules/katex/dist/` 拷贝到 `backend/app/static/katex/`：`katex.min.css`、`katex.min.js`、`contrib/auto-render.min.js`、`fonts/`（woff2 为主，保留 woff/ttf 中 KaTeX 默认引用的部分）。
- 拷贝脚本 `scripts/sync_katex.py`（一次性/升级时用）：读 `web/node_modules/katex/package.json` 的版本，打印并复制上述文件；不进运行时依赖。
- 版本记录：`backend/app/static/katex/VERSION.txt` 写 `katex@<version> copied from web/node_modules`。
- 中文字体：开发机用 `Microsoft YaHei`/`SimSun`；**上线 Docker 必须装 `fonts-noto-cjk`**（文档写清 `apt-get install -y fonts-noto-cjk chromium` 或 Playwright 官方镜像），否则中文变方块——本轮不改镜像，只在 `PROGRESS/DECISIONS` 记一条待办。

## 8. 前端设计

- `web/src/api/papers.ts` 加：

```ts
export async function exportPaperPdf(
  id: number,
  variant: 'questions' | 'answers',
): Promise<Blob> {
  const resp = await http.get<Blob>(`${API_PREFIX}/papers/${id}/export.pdf`, {
    params: { variant },
    responseType: 'blob',
    timeout: 60_000,
  })
  return resp.data
}
```

- `Generate.vue`：保存成功后记住 `savedPaperId`，在预览头部渲染两个按钮（`data-testid="export-questions"` / `export-answers"`）；点击时禁用来防重复，`blob` 用 `URL.createObjectURL` + 临时 `<a download>` 下载，`finally` `revokeObjectURL`；失败由 `http.ts` 统一弹错。
- 文件名由响应头给不出时（前端拿不到 `Content-Disposition` 的跨域场景）用 `试卷-${id}-${变体}.pdf` 兜底。
- 保存后再换题/删题：`savedPaperId` 保留（导出的是库里那份），但按钮旁加小字「导出的为已保存版本」，避免误解。

## 9. 测试清单

### 后端 `tests/test_pdf_service.py`（纯函数/注入）

1. `test_build_context_questions_numbers_and_blanks`：5 题 → 序号 1–5、单选/填空 `blank_lines=2`、解答走 CSS 块、总分/题量透传。
2. `test_build_context_answers_keeps_stems`：答案卷仍含题干，且答案/解析字段透传。
3. `test_build_context_rejects_empty_items`：`items=[]` → `ConflictError`。
4. `test_build_context_unknown_variant_raises`：防御性 422/`InvalidParamError`。
5. `test_render_html_escapes_and_keeps_math`：题干含 `<script>` 与 `$x^2$` → HTML 里 `&lt;script&gt;` 且 `$x^2$` 原样。
6. `test_render_html_variant_diff`：题干卷不含「答案：」，答案卷含答案与解析。
7. `test_build_header_footer_has_page_numbers_and_escapes_title`：标题 `<期中>卷` 被转义、页脚含 `pageNumber`/`totalPages`。
8. `test_export_pdf_uses_injected_renderer`：fake renderer 返回 `b"%PDF-1.4"`，断言返回字节、文件名 `期中卷高一-题干卷.pdf`、HTML 含题干。
9. `test_export_pdf_wraps_renderer_failure`：fake 抛 `RuntimeError` → `PdfRenderError`。

### 后端 `tests/test_pdf_api.py`（TestClient + fake renderer）

10. `test_export_requires_login_returns_401`。
10. `test_export_forbids_other_user_returns_403`。
11. `test_export_missing_paper_returns_404`。
12. `test_export_empty_paper_returns_409`。
13. `test_export_questions_returns_pdf_bytes`：200、`content-type=application/pdf`、`%PDF` 开头、`Content-Disposition` 含 RFC 5987 文件名。
14. `test_export_answers_returns_filename_with_answer_label`。
15. `test_export_invalid_variant_returns_422`。
16. `test_export_renderer_error_returns_500`。

### 前端

18. `papers.spec.ts`：`exportPaperPdf` 用 `responseType: 'blob'` + `params.variant`，并 unwrap 成 Blob。
19. `Generate.spec.ts`：保存前无导出按钮；保存成功后出现两个按钮；点「导出答案卷」调用 `exportPaperPdf(id,'answers')` 并触发下载（mock `URL.createObjectURL`）。
20. 保留原有 11 条页面用例全绿。

### 真实 PDF 验收（非 pytest，`.sdd/s5-3/`）

21. 用 `pdfplumber` 抽两卷文字：断言标题、题号 1–5、至少 1 个 `$...$` 公式的渲染文本、页码「第 1 / N 页」；断言题干卷不含「答案：」、答案卷含「答案：」。
22. 文件大小 > 20 KB、页数 ≥ 1；浏览器点按钮能下载且文件名中文正常。

## 10. 验收步骤（执行时落 `.sdd/s5-3/acceptance-evidence.md`）

1. `pip install playwright pdfplumber` + `playwright install chromium`；`python scripts/check_services.py` 3/3。
2. `pytest` 全量；`npm run test:run`、`npm run build`。
3. 起后端 8000 + 前端 5173，用学生 50 保存一份「解答 5 题」卷（S5-2 已证 `ok=true`）。
4. `curl` 导出两卷 → 保存 PDF → `pdfplumber` 抽文字比对（脚本 `.sdd/s5-3/verify_pdf.py`）。
5. Chrome headless/CDP 或手动点两个按钮，确认下载与文件名；截图存 `.sdd/s5-3/`。
6. 失败路径：`/papers/999999/export.pdf` → 404；空卷 → 409；fake 渲染失败 → 500（pytest 覆盖并贴输出）。
7. 记录真实数字：PDF 页数/大小/抽取文字长度、耗时、字体是否缺字。

## 11. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 中文字体缺失 → 方块 | 验收直接失败 | 本机用雅黑/宋体；文档写明 Docker 装 `fonts-noto-cjk`；验收抽文字检查中文 |
| KaTeX WOF2 字体未加载 | 公式乱码/空白 | 等 `document.fonts.ready` + `__katexReady`；静态目录与 CSS 相对路径一致 |
| Playwright 首次启动慢/超时 | 首导出 500 | 30 s 超时 + 1 次重试 + 浏览器单例预热（验收时记录首/次导出耗时） |
| 并发导出打爆内存 | 服务不稳 | 单渲染线程串行 + 30 s 页超时；不支持并行导出（学生单人场景够用） |
| 题干被分页劈开 | 打印不可用 | `.question { break-inside: avoid; }`，验收目测页数 |
| 页码/页眉字体缺失 | 页脚乱码 | header/footer 模板内联 `font-family` 与 `font-size` |
| 合同未定 `variant` 命名 | 前后端不一致 | 本 spec 定死 `questions|answers`，API.md 同步 |

## 12. 决策表（本轮已确认）

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| 1 | 渲染管线 | 后端 Jinja2 + Playwright + 本地 KaTeX | 任务卡指定；与前端解耦、离线可用 |
| 2 | 两卷暴露 | 同一接口 `?variant=` | 契约最小、鉴权复用 |
| 3 | 同步/失败 | 同步；失败 500/50000 | 2–5 秒级；与现有错误体系一致 |
| 4 | 资源落地 | KaTeX dist 拷进 `backend/app/static` | 离线/Docker 可用 |
| 5 | 版式 | A4、留白、页眉页脚 | 打印出来能直接用 |
| 6 | 前端入口 | 保存后两个下载按钮 | 最小闭环，列表页留 S5-7 |
| 7 | 题干渲染 | 转义 + KaTeX 公式，不做 Markdown | 与 `MathText` 一致 |
| 8 | 缓存 | 不缓存、实时渲染 | 卷面会变，缓存失效逻辑不值 |
| 9 | 依赖 | 装 playwright + pdfplumber + chromium | 任务卡要求，验收必需 |
| 10 | 答案卷内容 | 题干 + 答案 + 解析 | 讲评对照 |

## 13. 文档同步

- `docs/API.md §8`：把 `export.pdf` 占位改成上面的完整契约。
- `docs/SCHEMA.md`：`papers` 小节加一句「导出 PDF 不落库、不建缓存表」。
- `docs/PROGRESS.md`：最近完成/验收/待解决/变更日志/勾选 S5-3。
- `docs/DECISIONS.md`：D-060（导出管线与两卷口径、Docker 字体待办）。
- `AGENTS.md §9.6`：PDF 导出锚点（模板 + 两层纯函数 + 注入 renderer）。
- `docs/AI协作开发实施计划.md`：S5-3 勾选。
- `requirements.txt` 加依赖；无新环境变量（超时/并发用常量，后续需要再进 Settings）。