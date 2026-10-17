# EchoChat

源码包使用见 [最短启动说明](START_HERE.md)；分发/出售前阅读 [第三方声明与待确认权利](THIRD_PARTY_NOTICES.md)。

供个人本机使用的聊天应用：Vue 3 前端、Python FastAPI 后端、SQLite 数据库。统一助手支持快速回答、深度思考、流式回复、附件、语音输入、历史会话和主题切换。

```text
echochat/
├── frontend/   # Vue 界面
├── backend/    # FastAPI、数据库迁移和后端测试
├── tests/      # 浏览器联调与模拟模型
└── docs/       # 设计与行为约定
```

## 本地启动

需要 Python 3.11+、uv、Node.js 20.19+ 或 22.12+。不需要安装 MySQL。

第一个终端启动后端：

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

第二个终端启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

打开终端显示的本机前端地址，在页面配置 DeepSeek API Key 后发送消息。前端的 `/api` 请求通过 Vite 转发到 `127.0.0.1:8000`。

首次打开会展示品牌开场，点击“开始对话”进入聊天。鼠标移动时，机器人目光跟随，邻近的光点轻轻避让，深蓝背景下的流线与星图局部显露，并留下逐渐消退的轨迹。移出窗口后效果淡出，进入聊天后停止；触屏不触发鼠标交互，减少动态效果模式使用静态背景。之后打开只显示短暂入场，底部“设置 → 重播开场”可以再次观看。建议问题只填入输入框，由用户确认发送。重播保留当前对话和草稿，回复生成期间暂不可重播。

密钥仅存在后端进程内存中，刷新页面不影响使用；清除密钥或重启后端后需要重新填写。不要将密钥写入前端环境变量或源码。后端按单进程、本机访问设计，暂不支持公网访问、多用户登录或多个 worker。

## 数据与聊天行为

输入区的“工具”开关启用 Agent 能力，默认开启；关闭后按普通聊天处理。后端使用 LangGraph 编排“模型 → 工具 → 模型”循环，复用原有流式输出、停止生成和历史记录。

- 可调用的工具：精确算术、列出和读取当前对话附件、生成可下载的 Markdown / TXT / JSON 文件、免 Key 网页搜索和公开网页文字读取。
- 回复中的“工具记录”默认折叠，可查看参数、结果与成功或失败状态；文件下载入口独立展示，刷新后仍然可用。删除所属回复或对话会同时删除文件。
- 附件读取范围限定在当前对话上下文已提交的附件；网页读取禁止本机、内网和保留地址，逐次校验重定向，不登录、不执行网页脚本。搜索关键词会发送到 DuckDuckGo，勿输入密钥或隐私资料。
- 任务不设模型轮次、工具总次数和总时长上限，直到完成、用户停止或发生错误。单次模型请求最多 120 秒、单工具最多 20 秒；输出大小和单次工具调用解析仍有限制。工具权限独立强制执行；相同参数重复失败会停止并保留已有内容与文件。长任务可能持续消耗模型费用，请按需停止。
- 搜索无需额外 Key，可能因网络或限流失败；动态网页、登录页面可能无法提取文字。附件仍采用下述提取上限，生成文件每个最多 80000 字符。
- 网页域名解析遇到 Clash 的 `198.18.0.0/15` 虚拟地址时，使用 Cloudflare 公共 DNS 查询该域名，再校验并连接公网地址；不会放行代理虚拟地址或其他内网地址。
- 执行记录与产物保存在原 SQLite 数据库，无需安装额外数据库。服务重启会把未完成任务标为中断，不自动重新执行。未接入后台调度、任意代码执行或多用户权限。LangSmith 外部追踪默认禁用。

- 聊天记录保存在 `backend/data/echochat.db`，启动时自动执行 Alembic 数据迁移。数据库和本地密钥不进入 Git。
- 会话使用独立 ID，可以同名；空白会话在首次发送后才进入历史列表。
- 同时只能生成一个回复。切换会话后，回复仍保存到原会话；停止会保留已经生成的内容。
- 深度思考模式分别保存思考过程和最终回答。回答上方的“思考过程”默认折叠，展开后可查看流式内容；刷新或重启后仍可从历史查看。停止生成也会保留已收到的思考内容，更新前未保存的思考过程无法补回。
- 统一助手可以处理日常和编程问题。旧记录的上下文分段保留；重新生成使用原回复所在的上下文，会替换该回复并删除之后的消息，页面会提示有后续记录的情况。
- 首次提问自动生成会话标题，手动重命名后不再覆盖。附件消息使用文件名命名；已有默认标题会在启动时补齐。历史摘要转换为纯文本后截断。
- 侧栏支持折叠，API Key、旧记录导入及清空入口位于底部“设置”。消息常用操作为复制、重新回复，其余操作位于“更多”。
- 支持文本、代码、PDF 和 DOCX 内容提取。每个文件最多 8 MiB，每次最多 10 个文件、合计 24 MiB；每份提取正文最多 8000 字符。数据库保留提取文本和元信息，不保存原文件。
- `.doc` 和无法提取文字的 PDF 仅保留文件信息；损坏文件会明确报错。语音识别依赖浏览器支持。

备份时先正常停止后端，再复制整个 `backend/data` 目录。恢复时也需停止后端。不要在运行中仅复制 `.db` 文件；SQLite 的 WAL 中可能还有未合并的数据。

需要手动执行数据库升级时，在 `backend` 目录运行 `uv run alembic upgrade head`。升级前先备份，迁移不会主动清空聊天记录。

## 导入旧版记录

页面支持导入当前地址下的旧版浏览器缓存，也支持导入 JSON 快照。导入不会删除旧缓存，相同快照重复导入不会重复新增。

如果旧版页面与新页面地址不同，在旧版页面的浏览器开发者工具 Console 中运行下面代码，下载快照后到 EchoChat 页面导入：

```javascript
const snapshot = localStorage.getItem('session');
if (!snapshot) throw new Error('当前页面没有旧版聊天缓存');
const url = URL.createObjectURL(new Blob([snapshot], { type: 'application/json' }));
const link = document.createElement('a');
link.href = url;
link.download = 'vue-llm-history.json';
link.click();
setTimeout(() => URL.revokeObjectURL(url), 1000);
```

旧版没有保存完整的历史角色段和消息时间，这些信息不会推测补齐；上下文无法确认的旧回复可查看，但不能重新生成。

## 检查与测试

```powershell
cd backend
uv run pytest
uv run ruff check .
```

```powershell
cd frontend
npm run lint
npm test
npm run build
```

浏览器回归使用独立端口、临时数据库和模拟模型，不产生 DeepSeek 费用。在仓库根目录启动测试后端：

```powershell
uv run --project backend python tests/browser_server.py --port 8001 --frontend-port 5174
```

另开终端启动测试前端：

```powershell
cd frontend
npm run dev -- --config ../tests/vite.config.mjs
```

第三个终端在仓库根目录依次执行：

```powershell
$env:ECHOCHAT_TEST_URL = 'http://127.0.0.1:5174'
uv run --project backend --with playwright python tests/browser_smoke.py
uv run --project backend --with playwright python tests/browser_layout.py
uv run --project backend --with playwright python tests/browser_opening.py
uv run --project backend --with playwright python tests/browser_streaming.py
uv run --project backend --with playwright python tests/browser_agent.py
```

Windows 默认使用已安装的 Edge；其他系统需要 Playwright Chromium。模拟测试验证应用行为，真实 DeepSeek 连通性需要在页面填写有效密钥验证。

详细规则见 [后端方案](docs/backend-plan.md)。


## 运行记录、工具权限与模型接口

每条新助手回复提供“运行记录”，可查看独立 run_id、执行状态和按顺序保存的模型/工具步骤；刷新后仍可查询。停止、失败和服务重启中断分别记录，重启不会自动续跑或重放工具。运行记录随所属消息/对话删除。

输入区“工具”入口默认收起，点击后逐项授权。选择保存在本机浏览器，只影响下一次请求；后端固定该次 allowlist，未授权调用即使由模型或工具内容提出也会拒绝。提示词不构成防注入保证。相同请求 ID 在记录保留时重放已有结果，同一文件工具操作键重复执行不重复生成文件；删除记录并重启后的请求去重不作长期承诺。

“设置 → 模型接口”可保存服务基础地址、模型名和兼容模式。支持 OpenAI Chat Completions 的文本 SSE/函数工具调用形状；DeepSeek 模式另发送其思考参数。不是所有声称 OpenAI 兼容的服务都实现这些能力，不支持 Responses API、原生 Anthropic/Gemini 协议。公网地址需 HTTPS；仅明确的 localhost、127.0.0.1、::1 可用本机 HTTP。自定义公网地址会验证 DNS 并固定连接地址；不跟随重定向，不关闭 TLS 校验。更换地址或兼容模式会清除内存密钥，需为新服务重新填写。

连接测试由用户点击触发，只请求已保存服务的 GET /models，不生成回复，不自动使用真实密钥做联调。成功仅证明该端点连通，不证明指定模型、思考或工具已兼容。服务不提供 /models 时可能无法通过此测试，但不据此认定聊天一定不可用。非敏感接口配置保存在 SQLite，API Key 仍只在后端内存中。

实现与验收边界见 [三项底座能力](docs/agent-foundation.md)。

密钥设置在打开弹窗时显示并固定目标地址/协议；保存时后端在同一锁下核对目标，过期弹窗或不带目标的自定义服务请求返回 409，需重新打开核对。旧版不带目标的密钥请求仅兼容默认 DeepSeek 地址及协议。运行接受时原子固定目标和密钥；自定义固定 IP 的连接每次关闭，避免同 IP 不同域名复用 TLS 身份。
