# EchoChat 前端

Vue 3、Pinia、Element Plus 和 Vite。统一助手支持快速回答、深度思考、流式回复、文件与语音输入、会话管理和主题功能。

## 运行

先按仓库根目录 README 启动 Python 后端，再执行：

```powershell
npm ci
npm run dev
```

访问 http://127.0.0.1:5173。页面中的 `/api` 请求由 Vite 代理到 http://127.0.0.1:8000。

点击输入区的 **配置 API Key** 或侧栏底部 **设置 → API Key 设置**，输入自己的 DeepSeek 密钥后点击 **使用密钥**。配置成功后回到聊天，密钥只留在后端进程内存中。清除或重启后端后需重新配置。

聊天历史保存在后端 SQLite。浏览器只持久化主题、选中会话和模式；未发送文本及文件按会话暂存在内存中。

## 检查

```powershell
npm run lint
npm test
npm run build
```

`npm run preview` 在相同的 5173 端口预览构建结果，需要先停止开发服务器，并保持后端运行。

Vue DevTools 浮层默认关闭，避免遮挡手机上的操作按钮；需要调试时可设置环境变量 `ECHOCHAT_DEVTOOLS=1` 后启动。

## 旧版记录

侧栏底部 **设置 → 导入旧记录** 支持当前地址的旧浏览器缓存，或旧页面导出的 JSON 文件。导入成功后保留原缓存，相同快照重复导入会跳过。跨地址导出方法见仓库根目录 README。
