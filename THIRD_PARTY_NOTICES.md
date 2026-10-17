# 第三方组件与权利说明

本源码交付不捆绑依赖安装目录或构建产物。锁定版本及已安装依赖的许可元数据见 [清单](third_party/DEPENDENCIES.json)，可获取的上游版权/许可原文保留在 `third_party/licenses/`。这些声明只适用于对应第三方组件，不为本项目整体新增许可证。

| 组件 | 许可/处理 |
| --- | --- |
| Vue、Pinia、Vite、Element Plus、LangGraph、FastAPI、SQLAlchemy 等 | 多为 MIT；具体版本及原文以清单为准。 |
| HTTPX、Uvicorn、pypdf 等 | BSD；保留版权及免责声明。 |
| python-multipart 等 | Apache-2.0；保留适用许可及 NOTICE。 |
| certifi、orjson 内含部分组件 | 包含 MPL-2.0 条款；文件级义务不应被解释为本项目整体改用 MPL。交付包未修改或捆绑这些依赖源码。 |
| `caniuse-lite`（开发依赖数据） | CC-BY-4.0；保留上游来源/许可声明。Element Plus 及 `@element-plus/icons-vue` 的声明为 MIT，具体见清单和原文。 |
| GSAP 3.15.0 | 标准 no-charge 许可，非 MIT。官方允许一般商业项目，禁止未经书面同意的竞争性无代码可视动画构建用途，不得移除其专有声明；见 [原文](https://gsap.com/community/standard-license/)。当前聊天界面的动画使用属于普通界面使用的判断，不能替代权利人的解释。 |

清单含锁文件的开发依赖、可选及跨平台项；Windows 未安装项明确标注，不代表所有操作系统都已验证。构建或重新分发依赖/产物时仍需保留对应声明，重新核查实际安装平台和版本。

## 本项目与静态素材

仓库目前没有项目整体 `LICENSE`；本文件不擅自授予、转让或变更任何人的权利。公开 GitHub 仓库不等于向买方授予商业再分发许可，参见 [GitHub 说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。出售前，权利人需确认原创/贡献代码权属，并明确买方的使用、修改、分发或转售范围。

`frontend/src/assets/` 与 `frontend/public/` 中现有 SVG 没有随仓库提供可核验的作者/商业授权记录。部分文件带导出工具元数据，但元数据不能证明来源或许可。出售前需提供对应授权记录，或换成权属清楚的素材；本交付不将其宣称为已获商业授权。此项尚未解决，因此不能把该源码包描述为已完成全部可售权利审核。

待确认文件（导出元数据是线索，不是来源证明）：

- `frontend/public/favicon.svg`：HTML、后端角色选项及动态 favicon 回退直接使用。
- `frontend/src/assets/avatars/assistant.svg`：聊天视图直接导入。
- `frontend/public/faviconcode.svg`
- `frontend/src/assets/faviconcode.svg`
- `frontend/src/assets/logo.svg`
- `frontend/src/assets/avatars/faviconcode.svg`
- `frontend/src/assets/avatars/user.svg`

后五项在当前源码中未找到直接引用；这只是可供后续精简的线索，本次未擅自删素材或更换视觉。即使经确认移除未使用项，前两项仍需权利核实。没有在仓库中找到可追溯到具体图标作品/作者的链接。

模型服务、联网搜索/网页、字体及其他外部服务各有独立条款；本源码包不包含服务账号、API Key、模型额度、数据内容权利或效果/就业承诺。真实第三方模型与计费兼容性未在交付检查中调用验证。
