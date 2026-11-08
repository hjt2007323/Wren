# Wren Agent 工具输出：16 KiB 预算与中文保留

基于 Wren SDK 的固定版本，用 AI 辅助开发改进面向模型的工具输出：**按 UTF-8 字节限长，中文和 emoji 保持可读，截断时说明省略内容**。

上游：[Canner/WrenAI](https://github.com/Canner/WrenAI)，固定提交 `548eee3e864b11e7f11eee15ae82be178a295f22`。本次改动位于 Apache-2.0 的 `sdk/wren-langchain`，是组件改进。原项目说明见 [README-UPSTREAM.md](README-UPSTREAM.md)，来源见 [UPSTREAM.md](UPSTREAM.md)，路径许可见 [LICENSE](LICENSE)。

## 改了什么

- 6 个工具内容格式化函数统一 **16 KiB = 16,384 字节**预算，尾注计入预算；这不是 token 上限。
- 中文与 emoji 原样输出，超长查询结果保留尽可能多的完整前缀行，保持各函数既有签名与返回类型。
- 超长 SQL 明确标记不完整，空表但外部总数非零时解释计数差异。
- 新增 25 例边界回归与 2 例工具层集成测试，保留新测试在冻结上游失败的红测记录。

## 验证结果

| 同一固定输入 | 上游 | 改进后 |
|---|---|---|
| 10 行中文 JSON | 950 B，Unicode 转义 | 650 B，中文可读 |
| 1000 行中文超限输出 | 135 行 / 14,632 B | 224 行 / 16,313 B |
| 40 KB dry-plan SQL | 43,918 B，无不完整标记 | 16,346 B，标记不完整 |
| 固定 23 例的失败门槛 | 15 个门槛失败，分布于 10 例 | 0 个门槛失败 |
| 同批 25 例新测试 | 10 failed / 15 passed | 25 passed |

交付记录另有 SDK 测试 **157 passed、2 deselected**，及临时真实 DuckDB → WrenToolkit 工具调用演示。独立复验 R1（2026-11-07）accepted。详见 [README-G2.md](README-G2.md)、[交付记录](docs/G2-交付.md)、[PUBLICATION.md](PUBLICATION.md)。

## 本地复现

先创建并激活虚拟环境。下列 `python` 指虚拟环境解释器：Windows 为 `.venv/Scripts/python.exe`，Linux/macOS 为 `.venv/bin/python`。

```bash
python -m venv .venv
# 激活虚拟环境后执行
python -m pip install -e sdk/wren-langchain pytest pytest-mock pyarrow
python tools/reproduce_g2.py --side both --check --out reproduce-output
python -m pytest sdk/wren-langchain/tests/unit/test_format_budget.py -q
python tools/demo_g2.py
```

安装涉及 Wren、LangChain 与 PyArrow，已测环境见 `docs/evidence/env/`。无需模型密钥，演示使用临时 DuckDB，不调用付费模型。

## 阅读代码

- [共享预算模块](sdk/wren-langchain/src/wren_langchain/_budget.py)
- [6 个格式化函数](sdk/wren-langchain/src/wren_langchain/_format.py)
- [25 例边界回归](sdk/wren-langchain/tests/unit/test_format_budget.py)
- [真实工具层测试](sdk/wren-langchain/tests/integration/test_content_budget_tool.py)
- [一键对照](tools/reproduce_g2.py)

**范围**：只限制格式化函数返回的 `content`，外层信封和 `data.rows` 不在上限内。未验证真实 LLM 效果、memory 向量检索或整个平台部署；组件性能不代表整体 Agent 延迟或模型费用。上游发行工作流归档于 `.github/upstream-workflows/`，本轮没有修改产品逻辑；新增 `.gitattributes` 固定发布副本行尾，防止 Windows 克隆改变源码及证据指纹。
