# 回韵轻语（EchoChat）

一个基于 Vue 3、Vite 和 DeepSeek Chat API 的多角色 AI 对话应用。

支持通用助手与程序员助手切换、流式回复、附件上传、语音输入、主题切换和多会话管理。

## 目录

- [项目概览](#项目概览)
- [功能清单](#功能清单)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [使用说明](#使用说明)
- [项目结构](#项目结构)
- [核心实现说明](#核心实现说明)
- [开发建议](#开发建议)
- [已知限制](#已知限制)

## 项目概览

回韵轻语围绕“轻量、多会话、多角色”的前端 AI 聊天体验设计，当前主要能力包括：

- 通过按钮在 `通用助手` 和 `程序员助手` 之间切换
- 在 `deepseek-chat` 与 `deepseek-reasoner` 之间切换模型
- 流式渲染 AI 输出内容
- 支持会话新建、重命名、删除、清空、搜索
- 支持文本、文档和常见代码文件上传
- 支持浏览器语音输入
- 支持浅色 / 深色主题和移动端侧边栏

## 功能清单

### 对话能力

- 双角色模式
  - 通用助手：面向日常问答、学习、写作、生活类问题
  - 程序员助手：面向编程、调试、架构、工程实践问题
- 双模型切换
  - `deepseek-chat`：更偏快速响应
  - `deepseek-reasoner`：更适合复杂问题
- 流式输出
  - AI 内容按 token 逐步显示
- 消息操作
  - 复制纯文本
  - 复制完整 Markdown
  - 重新生成上一条 AI 回复
  - 删除单条消息

### 会话与角色

- 多会话管理
  - 新建对话
  - 重命名对话
  - 删除对话
  - 清空全部历史
  - 搜索历史会话
- 会话级角色记忆
  - 每个会话记录自己的当前角色
  - 会话切换时会恢复对应角色
- 角色切换上下文隔离
  - 同一个会话里切换角色后，后续请求只携带切换后的上下文
  - 避免“前面是程序员助手，切回通用助手后仍被旧上下文带偏”
- 动态 favicon
  - 不同角色切换不同 favicon

### 输入与附件

- 文本输入
  - `Enter` 发送
  - `Shift + Enter` 换行
- 停止生成
  - 生成过程中可以中止流式请求
- 语音输入
  - 基于浏览器 Web Speech API
  - 当前语言设置为 `zh-CN`
- 附件上传
  - 单文件大小限制：`8 MB`
  - 预览内容最大长度：`8000` 字符
  - 文件信息会被拼接到模型上下文中

### 文件支持情况

- 内置文本解析较完整的类型
  - `txt`
  - `md`
  - `csv`
  - `json`
  - `log`
  - `pdf`
  - `docx`
- 允许上传的常见扩展名
  - 文本与结构化数据：`xml` `yml` `yaml`
  - 前端文件：`html` `css` `scss` `less` `js` `jsx` `ts` `tsx` `vue`
  - 后端与脚本：`py` `java` `c` `cpp` `cc` `h` `hpp` `cs` `php` `rb` `go` `rs` `kt` `swift` `sql` `sh`
  - 文档：`doc` `docx` `pdf`
- 行为说明
  - 命中内置解析器时，会提取正文摘要并附到上下文
  - 未命中解析器时，仍会携带文件名称、大小、类型等元信息

### 界面与体验

- Element Plus 驱动的桌面端对话界面
- 虚拟滚动长列表，减轻大量消息渲染压力
- 代码块高亮与复制按钮
- 表格渲染
- 响应式布局
  - 桌面端左右分栏
  - 移动端抽屉式侧边栏
- 主题切换
  - 手动切换明暗模式
  - 支持初次加载跟随系统主题

## 技术栈

### 前端框架

- Vue 3
- Composition API
- Pinia
- Vite

### UI 与交互

- Element Plus
- `@element-plus/icons-vue`
- `vue-virtual-scroller`

### 内容渲染

- `markdown-it`
- `markdown-it-table`
- `highlight.js`

### 文件处理

- `pdfjs-dist`
- `jszip`

### 状态持久化

- `pinia-plugin-persistedstate`

## 快速开始

### 环境要求

- 推荐 `Node.js 20+`
- 推荐 `npm 9+`

说明：

- 当前项目使用的是 `Vite`
- 如果本地 Node 版本过低，可能会出现依赖安装或 dev server 启动问题

### 1. 安装依赖

```bash
npm install
```

### 2. 配置环境变量

复制示例配置：

```bash
cp .env.example .env
```

Windows PowerShell 可使用：

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`：

```bash
VITE_DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
```

### 3. 启动开发环境

```bash
npm run dev
```

### 4. 构建生产包

```bash
npm run build
```

### 5. 本地预览构建结果

```bash
npm run preview
```

### 6. 运行 ESLint

```bash
npm run lint
```

注意：

- 当前 `lint` 脚本实际执行的是 `eslint . --fix`
- 它不仅检查代码，还会尝试自动修改文件

## 环境变量

| 变量名 | 必填 | 说明 |
| --- | --- | --- |
| `VITE_DEEPSEEK_API_KEY` | 是 | DeepSeek API Key，用于前端直接请求 `https://api.deepseek.com/v1/chat/completions` |

## 使用说明

### 基本操作流程

1. 启动项目后，左侧点击“新建对话”
2. 在聊天页顶部切换角色
3. 选择模型
4. 在输入框中输入文本，或上传附件，或使用语音输入
5. 发送消息
6. 等待 AI 回复流式生成完成

### 角色说明

#### 通用助手

- 面向开放式问答
- 适合聊天、学习、写作、解释、总结、生活类问题
- favicon 与角色标识使用通用风格

#### 程序员助手

- 面向软件开发场景
- 更适合代码、报错、调试、架构、工程化问题
- 对明显非技术问题会给出模式提醒

### 模型说明

#### `deepseek-chat`

- 响应更快
- 适合日常普通对话

#### `deepseek-reasoner`

- 更适合复杂问题
- 前端仍以普通回复的形式流式展示内容

### 会话说明

- 每个会话有独立标题
- 每个会话记录自己的角色
- 当前对话和主题状态会持久化到本地
- 同一会话切换角色后，后续请求会从新的上下文边界开始组装消息

### 附件说明

- 单文件大小限制：`8 MB`
- 提取正文后只保留前 `8000` 个字符
- PDF 和 DOCX 会尝试做内容解析
- 解析失败时仍保留文件元信息

### 语音输入说明

- 依赖浏览器的 `SpeechRecognition` / `webkitSpeechRecognition`
- 并非所有浏览器都支持
- 当前识别语言为 `zh-CN`
- 开始生成回复后，会自动停止录音

## 项目结构

```text
vue-llm/
├── public/
│   ├── favicon.svg
│   └── faviconcode.svg
├── src/
│   ├── apis/
│   │   └── deepseek.js
│   ├── assets/
│   │   ├── avatars/
│   │   │   ├── assistant.svg
│   │   │   ├── faviconcode.svg
│   │   │   └── user.svg
│   │   ├── base.css
│   │   ├── faviconcode.svg
│   │   ├── logo.svg
│   │   └── main.css
│   ├── components/
│   │   └── chat/
│   │       ├── AttachmentPreview.vue
│   │       ├── ChatInput.vue
│   │       └── ConversationSidebar.vue
│   ├── composables/
│   │   └── useDynamicFavicon.js
│   ├── config/
│   │   └── deepseekKey.js
│   ├── stores/
│   │   ├── session.js
│   │   └── theme.js
│   ├── utils/
│   │   ├── aiRoles.js
│   │   ├── MarkdownWorker.js
│   │   └── streamQueue.js
│   ├── views/
│   │   └── chatMessage.vue
│   ├── App.vue
│   └── main.js
├── docs/                   # 预留文档目录（当前为空）
├── .env.example
├── index.html
├── package.json
├── vite.config.js
└── README.md
```

## 核心实现说明

### 页面层级

#### `src/App.vue`

负责整体布局和响应式容器：

- 桌面端左右分栏
- 移动端顶部标题栏
- 移动端侧边栏展开 / 收起
- 根据角色自动切换 favicon

#### `src/views/chatMessage.vue`

负责主聊天区域：

- 消息列表渲染
- Markdown 渲染
- 代码块复制
- 模型切换
- 角色切换
- 流式响应展示
- 重新生成 / 删除消息

#### `src/components/chat/ConversationSidebar.vue`

负责左侧会话区：

- 新建对话
- 搜索历史
- 会话预览
- 会话角色标签
- 重命名 / 删除 / 清空历史
- 主题切换

#### `src/components/chat/ChatInput.vue`

负责底部输入区：

- 文本输入
- Enter / Shift+Enter
- 文件选择与解析
- 语音输入
- 停止生成

### 状态管理

#### `src/stores/session.js`

项目的核心状态都在这里：

- 所有会话消息
- 当前会话名
- 会话更新时间
- 当前模型
- 当前角色
- 角色切换后的上下文边界

特别说明：

- `roleContextStart` 用于解决“同一会话切换角色后，旧上下文继续干扰新角色”问题
- `getMessagesForModel()` 会从该边界开始组装真正发给模型的消息

#### `src/stores/theme.js`

负责主题模式：

- 浅色 / 深色切换
- 初次加载跟随系统主题
- 用户主动切换后优先使用本地持久化值

### 请求与流式处理

#### `src/apis/deepseek.js`

负责直接请求 DeepSeek 接口：

- 使用 `fetch` 调用 `chat/completions`
- `stream: true`
- 手动解析 SSE
- 暴露 `abortStream()` 供前端停止生成

#### `src/utils/streamQueue.js`

负责降低高频 token 渲染带来的 UI 压力：

- 把流式 token 先放入队列
- 使用 `requestAnimationFrame` 合并后再写入状态

### 角色系统

#### `src/utils/aiRoles.js`

负责角色元信息：

- 角色 ID
- 角色名称
- 角色描述
- 系统提示词
- 对应 favicon

如果后续你要增加新角色，通常优先改这个文件。

### 动态 favicon

#### `src/composables/useDynamicFavicon.js`

监听当前角色变化，自动替换浏览器标签页图标。

### 样式系统

#### `src/assets/base.css`

全局 CSS 变量和颜色系统：

- 明暗主题变量
- 边框、文本、阴影、工具栏、代码块等配色

#### `src/assets/main.css`

全局通用样式：

- `html/body/#app` 高度铺满
- Element Plus 对话框的全局样式覆盖

## 开发建议

### 新增角色

修改：

- `src/utils/aiRoles.js`

如需配套图标，再补充：

- `public/`
- `src/assets/`
- `src/assets/avatars/`

### 新增模型

修改：

- `src/stores/session.js`

更新 `MODEL_OPTIONS` 即可。

### 扩展附件解析能力

修改：

- `src/components/chat/ChatInput.vue`

重点关注：

- `ALLOWED_EXTENSIONS`
- `ALLOWED_MIME_TYPES`
- `readFileContent()`
- `extractPdfText()`
- `extractDocxText()`

### 调整角色切换策略

修改：

- `src/stores/session.js`

重点关注：

- `setRole()`
- `roleContextStart`
- `getMessagesForModel()`

### 调整聊天区 UI

主要文件：

- `src/views/chatMessage.vue`
- `src/components/chat/ConversationSidebar.vue`
- `src/components/chat/ChatInput.vue`
- `src/assets/base.css`

## 已知限制

### 1. 当前是纯前端直连 DeepSeek

这意味着：

- API Key 会出现在浏览器端环境中
- 不适合直接作为开放公网产品的最终安全方案

更稳妥的做法是：

- 增加后端代理
- 在服务端持有真实 API Key
- 前端只请求自己的后端接口

### 2. 语音输入依赖浏览器实现

并非所有浏览器都支持：

- `SpeechRecognition`
- `webkitSpeechRecognition`

如果浏览器不支持，语音按钮不会出现。

### 3. 构建产物当前较大

原因主要包括：

- `pdfjs-dist`
- 高亮相关依赖
- 单页应用主包未做更细粒度拆分

当前执行 `npm run build` 时会出现大包 warning，这不会阻止构建，但后续值得继续优化。


## 适合继续扩展的方向

- 接入后端代理，隐藏 API Key
- 支持更多模型供应商
- 支持消息导出
- 支持代码块运行或沙箱预览
- 支持多角色预设编辑器
- 支持更完整的附件解析策略
- 对大包依赖做懒加载与分包优化

## 最后

- 本项目未开源，可用于学习，以及写进简历中，当你收到这个项目时，欢迎继续修改和拓展。
