# UPSTREAM：上游来源、指纹与改动边界

本文件说明 `wren-tool-output-budget/` 这一工作副本**从哪里来、哪些字节是上游的、哪些是本次改动**。提交历史只代表本工作副本，不代表上游 Git 历史。

## 1. 来源

| 项 | 值 |
|---|---|
| 上游仓库 | https://github.com/Canner/WrenAI |
| 固定 commit | `548eee3e864b11e7f11eee15ae82be178a295f22` |
| 归档 URL | `https://codeload.github.com/Canner/WrenAI/tar.gz/548eee3e864b11e7f11eee15ae82be178a295f22` |
| 归档 SHA256 | `ACA2925DE0FCCB925C15514928CB4B60E7B56908E2ED1C14675086DD4C775CEE` |
| 归档大小 | 13,719,265 B |
| 取得时间 | 2026-11-07（Asia/Shanghai） |
| 取得方式 | `Invoke-WebRequest` 下载 codeload 归档 → `tar -xzf` 解包 → 复制为工作树 |
| 解包目录 | `_downloads/extract/WrenAI-548eee3e.../`（工作树之外，仅作原始证据） |

**事实边界**：工作树来自归档，不是 `git clone`。本机 `git` 可用，但没有使用上游远端历史；本地提交是“在归档快照上做的提交”，不得表述为上游 commit 或已 fork/clone 上游历史，也没有向维护者发过消息或 PR。

## 2. 本地基线提交

```
6d5e83210dd1beee5fea0a90d4986b8efe8aa0ba
chore: vendor WrenAI 548eee3e (sdk/** Apache-2.0) as upstream baseline
```

- 707 个文件，19,722,198 B，与归档解包结果逐字节一致。
- 该提交之前没有任何修改；`git status` 在提交时为干净状态。

## 3. 关键文件指纹（上游原样）

| 文件 | SHA256 | 说明 |
|---|---|---|
| `sdk/wren-langchain/src/wren_langchain/_format.py` | `CEA7814ED569C223E1D5C997197020EF5C4A719DBD3121C32128F5B882B355C4`（6,525 B） | 本次改动的基线；与监控侧冻结副本一致 |
| `docs/evidence/baseline/upstream_format_548eee3e.py` | 同上 | 逐字节副本，复跑时按路径 importlib 加载 |
| `sdk/wren-langchain/pyproject.toml` | `F6DD92BDB06581FE8A8BB8479E05271BE0CED3EB800CE55454E1103A9B509839` | `requires-python >=3.11`，未修改 |
| `sdk/wren-langchain/src/wren_langchain/_tools.py` | `0C3E3243F36CA4E96122545031237BCB94C3A771BECD5B6441E9453197E30AD0` | 调用层，未修改 |
| `sdk/wren-langchain/src/wren_langchain/_tools_memory.py` | `743914AE7FF02CEB40EC4361CF1D833BA61214A2D6F76C721A04035B4F411699` | 调用层，未修改 |
| `AGENTS.md` | `A1CBCFB72BA919649DC8CC127CCCF8EC89D344868725D996F0B33F6409DD3A20` | 已读：指向 `.claude/CLAUDE.md` |
| `.claude/CLAUDE.md` | `286A40DAF91C5DCEFE4DE19634E999A03F08A1A0D84A485AF284ADAEFE33FA8E` | 已读：Conventions + Contribution Bar（先复现再称 bug、诚实标注、测试要真调用） |
| `CONTRIBUTING.md` | `DB5E2A44F9DE8261FF85DA1CE018C615098FECE008D72EBFD3E2694E94273E31` | 已读：conventional commits、ruff（line-length 88 / py3.11）、测试与 lint 必须干净、`sdk/**` 贡献按 Apache-2.0 |
| `LICENSE` | `25CE726569E5C568A00F46133A3F7515A216C6C435F8AA8531EDE1924B0D6309` | 多许可路径映射 |
| `sdk/wren-langchain/LICENSE` | `3DA122EEAEDCA9B81AA873D2CB090C66EEAA1594E776EFAB631FBF0D1CEBFEED` | Apache-2.0 全文，未修改 |

完整清单（含证据文件、工具脚本）见 `docs/evidence/manifest.sha256`。

## 4. 许可

- 改动全部位于 `sdk/**`：该路径按根 `LICENSE` 与 `sdk/wren-langchain/LICENSE` 为 **Apache-2.0**；本次未修改任何 LICENSE/NOTICE，未删除版权头。
- 根 `LICENSE` 是多许可映射：`core/**`、`skills/**`、`examples/**` 为 Apache-2.0，`docs/**` 为 CC BY 4.0。本次新增的 `docs/G2-*.md` 是自撰交付文档，不复制上游 `docs/**` 内容；没有把整库标成 MIT。
- 新增的 `sdk/wren-langchain/src/wren_langchain/_budget.py` 与 `tests/unit/test_format_budget.py` 位于 Apache-2.0 路径下，随该包同许可分发。

## 5. 相对上游的改动

| 类型 | 路径 |
|---|---|
| 修改 | `sdk/wren-langchain/src/wren_langchain/_format.py`（+190 / −62） |
| 新增 | `sdk/wren-langchain/src/wren_langchain/_budget.py` |
| 新增 | `sdk/wren-langchain/tests/unit/test_format_budget.py`（25 个测试） |
| 新增 | `sdk/wren-langchain/tests/integration/test_content_budget_tool.py`（2 个真实工具层用例） |
| 新增（交付工具，非上游） | `tools/g2_cases.py`、`tools/reproduce_g2.py`、`tools/demo_g2.py`、`tools/pytest_upstream_format.py` |
| 新增（交付材料） | `README-G2.md`、`UPSTREAM.md`、`docs/G2-*.md`、`docs/evidence/**` |

未改：`_tools.py`、`_tools_memory.py`、`_envelope.py`、`_toolkit.py`、`wren-pydantic`、Rust `core/**`、依赖清单与版本号。

## 6. 依赖解析记录

`pyproject.toml` 只声明下限（`wrenai>=0.13.1`、`langchain>=1.0` 等），本次解析到的是 2026-11 的索引结果，**不是**上游当年的锁定版本：

| 包 | 版本 |
|---|---|
| CPython | 3.11.15（conda env，源码目录外） |
| wren-langchain | 0.2.3（本工作树，editable） |
| wrenai | 0.17.1 |
| wren-core-py | 0.8.2 |
| langchain / langgraph | 1.4.9 / 1.2.20 |
| pyarrow | 26.0.1 |
| duckdb | 2.0.0 |

完整 `pip freeze` 见 `docs/evidence/env/pip-freeze.txt`。依赖版本差异可能影响上游测试数量，故所有测试/对照都在同一环境内完成，并在交付回执中记录。
