# 个人展示版发布说明

2026-11-08。公开仓库：https://github.com/hjt2007323/Wren 。版本及指纹映射见 [SOURCE-HISTORY.md](SOURCE-HISTORY.md)。

- 交付源提交：`ab4df18057a5e4b3c3c4fc29e0f3aee0010d4264`。
- 被验文件：`sdk/wren-langchain/src/wren_langchain/_format.py`，SHA256 `9351536f201b3fdd8f5f5738ddcb547d109614c1fcb5c3b22b88eda1caec3818`。
- 本次只更换首页、增加发布说明、从最初归档导入提交提取原 README 到 `README-UPSTREAM.md`，并把 22 个上游工作流移动至 `.github/upstream-workflows/`。
- 产品源码、冻结基线、测试断言、原始回执和历史测试记录全部保持原样。原证据 manifest 对应交付验收快照，不是更新首页后的完整发布清单；本轮完整清单在总控发布目录。
- 本地历史由上游源码归档导入，不是上游 Git 历史；无上游 PR、上游合并或整个平台上线声明。
- 许可：按上游 LICENSE 路径映射保留全部许可；sdk/** Apache-2.0，docs/** CC BY 4.0。
- R1 独立复验由用户指定的 DSH 项目监控完成；发布前 Codex 核对源码指纹、许可和发布副本。项目属于 AI 辅助的开源组件改进。
- 本轮无付费模型调用，不连接 A07 数据库。上游原自动化配置归档保留，本展示版未新增 GitHub Actions 验收结论。

- 发布副本复验发现 Windows 的全局换行设置把源码与基线转成 CRLF，测试行为未变但 SHA256 改变。新增 `.gitattributes` 固定 LF，并从原提交恢复源文件字节；原本带 CRLF 的上游文件例外保留。该修复不改产品逻辑。

- 通过已连接的 GitHub API 逐一重建 9 个审核快照，每个文件树与本地相同；提交身份及时间不同，因此远端提交 ID 不与本地 ID 混用。初始仓库提交保留在远端历史中。
