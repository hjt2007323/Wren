"""Regression tests for the 16 KiB UTF-8 content budget on tool output.

These tests pin the behaviour the G2 change is about:

* every formatter's returned ``content`` stays <= 16384 UTF-8 bytes;
* Chinese and emoji are emitted readably (no ``\\uXXXX`` escaping) and counted
  as bytes, not characters;
* query truncation keeps whole rows, a parseable JSON body and the largest
  ordered prefix that fits;
* the footer / truncation marker is counted in the budget and says what was
  omitted;
* zero rows with an external ``total_rows`` is not silently rendered as ``[]``;
* the public signatures and return shapes are unchanged.
"""

from __future__ import annotations

import inspect
import json
import random

import pyarrow as pa
import pytest

from wren_langchain._budget import (
    fit_blocks,
    fit_text,
    truncate_to_bytes,
    utf8_bytes,
)
from wren_langchain._format import (
    CONTENT_CAP_BYTES,
    format_dry_plan_content,
    format_fetch_context_content,
    format_list_models_content,
    format_query_content,
    format_recall_content,
    format_store_content,
)

CAP = CONTENT_CAP_BYTES
_DECODER = json.JSONDecoder()


def _split_footer(content: str) -> tuple[list, str]:
    rows, end = _DECODER.raw_decode(content)
    return rows, content[end:]


def _bytes(content: str) -> int:
    return len(content.encode("utf-8"))


def _cap_pad_table(extra: int = 0) -> pa.Table:
    """One ASCII row whose JSON array is exactly ``CAP + extra`` bytes."""
    pad = CAP - len(json.dumps([{"pad": ""}])) + extra
    return pa.Table.from_pylist([{"pad": "x" * pad}])


def test_cap_constant_unchanged() -> None:
    assert CAP == 16 * 1024


def test_query_short_result_is_plain_json() -> None:
    table = pa.Table.from_pylist([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])

    content, warnings = format_query_content(table, total_rows=2)

    assert warnings == []
    assert json.loads(content) == table.to_pylist()


def test_query_chinese_is_readable_utf8() -> None:
    table = pa.Table.from_pylist([{"city": "上海浦东新区", "note": "中文内容"}])

    content, warnings = format_query_content(table, total_rows=1)

    assert warnings == []
    assert "\\u" not in content
    assert "上海浦东新区" in content
    # 10 CJK chars: +2 bytes each over their character count.  Escaped they
    # would cost +6 each (60 bytes instead of 20).
    assert _bytes(content) - len(content) == 20


def test_query_emoji_is_not_escaped() -> None:
    content, warnings = format_query_content(pa.Table.from_pylist([{"e": "😀"}]), 1)

    assert warnings == []
    assert "😀" in content
    assert "\\ud83d" not in content


def test_query_exactly_at_cap_is_returned_whole() -> None:
    table = _cap_pad_table()

    content, warnings = format_query_content(table, total_rows=1)

    assert _bytes(content) == CAP
    assert warnings == []
    assert _split_footer(content)[1] == ""


def test_query_one_byte_over_cap_is_truncated_with_reason() -> None:
    content, warnings = format_query_content(_cap_pad_table(extra=1), total_rows=1)

    assert _bytes(content) <= CAP
    assert warnings and "truncated" in warnings[0]
    # A single row that cannot fit must not degrade to a bare "[]".
    assert "0 of 1" in content
    assert "exceeds" in content


def test_query_single_row_larger_than_cap_is_diagnosed() -> None:
    row = {"blob": "y" * 20_000}
    row_bytes = len(json.dumps(row).encode("utf-8"))

    content, warnings = format_query_content(pa.Table.from_pylist([row]), total_rows=1)

    assert _bytes(content) <= CAP
    assert "0 of 1" in content
    assert f"{row_bytes} bytes" in content  # the row's real size, not a guess
    assert warnings


def test_query_truncation_keeps_whole_rows_and_valid_json_prefix() -> None:
    rows = [{"id": i, "name": f"row-{i}"} for i in range(5000)]
    table = pa.Table.from_pylist(rows)

    content, warnings = format_query_content(table, total_rows=len(rows))

    assert _bytes(content) <= CAP
    assert warnings
    body, footer = _split_footer(content)
    assert 0 < len(body) < len(rows)
    assert body == rows[: len(body)]  # complete ordered rows, no partial row
    assert footer.startswith("\n(showing ")
    assert f"of {len(rows)} rows" in footer


def test_query_truncation_uses_most_of_the_budget() -> None:
    table = pa.Table.from_pylist([{"id": i, "name": f"row-{i}"} for i in range(5000)])

    content, _ = format_query_content(table, total_rows=5000)

    # Losing 20% of the cap to a coarse 25% step-down (upstream behaviour) would
    # fail this: the largest fitting prefix must leave less than one row spare.
    assert _bytes(content) > CAP - 128


def test_query_empty_table_has_no_footer() -> None:
    table = pa.table({"id": pa.array([], type=pa.int64())})

    content, warnings = format_query_content(table, total_rows=0)

    assert content == "[]"
    assert warnings == []


def test_query_empty_table_with_external_total_is_explained() -> None:
    content, warnings = format_query_content(pa.table({}), total_rows=100)

    assert _bytes(content) <= CAP
    body, footer = _split_footer(content)
    assert body == []
    assert "0 of 100" in footer
    assert "external count" in footer
    assert warnings


def test_dry_plan_short_is_a_closed_fence() -> None:
    content = format_dry_plan_content("SELECT 1")

    assert content == "```sql\nSELECT 1\n```"


def test_dry_plan_truncation_is_marked_incomplete() -> None:
    sql = (
        "SELECT\n  "
        + ",\n  ".join(f"column_{i}" for i in range(3000))
        + "\nFROM orders"
    )

    content = format_dry_plan_content(sql)

    assert _bytes(content) <= CAP
    assert content.startswith("```sql\n")
    assert content.endswith("]")
    assert "incomplete SQL" in content
    assert "do not execute as-is" in content


def test_fetch_context_full_schema_is_capped() -> None:
    schema = "\n".join(f"TABLE t_{i} (id INT, name VARCHAR)" for i in range(1200))

    content = format_fetch_context_content({"strategy": "full", "schema": schema})

    assert _bytes(content) <= CAP
    assert content.endswith("...[truncated]")


def test_fetch_context_items_are_truncated_on_whole_lines() -> None:
    result = {
        "strategy": "search",
        "results": [
            {"item_type": "column", "name": f"t.c{i}", "summary": "long summary " * 6}
            for i in range(200)
        ],
    }

    content = format_fetch_context_content(result)

    assert _bytes(content) <= CAP
    assert "[truncated: showing" in content
    assert "of 200 context items]" in content
    # Whole items only: every visible line is a complete numbered item.
    footer = content.splitlines()[-1]
    shown = int(footer.split("showing ")[1].split(" of ")[0])
    item_lines = content.splitlines()[:shown]
    assert len(item_lines) == shown
    for line in item_lines:
        assert line[0].isdigit()
        assert line.endswith("long summary " * 6)


def test_recall_is_capped_with_counted_footer() -> None:
    rows = [
        {"nl": f"question {i} " + "上下文 " * 30, "sql": f"SELECT {i} FROM t"}
        for i in range(100)
    ]

    content = format_recall_content(rows)

    assert _bytes(content) <= CAP
    assert "[truncated: showing" in content
    assert "of 100 past queries]" in content


def test_list_models_is_capped_and_keeps_header() -> None:
    manifest = {
        "models": [
            {"name": f"m{i}", "columns": [{}] * 8, "description": "detail " * 12}
            for i in range(300)
        ]
    }

    content = format_list_models_content(manifest)

    assert _bytes(content) <= CAP
    assert content.startswith("| model | cols | description |")
    assert "[truncated: showing" in content
    assert "of 300 models]" in content


def test_store_confirmation_is_capped() -> None:
    content = format_store_content("统计" * 20_000, "SELECT 1", [])

    assert _bytes(content) <= CAP
    assert "truncated" in content


def test_budget_helpers_count_bytes_not_characters() -> None:
    assert utf8_bytes("上海") == 6
    assert utf8_bytes("😀") == 4
    assert utf8_bytes("abc") == 3

    cut = truncate_to_bytes("上海", 4)  # cannot fit two chars in 4 bytes
    assert cut == "上"
    assert len(cut.encode("utf-8")) <= 4


def test_fit_text_reserves_room_for_the_suffix() -> None:
    text, truncated = fit_text("a" * 100, suffix="[tail]", cap=20)

    assert truncated
    assert text.endswith("[tail]")
    assert len(text.encode("utf-8")) <= 20


def test_fit_blocks_keeps_whole_blocks() -> None:
    blocks = [f"block-{i}" for i in range(100)]
    text, shown, truncated = fit_blocks(
        blocks, separator="\n", cap=100, footer=lambda s, t: f"\n({s}/{t})"
    )

    assert truncated
    assert 0 < shown < 100
    assert text.splitlines()[:-1] == blocks[:shown]
    assert text.endswith(f"({shown}/100)")


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_property_budget_holds_for_random_tables(seed: int) -> None:
    rng = random.Random(seed)
    rows = [
        {
            "id": i,
            "text": "".join(
                rng.choice('ab上海😀 \n\t"|') for _ in range(rng.randint(1, 300))
            ),
        }
        for i in range(rng.randint(1, 400))
    ]
    table = pa.Table.from_pylist(rows)

    content, _warnings = format_query_content(table, total_rows=len(rows))

    assert _bytes(content) <= CAP
    body, _footer = _split_footer(content)
    assert body == rows[: len(body)]


def test_formatter_signatures_are_unchanged() -> None:
    expected = {
        "format_query_content": "(table: 'pa.Table', total_rows: 'int | None' = None) -> 'tuple[str, list[str]]'",
        "format_dry_plan_content": "(sql: 'str') -> 'str'",
        "format_fetch_context_content": "(result: 'dict[str, Any]') -> 'str'",
        "format_recall_content": "(rows: 'list[dict[str, Any]]') -> 'str'",
        "format_store_content": "(nl: 'str', sql: 'str', tags: 'list[str] | None') -> 'str'",
        "format_list_models_content": "(manifest: 'dict[str, Any]') -> 'str'",
    }
    actual = {
        "format_query_content": format_query_content,
        "format_dry_plan_content": format_dry_plan_content,
        "format_fetch_context_content": format_fetch_context_content,
        "format_recall_content": format_recall_content,
        "format_store_content": format_store_content,
        "format_list_models_content": format_list_models_content,
    }
    for name, signature in expected.items():
        assert str(inspect.signature(actual[name])) == signature, name
