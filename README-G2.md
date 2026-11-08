# G2：Wren SDK 工具输出预算（16 KiB UTF-8）与中文保留

固定上游 [Canner/WrenAI](https://github.com/Canner/WrenAI) `548eee3e` 的 `sdk/wren-langchain` 上，
把 6 个 LLM 面向的 `content` 格式化函数统一到**同一套 UTF-8 字节预算**：预算含尾注/截断标记，
中文与 emoji 直出可读，超限时保留**最大有序前缀**并说明省略了什么。

本仓库是上游全量快照 + 本次改动（来源与指纹见 [UPSTREAM.md](UPSTREAM.md)）。改动只在 `sdk/wren-langchain`，
没有改 Rust core、pydantic SDK、依赖清单或数据库权限。

## 结果速览（同一数据、同一解释器、同一 pyarrow）

| 场景 | 上游 | 本次 | 变化 |
|---|---|---|---|
| 10 行中文 JSON | 950 B，`\uXXXX` 转义不可读 | 650 B，中文可读 | −31.6% |
| 5000 行短行（超限） | 保留 213 行 / 12,899 B（用掉 78.7% 预算） | 保留 268 行 / 16,381 B（99.98%） | +25.8% 行 |
| 1000 行中文（超限） | 135 行 / 14,632 B | 224 行 / 16,313 B | +65.9% 行 |
| 40 KB `dry_plan` SQL | 43,918 B，无任何“不完整”标记 | 16,346 B，标记 `incomplete … do not execute as-is` | 强制入预算 |
| 空表 + `total_rows=100` | `[]`，无尾注无 warning | `[]` + `0 of 100 … external count` | 不再误导 |
| 组件耗时（5000 行 × 6 列，30 次中位数） | 30.7 ms | 10.3 ms | 3.0× 快 |

完整 before/after 见 [docs/G2-交付.md](docs/G2-交付.md) 与 `docs/evidence/`。

## 一键复跑

```bash
# 0) 环境：CPython >= 3.11（示例 env 在源码目录外）
python -m venv .venv && .venv/Scripts/pip install -e sdk/wren-langchain pytest pytest-mock
#    Windows 下 sdk/wren-langchain 会拉 wrenai / langchain / langgraph / pyarrow，约 200 MB

# 1) before/after 全量对照 + 硬门槛（exit 1 = 有门槛失败）
python tools/reproduce_g2.py --side both --check

# 2) 组件性能（固定数据、30 次，报中位数与 min/max）
python tools/reproduce_g2.py --side both --bench --bench-repeat 30

# 3) 终端里看关键差异（中文/emoji/截断/空表/超长 SQL）
python tools/reproduce_g2.py --demo

# 4) 真实 SDK 工具路径演示：临时 Wren + DuckDB 项目，调用 wren_query / wren_dry_plan / wren_list_models
python tools/demo_g2.py

# 5) 测试（157 passed / 2 slow 跳过）
cd sdk/wren-langchain && python -m pytest tests -q

# 6) 红测：同一批新测试跑在冻结上游上（预期 10 failed / 15 passed）
#    回到仓库根目录后执行；PowerShell 用 $env:PYTHONPATH="tools" 代替前缀
PYTHONPATH=tools python -m pytest sdk/wren-langchain/tests/unit/test_format_budget.py \
  -q -p pytest_upstream_format
```

`reproduce_g2.py` 的 `before` 侧不是复制实现：它用 `importlib` 按路径加载
`docs/evidence/baseline/upstream_format_548eee3e.py`（上游 `_format.py` 的逐字节副本，
SHA256 `CEA7814E…`），`after` 侧加载工作树里的真实模块。

## 目录

```
sdk/wren-langchain/src/wren_langchain/_budget.py     # 新增：共享 UTF-8 字节预算
sdk/wren-langchain/src/wren_langchain/_format.py     # 修改：6 个格式化函数
sdk/wren-langchain/tests/unit/test_format_budget.py  # 新增：25 个边界回归
sdk/wren-langchain/tests/integration/test_content_budget_tool.py  # 新增：2 个真实工具层用例
tools/pytest_upstream_format.py                      # 红测插件（换成冻结上游）
tools/g2_cases.py                                    # 冻结用例表（23 例 + 性能数据）
tools/reproduce_g2.py                                # 一键 before/after + 门槛 + 基准 + demo
tools/demo_g2.py                                     # 真实 SDK/DuckDB 演示
docs/G2-用例表与基线预期.md                            # 改代码前冻结的输入与预期
docs/G2-交付.md                                       # 交付回执（改了什么/数字/限制/证据）
docs/G2-验收对照表.md                                   # W1–W8 与硬门槛 → 证据/命令 的一页对照
docs/面试材料-G2.md                                    # 一页面试材料 + 3 分钟演示说明
docs/evidence/{baseline,after,tests,demo,env}/       # 原始证据与 manifest
```

## 边界（别过度声称）

- 只保证**本格式化函数返回的 `content` 字符串** ≤ 16 KiB；外层工具信封（`data.rows` 等）不在该 cap 内。
- 已在本机验证 SDK 整包（unit + conformance + real-DuckDB integration）；**未**部署 Wren 平台/数据库服务，
  未跑真实 LLM agent，未安装 memory extra（LanceDB/sentence-transformers），未调用付费模型。
- 性能只是组件级测量，不能推断“整体 Agent 提速”。
- 许可：`sdk/**` Apache-2.0；`docs/**` 上游为 CC BY 4.0，本次新增文档为自撰。
