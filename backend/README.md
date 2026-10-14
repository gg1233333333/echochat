# EchoChat FastAPI

入口采用应用工厂 `app.main:create_app`。启动时校验服务端密钥与生产鉴权配置；
缺失时立即失败。运行依赖与测试依赖分别锁定在 `requirements.txt`、
`requirements-test.txt`，`pyproject.toml` 提供依赖范围及工具配置。

## 接口

`GET /api/health` 返回 `{"status":"ok"}`，只检查进程健康，不验证模型余额或连通性。

`POST /api/chat/stream`：

```json
{
  "mode": "thinking",
  "messages": [
    {"role": "system", "content": "你是一个友好的助手。"},
    {"role": "user", "content": "你好"}
  ]
}
```

模式只允许 `thinking`、`non-thinking`。服务端固定 DeepSeek URL、`deepseek-flash`
模型、思考参数和输出上限；客户端不能指定目标 URL、密钥或生成预算。
请求最多 100 条消息、单条 32000 字符、总计 64000 字符、请求体 256 KiB。
未知字段被拒绝，最后一条必须是用户消息。历史角色与附件摘要沿用前端实现。

SSE 协议示例：

```text
event: delta
data: {"content":"你好"}

event: done
data: {"finish_reason":"stop"}

```

失败终止事件：

```text
event: error
data: {"code":"upstream_timeout","message":"等待模型服务超时，请重试。","retryable":true,"request_id":"..."}

```

成功只在收到上游 `[DONE]` 后发出 `done`。正常 EOF、无效 JSON、非法 UTF-8、
过大的 SSE 事件都会报错。`finish_reason=length` 会在前端提示长度限制。
模型推理内容不作为最终答案输出；等待期间每 15 秒发送 `: keepalive` 注释。

校验/鉴权失败在流开始前返回 HTTP 401/403/413/422 和 `{"error":{...}}`。
上游连接和状态异常发生在流内，通过 `event: error` 返回，HTTP 此时已为 200。
客户端应检查终止事件，不能仅根据 HTTP 200 判断请求成功。

| 错误码 | 场景 | 可重试 |
| --- | --- | --- |
| `invalid_request` / `request_too_large` | 请求无效或超限 | 修改输入后 |
| `unauthorized` / `local_only` / `origin_not_allowed` | 网关或来源检查失败 | 配置修正后 |
| `upstream_authentication` | 上游 401/403 | 管理员修正密钥后 |
| `upstream_quota_exceeded` | 上游 402 | 充值后 |
| `upstream_rate_limited` / `server_busy` | 上游限流或本机并发已满 | 是 |
| `upstream_unavailable` / `upstream_network` | 上游 5xx 或网络故障 | 是 |
| `upstream_timeout` / `stream_timeout` | 连接、读取或总时限超时 | 是 |
| `upstream_invalid_request` | 上游拒绝请求 | 修改输入后 |
| `upstream_protocol` / `upstream_truncated` | 协议错误或缺少结束标记 | 视情况 |
| `internal_error` | 未预期的服务错误 | 排查后 |

不自动重试，避免已输出的 token 重复或增加计费。错误不会返回上游原始响应体，
日志只记录请求 ID、错误码或异常类型，不记录密钥和聊天内容。

## 超时和生命周期

- HTTPX：连接 10 秒、读取空闲 60 秒、写入 10 秒、连接池 5 秒。
- 服务端整次生成 300 秒，包括等待上游响应头；注释心跳不延长这个时限。
- 前端空闲 75 秒、总时限 315 秒；若修改服务端预算，需同步调整前端预算和代理时限。
- 下游断连会取消正在等待响应头/数据的任务，并关闭 HTTPX response。
- 下游发送失败也显式关闭生成器；总时限额外留 5 秒限制不读取数据的客户端。
- 异步客户端由 lifespan 共享，服务关闭时释放连接池；并发名额由生成器 `finally` 释放。
- 并发上限默认每个 worker 8 条。多 worker/多实例总配额需在网关或共享存储控制。

## 生产边界

开发模式仅接受 loopback 客户端，Vite 和 Uvicorn 都默认监听 `127.0.0.1`。
部署时设置 `APP_ENV=production`、至少 32 字符的 `GATEWAY_TOKEN`，
配置 `ALLOWED_HOSTS` 和 `CORS_ORIGINS` 为实际站点。所有值都只保存在服务端。

生产 FastAPI 只接受 `X-EchoChat-Gateway-Token` 与服务端配置匹配的请求。
此 header 必须由经过用户鉴权的代理注入，并覆盖客户端同名 header；
它是网关到后端的凭据，不是可放进前端的用户 token。后端端口不得直接开放公网。
CORS 和 Origin 检查用于限制来源，身份鉴权由网关承担。

仓库提供 TLS + Basic Auth + 按 IP 限流/并发控制的 Nginx 模板：

1. 用 `openssl rand -hex 32` 生成网关凭据，配置后端环境与 Nginx 服务环境为相同值。
2. 配置 TLS 证书、真实域名、前端 `dist` 目录；用 `htpasswd` 创建 `/etc/nginx/echochat.htpasswd`。
3. 只替换模板中的网关变量：
   `envsubst '${GATEWAY_TOKEN}' < deploy/nginx.conf.template > /etc/nginx/conf.d/echochat.conf`。
4. 将 `APP_ENV=production`、`ALLOWED_HOSTS=["你的域名"]`、
   `CORS_ORIGINS=["https://你的域名"]` 写入后端环境；Uvicorn 不信任外部代理 IP header。
5. 运行 `nginx -t` 后重载。验证未登录时被拒绝，登录后流式更新且停止能释放上游。

该模板需要 Nginx 的 standard `auth_basic`、`limit_req`、`limit_conn` 模块。
这里只提供可部署的配置，未替你开通账号、配置证书或实际发布服务。
