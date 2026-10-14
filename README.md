# EchoChat

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
```

Windows 默认使用已安装的 Edge；其他系统需要 Playwright Chromium。模拟测试验证应用行为，真实 DeepSeek 连通性需要在页面填写有效密钥验证。

详细规则见 [后端方案](docs/backend-plan.md)。
