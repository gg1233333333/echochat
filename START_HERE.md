# 本地启动

需要 Python 3.11+、uv，以及 Node.js 20.19+ 或 22.12+。在解压后的项目根目录打开两个 PowerShell 窗口。

窗口一：

```powershell
cd backend
uv sync --frozen
uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 8000
```

窗口二：

```powershell
cd frontend
npm ci
npm run dev
```

浏览器打开 http://127.0.0.1:5173/ 。在“设置 → 模型接口”核对服务地址/模型/兼容协议，再由你在“API Key 设置”填写自己的密钥。不要把密钥写进源码、`VITE_` 环境变量或交付文件。仅查看界面不需要密钥；发消息/使用联网工具可能产生模型费用及外部网络访问。

停止：分别在两个启动窗口按 Ctrl+C。聊天数据创建在 `backend/data/`，重启后需重新填写内存密钥。只监听本机、单进程使用；重启中断不会自动续跑。

源码包不含账号、密钥、个人聊天数据、安装依赖、课程或效果承诺。分发/出售前先处理 [第三方与素材权利待确认项](THIRD_PARTY_NOTICES.md)。完整功能边界见 README。

任务没有模型轮次、工具总次数或总时长上限；长任务可能持续产生费用，可随时点击停止。单次模型/工具请求超时和工具权限仍生效。
