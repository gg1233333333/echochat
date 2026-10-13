# EchoChat

Vue 前端与 Python FastAPI 后端的统一仓库。

## 项目结构

```text
echochat/
├── frontend/   # Vue 3 前端
└── backend/    # FastAPI 后端目录，待实现
```

## 前端启动

```bash
cd frontend
npm ci
```

将 `frontend/.env.example` 复制为 `frontend/.env`，配置 DeepSeek API Key 后启动：

```bash
npm run dev
```

前端目前直接调用 DeepSeek。详细配置见 [前端说明](frontend/README.md)。

## 后端

`backend/` 当前为目录占位，尚未实现 API 服务。
