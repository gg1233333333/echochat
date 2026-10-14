# EchoChat

Vue 前端与 Python FastAPI 后端的统一仓库。

## 项目结构

```text
echochat/
├── frontend/   # Vue 3 前端
└── backend/    # FastAPI 流式代理、接口测试
```

## 本地启动

推荐 Python 3.12 和 Node.js 24 LTS。先启动后端：

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

只在 `backend/.env` 填写 `DEEPSEEK_API_KEY`，然后运行：

```bash
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

在另一个终端启动前端：

```bash
cd frontend
npm ci
```

```bash
npm run dev
```

Vite 默认将 `/api` 代理到 `http://127.0.0.1:8000`，前端无需配置密钥。
可选的 `frontend/.env` 只配置 `API_PROXY_TARGET`。删除旧的前端密钥配置；
如果旧版本已公开部署并暴露过真实密钥，请在 DeepSeek 控制台轮换该密钥。

Windows 复制配置使用 `Copy-Item .env.example .env`。会话、附件摘要、角色选择
仍在浏览器维护，FastAPI 仅代理模型请求，不保存聊天内容。

## 验证

```bash
cd backend
pip install -r requirements-test.txt
python -m pytest -q
ruff check app tests
ruff format --check app tests
```

```bash
cd frontend
npm ci
npm test
npm run lint:check
npm run build
npm run check:bundle
```

自动化测试不需要真实 DeepSeek Key，也不会调用计费 API。后端包含真实本机 TCP
流式集成测试，验证 HTTPX、Uvicorn、取消和连接关闭。CI 执行相同检查。

实际 DeepSeek 连通性、生产网关鉴权和浏览器操作仍需在目标环境验收：
发送、停止后立即重发、切换会话/角色、重新生成、附件对话、刷新恢复，以及超时提示。

## 部署和协议

[后端接口及安全边界](backend/README.md)、[前端说明](frontend/README.md)、
[生产 Nginx 配置模板](deploy/nginx.conf.template)。生产模式要求已鉴权的网关注入
服务端 `GATEWAY_TOKEN`；不得把这个凭据放到浏览器配置。当前不包含独立的用户账号系统。
