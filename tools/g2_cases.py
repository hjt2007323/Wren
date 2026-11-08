"""Frozen input table for the G2 content-budget before/after comparison.

Every case is a real call into a real formatter (never a copy of it) plus the
checks the reproducer applies to whatever that formatter returns.  The table is
frozen *before* the first edit: the same inputs run against the frozen upstream
module and against the patched module, on the same interpreter and pyarrow.

Contract under test (upstream commit 548eee3e864b11e7f11eee15ae82be178a295f22):

* ``CAP = 16 * 1024`` UTF-8 **bytes** on the returned ``content`` string;
* ``format_query_content`` returns ``(content, warnings)`` where content is a
  JSON array of row dicts plus an optional ``(showing N of M rows)`` footer;
* the other five formatters return a plain string;
* function names, signatures and return shapes must not change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

CAP = 16 * 1024

# Payload length that makes ``json.dumps([{"pad": "<x>" * n}])`` exactly CAP
# bytes.  ``json.dumps`` on this pure-ASCII row is identical with and without
# ``ensure_ascii``, so the same integer exercises both modules.
_CAP_PAD = CAP - len(json.dumps([{"pad": ""}]))


@dataclass(frozen=True)
class Case:
    """One formatter call plus the checks its output must satisfy."""

    id: str
    tool: str  # query | dry_plan | recall | list_models | fetch_context | store
    args: dict[str, Any]
    checks: tuple[str, ...]
    note: str = ""
    expected: dict[str, Any] = field(default_factory=dict)


def _query(table: pa.Table, total_rows: int | None, *checks: str) -> dict[str, Any]:
    return {"table": table, "total_rows": total_rows, "checks": checks}


def build_cases() -> list[Case]:
    """Return the frozen case list, in report order."""
    zh_rows = [{"id": i, "city": "上海浦东新区", "note": "中文内容"} for i in range(10)]
    zh_1000 = [
        {"id": i, "city": "上海浦东新区", "note": "中文内容保留"} for i in range(1000)
    ]
    long_rows = [
        {"id": i, "name": f"row-{i}", "score": i * 0.5, "flag": i % 2 == 0}
        for i in range(5000)
    ]
    special_rows = [
        {"text": "line1\nline2", "sym": "```sql", "pipe": "| a | b |"},
        {"text": "tab\there", "sym": "back\\slash", "pipe": "quote \" and '"},
        {"text": "crlf\r\nend", "sym": "back\\slash2", "pipe": "ascii only"},
    ]
    multilingual_rows = [
        {"text": "中文\n换行", "sym": "```sql", "pipe": "| 城市 | 订单 |"},
        {"text": "emoji 😀🎉", "sym": "tab\there", "pipe": "引号 \" 和 '"},
        {"text": "crlf\r\n中文", "sym": "back\\slash", "pipe": "混合 mixed"},
    ]

    en_table = pa.Table.from_pylist(
        [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}, {"id": 3, "name": "carol"}]
    )
    zh_table = pa.Table.from_pylist(zh_rows)
    emoji_table = pa.Table.from_pylist([{"emoji": "😀"}, {"emoji": "🎉"}, {"emoji": "🚀"}])
    cap_table = pa.Table.from_pylist([{"pad": "x" * _CAP_PAD}])
    over_table = pa.Table.from_pylist([{"pad": "x" * (_CAP_PAD + 1)}])
    huge_table = pa.Table.from_pylist([{"blob": "y" * 20_000}])
    empty_table = pa.Table.from_pylist([])  # 0 rows, 0 columns
    empty_one_col = pa.table({"id": pa.array([], type=pa.int64())})
    long_table = pa.Table.from_pylist(long_rows)
    zh_1000_table = pa.Table.from_pylist(zh_1000)
    special_table = pa.Table.from_pylist(special_rows)
    multilingual_table = pa.Table.from_pylist(multilingual_rows)

    recall_short = [
        {"nl": "List orders", "sql": "SELECT 1"},
        {"nl": "Count customers", "sql": "SELECT count(*) FROM customers"},
    ]
    recall_long = [
        {
            "nl": f"Question {i}: 统计每个城市的订单数量并按金额排序（示例自然语言问题，用于 recall 长输出）。",
            "sql": (
                "SELECT city, count(*) AS orders, sum(amount) AS total "
                f"FROM orders WHERE city <> 'city-{i}' GROUP BY city ORDER BY total DESC"
            ),
        }
        for i in range(100)
    ]
    models_short = {
        "models": [
            {
                "name": "orders",
                "columns": [{"name": "id"}, {"name": "customer"}],
                "properties": {"description": "Customer orders"},
            },
            {"name": "customers", "columns": [{"name": "id"}]},
        ]
    }
    models_long = {
        "models": [
            {
                "name": f"model_{i:03d}",
                "columns": [{"name": f"c{j}"} for j in range(8)],
                "properties": {
                    "description": f"Long description for model {i}: " + "detail " * 8
                },
            }
            for i in range(300)
        ]
    }
    fetch_short = {
        "strategy": "search",
        "results": [
            {"item_type": "model", "name": "orders", "summary": "Orders table"},
            {"item_type": "column", "name": "orders.id", "summary": "Primary key"},
        ],
    }
    fetch_schema_long = {
        "strategy": "full",
        "schema": "\n".join(
            f"TABLE table_{i} (id INT, name VARCHAR(255), created_at TIMESTAMP)" for i in range(1200)
        ),
    }
    fetch_items_long = {
        "strategy": "search",
        "results": [
            {
                "item_type": "column",
                "name": f"orders.column_{i}",
                "summary": "semantic description text that is deliberately long " * 4,
            }
            for i in range(200)
        ],
    }

    return [
        Case(
            id="Q1_en_short",
            tool="query",
            args=_query(en_table, 3),
            checks=("cap", "full_json", "no_truncation"),
            note="正向控制：3 行英文，未超限，输出应与上游逐字节一致",
            expected={"rows": en_table.to_pylist()},
        ),
        Case(
            id="Q2_zh_10",
            tool="query",
            args=_query(zh_table, 10),
            checks=("cap", "full_json", "no_truncation", "zh_readable"),
            note="10 行中文：上游 \\uXXXX 转义，修后应为可读 UTF-8",
            expected={"rows": zh_table.to_pylist()},
        ),
        Case(
            id="Q3_emoji",
            tool="query",
            args=_query(emoji_table, 3),
            checks=("cap", "full_json", "no_truncation", "emoji_readable"),
            note="emoji：上游代理对转义 12 B，修后 4 B",
            expected={"rows": emoji_table.to_pylist()},
        ),
        Case(
            id="Q4_cap_exact",
            tool="query",
            args=_query(cap_table, 1),
            checks=("cap", "exact_cap"),
            note="恰好 16384 B 必须放行，不得截断",
            expected={"rows": cap_table.to_pylist(), "content": json.dumps([{"pad": "x" * _CAP_PAD}])},
        ),
        Case(
            id="Q5_cap_over_1",
            tool="query",
            args=_query(over_table, 1),
            checks=("cap", "over_cap_truncated"),
            note="16385 B：必须截断且总字节 <= 16384",
            expected={"rows": over_table.to_pylist()},
        ),
        Case(
            id="Q6_single_row_20k",
            tool="query",
            args=_query(huge_table, 1),
            checks=("cap", "single_row_diag"),
            note="单行 20 KB：必须明确 0 of 1 的原因，不能只回 []",
            expected={"rows": huge_table.to_pylist()},
        ),
        Case(
            id="Q7_empty_plain",
            tool="query",
            args=_query(empty_one_col, 0),
            checks=("cap", "empty_plain"),
            note="普通空表（0 行 0 列之外：1 列 0 行）：应返回 [] 且无尾注",
            expected={"rows": []},
        ),
        Case(
            id="Q8_empty_total_100",
            tool="query",
            args=_query(empty_table, 100),
            checks=("cap", "empty_total_diag"),
            note="空表 + total_rows=100：上游只回 [] 且无 warning，修后必须说明 0 of 100",
            expected={"rows": []},
        ),
        Case(
            id="Q9_5000_rows",
            tool="query",
            args=_query(long_table, 5000),
            checks=("cap", "truncated_json", "maximal_prefix"),
            note="5000 短行：验证最大有序前缀与字节利用率",
            expected={"rows": long_table.to_pylist()},
        ),
        Case(
            id="Q10_zh_1000",
            tool="query",
            args=_query(zh_1000_table, 1000),
            checks=("cap", "truncated_json", "maximal_prefix", "zh_kept"),
            note="1000 行中文：修后同字节预算应保留更多行",
            expected={"rows": zh_1000_table.to_pylist()},
        ),
        Case(
            id="Q11_special_chars",
            tool="query",
            args=_query(special_table, 3),
            checks=("cap", "full_json", "data_intact"),
            note="换行/围栏/表格/引号/反斜杠（纯 ASCII）：JSON 原样往返，且应与上游逐字节一致",
            expected={"rows": special_table.to_pylist()},
        ),
        Case(
            id="Q12_special_zh",
            tool="query",
            args=_query(multilingual_table, 3),
            checks=("cap", "full_json", "data_intact", "zh_readable"),
            note="中文/emoji 与特殊字符混排：可读 UTF-8，JSON 仍原样往返",
            expected={"rows": multilingual_table.to_pylist()},
        ),
        Case(
            id="D1_dry_short",
            tool="dry_plan",
            args={"sql": "WITH cte_orders AS (SELECT id FROM orders) SELECT * FROM cte_orders"},
            checks=("cap", "no_truncation"),
            note="正常 SQL：围栏输出应与上游一致",
            expected={},
        ),
        Case(
            id="D2_dry_huge",
            tool="dry_plan",
            args={
                "sql": "SELECT\n  "
                + ",\n  ".join(f"column_{i}" for i in range(3000))
                + "\nFROM orders"
            },
            checks=("cap", "dry_plan_marked"),
            note="超长 SQL：必须截断并标明不完整，不能静默冒充完整 SQL",
            expected={},
        ),
        Case(
            id="R1_recall_short",
            tool="recall",
            args={"rows": recall_short},
            checks=("cap", "no_truncation"),
            note="2 条召回：输出应与上游一致",
            expected={},
        ),
        Case(
            id="R2_recall_long",
            tool="recall",
            args={"rows": recall_long},
            checks=("cap", "recall_capped"),
            note="100 条长召回：上游无上限，修后统一 cap 并标明截断",
            expected={},
        ),
        Case(
            id="L1_models_short",
            tool="list_models",
            args={"manifest": models_short},
            checks=("cap", "no_truncation"),
            note="2 个模型：输出应与上游一致",
            expected={},
        ),
        Case(
            id="L2_models_long",
            tool="list_models",
            args={"manifest": models_long},
            checks=("cap", "models_capped"),
            note="300 个模型：上游无上限，修后统一 cap",
            expected={},
        ),
        Case(
            id="F1_fetch_short",
            tool="fetch_context",
            args={"result": fetch_short},
            checks=("cap", "no_truncation"),
            note="短检索结果：输出应与上游一致",
            expected={},
        ),
        Case(
            id="F2_fetch_schema_long",
            tool="fetch_context",
            args={"result": fetch_schema_long},
            checks=("cap", "fetch_capped"),
            note="长 schema：上游已按字节截断（正向控制）",
            expected={},
        ),
        Case(
            id="F3_fetch_items_long",
            tool="fetch_context",
            args={"result": fetch_items_long},
            checks=("cap", "fetch_capped"),
            note="200 条检索项：修后按整行截断并说明省略数量",
            expected={},
        ),
        Case(
            id="S1_store_short",
            tool="store",
            args={"nl": "List orders", "sql": "SELECT 1\nFROM t", "tags": ["a", "b"]},
            checks=("cap", "store_exact"),
            note="正常 store：输出应与上游逐字节一致",
            expected={"content": 'Stored: "List orders" → SELECT 1 (2 tags)'},
        ),
        Case(
            id="S2_store_long",
            tool="store",
            args={"nl": "统计每个城市的订单量并给出环比" * 800, "sql": "SELECT 1", "tags": []},
            checks=("cap", "store_capped"),
            note="超长 nl：上游不设限，修后也纳入统一预算",
            expected={},
        ),
    ]


# Cases whose *untruncated* output must stay byte-identical to upstream.  These
# are the backward-compatibility controls; the reproducer compares the sha256
# of both sides for them.
COMPAT_EXACT_IDS = (
    "Q1_en_short",
    "Q4_cap_exact",
    "Q7_empty_plain",
    "Q11_special_chars",
    "D1_dry_short",
    "R1_recall_short",
    "L1_models_short",
    "F1_fetch_short",
    "S1_store_short",
)


def perf_tables() -> dict[str, pa.Table]:
    """Fixed inputs for the component performance measurement.

    * ``over_cap_5000`` — 5000 rows x 6 columns (incl. Chinese), far over the cap;
      exercises the truncation path that upstream re-encodes on every 25% step.
    * ``over_cap_1000`` — 1000 rows, still over the cap, smaller absolute cost.
    * ``under_cap_200`` — 200 rows, under the cap: the fast path both sides share.
    """
    over = pa.Table.from_pylist(
        [
            {
                "id": i,
                "customer": f"customer-{i % 97}",
                "city": "上海",
                "amount": i * 1.25,
                "status": "paid",
                "note": f"order note {i}",
            }
            for i in range(5000)
        ]
    )
    mid = pa.Table.from_pylist(
        [{"id": i, "name": f"row-{i}", "score": i * 0.5} for i in range(1000)]
    )
    small = pa.Table.from_pylist(
        [{"id": i, "name": f"row-{i}", "score": i * 0.5} for i in range(200)]
    )
    return {"over_cap_5000": over, "over_cap_1000": mid, "under_cap_200": small}
