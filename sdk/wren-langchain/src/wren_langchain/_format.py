"""Content formatters per tool. Used by tool wrappers to produce the
LLM-facing ``content`` field of the envelope.

Every formatter routes its output through :mod:`wren_langchain._budget`, so the
16 KiB byte ceiling applies uniformly and includes the footer/marker text that
is appended to truncated output.  Encoded sizes are counted in UTF-8 bytes, not
characters, and text is emitted with ``ensure_ascii=False`` so Chinese and emoji
stay readable (and 2-4x smaller) instead of being escaped.
"""

from __future__ import annotations

import json
from typing import Any

import pyarrow as pa

from wren_langchain._budget import (
    CONTENT_CAP_BYTES,
    fit_blocks,
    fit_text,
    truncate_to_bytes,
    utf8_bytes,
)


def _dump(value: Any) -> tuple[str, int]:
    """JSON-encode *value*; return ``(text, utf8_size)``.

    ``ensure_ascii=False`` keeps non-ASCII text readable.  A lone surrogate in
    the data would make that text unencodable as UTF-8; in that rare case fall
    back to the ASCII-escaping form, which is always valid UTF-8.
    """
    text = json.dumps(value, default=str, ensure_ascii=False)
    try:
        return text, utf8_bytes(text)
    except UnicodeEncodeError:
        text = json.dumps(value, default=str)
        return text, utf8_bytes(text)


def format_query_content(
    table: pa.Table, total_rows: int | None = None
) -> tuple[str, list[str]]:
    """Render query rows as JSON, truncating to fit ``CONTENT_CAP_BYTES``.

    Returns ``(content, warnings)``.  The content is a JSON array of row dicts
    plus an optional ``(showing N of M rows ...)`` footer when truncated.  The
    footer stays *outside* the JSON (the existing contract), so callers split
    body and footer with ``json.JSONDecoder.raw_decode``; ``json.loads`` on the
    whole string was never valid once a footer was present.

    Truncation keeps the **largest ordered prefix of whole rows** that fits, and
    the byte count includes the footer.  A single row too large to show is
    reported as an explicit ``0 of N`` diagnostic rather than a misleading
    ``[]``; a zero-row result whose ``total_rows`` says otherwise is annotated so
    the count cannot be read as "the table is empty".
    """
    rows = table.to_pylist()
    total = len(rows) if total_rows is None else max(int(total_rows), len(rows))

    if not rows:
        if total > 0:
            # Zero returned rows plus an external total is not "no data": say
            # which number came from where instead of returning a bare "[]".
            note = (
                f"\n(0 of {total} rows: the query returned no rows; "
                f"total_rows={total} is an external count, not row data)"
            )
            return "[]" + note, [
                f"query returned 0 rows but total_rows={total}; no rows to display"
            ]
        return "[]", []

    full, full_bytes = _dump(rows)
    if full_bytes <= CONTENT_CAP_BYTES:
        return full, []

    def footer(shown: int, of: int) -> str:
        return (
            f"\n(showing {shown} of {of} rows — content truncated to the "
            f"{CONTENT_CAP_BYTES}-byte cap)"
        )

    # Encode each row once and stop at the first row that cannot fit, so a huge
    # table is never re-encoded as a whole (upstream re-dumped every 25% step).
    parts: list[str] = []
    used = 2  # the enclosing "[" and "]"
    shown = 0
    last = len(rows) - 1
    for index, row in enumerate(rows):
        piece, piece_bytes = _dump(row)
        extra = piece_bytes + (2 if index else 0)  # the ", " separator
        if index == last:
            # Last row: no footer is emitted when everything fits.
            if used + extra <= CONTENT_CAP_BYTES:
                parts.append(piece)
                used += extra
                shown = index + 1
            break
        if used + extra + utf8_bytes(footer(index + 1, total)) <= CONTENT_CAP_BYTES:
            parts.append(piece)
            used += extra
            shown = index + 1
        else:
            break

    if shown == 0:
        row_bytes = _dump(rows[0])[1]
        return (
            f"(0 of {total} rows shown — row 1 alone is {row_bytes} bytes; with "
            f"JSON framing it exceeds the {CONTENT_CAP_BYTES}-byte cap. Use SELECT "
            "to pick fewer / narrower columns, or aggregate in SQL.)",
            [
                f"content truncated: row 1 alone is {row_bytes} bytes; with JSON "
                f"framing it exceeds the {CONTENT_CAP_BYTES}-byte cap, no rows shown."
            ],
        )

    content = "[" + ", ".join(parts) + "]" + footer(shown, total)
    warning = f"content truncated: showed {shown} of {total} rows due to size cap"
    return content, [warning]


def format_dry_plan_content(sql: str) -> str:
    """Wrap dialect SQL in a markdown code fence, capped to the content budget.

    When the SQL does not fit, the fence is closed and an explicit
    ``incomplete SQL`` marker follows, so a truncated plan cannot be mistaken
    for runnable SQL.  The full statement remains available to callers in the
    envelope's ``data.dialect_sql``.
    """
    content = f"```sql\n{sql}\n```"
    if utf8_bytes(content) <= CONTENT_CAP_BYTES:
        return content

    sql_bytes = utf8_bytes(sql)
    opening, closing = "```sql\n", "\n```"
    template = (
        "\n\n[truncated: incomplete SQL — {shown} of {total} bytes shown; "
        "do not execute as-is]"
    )
    budget = CONTENT_CAP_BYTES - utf8_bytes(opening) - utf8_bytes(closing) - 120
    while True:
        head = truncate_to_bytes(sql, max(0, budget))
        candidate = (
            opening
            + head
            + closing
            + template.format(shown=utf8_bytes(head), total=sql_bytes)
        )
        overflow = utf8_bytes(candidate) - CONTENT_CAP_BYTES
        if overflow <= 0:
            return candidate
        budget = max(0, budget - overflow)


def format_fetch_context_content(result: dict[str, Any]) -> str:
    """Render get_context output as readable text, capped to the content budget.

    Strategy ``full`` returns the schema text directly (byte-truncated with the
    existing marker).  Strategy ``search`` returns a numbered list of items;
    when it does not fit, whole items are kept and the omitted count is stated
    instead of cutting a line in half.
    """
    strategy = result.get("strategy")
    if strategy == "full":
        text = result.get("schema", "")
        return fit_text(text, suffix="\n\n...[truncated]")[0]

    items = result.get("results", []) or []
    if not isinstance(items, list) or not items:
        return "_No relevant context items found._"

    lines = []
    n = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        n += 1
        item_type = item.get("item_type", "item")
        name = item.get("name", "")
        summary = item.get("summary") or item.get("text") or ""
        if not isinstance(summary, str):
            summary = str(summary) if summary is not None else ""
        if len(summary) > 120:
            summary = summary[:117] + "..."
        lines.append(f"{n}. [{item_type}] {name} — {summary}")
    if not lines:
        return "_No relevant context items found._"
    return fit_blocks(
        lines, separator="\n", cap=CONTENT_CAP_BYTES, footer=_context_footer
    )[0]


def _context_footer(shown: int, total: int) -> str:
    if shown:
        return f"\n...[truncated: showing {shown} of {total} context items]"
    return (
        f"\n...[truncated: the first of {total} context items exceeds the "
        f"{CONTENT_CAP_BYTES}-byte cap]"
    )


def format_recall_content(rows: list[dict[str, Any]]) -> str:
    """Render recalled NL→SQL pairs as a numbered list with code fences.

    Capped like every other formatter: whole pairs are kept and the number of
    omitted pairs is stated when the list does not fit.
    """
    if not isinstance(rows, list) or not rows:
        return "_No similar past queries found._"

    chunks = []
    n = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        n += 1
        nl = row.get("nl_query") or row.get("nl") or ""
        sql = row.get("sql_query") or row.get("sql") or ""
        chunks.append(f'{n}. "{nl}"\n   ```sql\n   {sql}\n   ```')
    if not chunks:
        return "_No similar past queries found._"
    return fit_blocks(
        chunks, separator="\n", cap=CONTENT_CAP_BYTES, footer=_recall_footer
    )[0]


def _recall_footer(shown: int, total: int) -> str:
    if shown:
        return f"\n...[truncated: showing {shown} of {total} past queries]"
    return (
        f"\n...[truncated: the first of {total} past queries exceeds the "
        f"{CONTENT_CAP_BYTES}-byte cap]"
    )


def format_store_content(nl: str, sql: str, tags: list[str] | None) -> str:
    """One-liner ``Stored: "<nl>" → <sql preview> (N tags)``, capped to budget."""
    # Store tool paths occasionally surface None/placeholders before validation.
    # Coerce so format helpers never TypeError on .strip().
    if not isinstance(nl, str):
        nl = "" if nl is None else str(nl)
    if not isinstance(sql, str):
        sql = "" if sql is None else str(sql)
    sql_preview = sql.strip().split("\n")[0]
    if len(sql_preview) > 80:
        sql_preview = sql_preview[:77] + "..."
    tag_count = len(tags) if isinstance(tags, list) else 0
    text = f'Stored: "{nl}" → {sql_preview} ({tag_count} tags)'
    return fit_text(
        text,
        suffix="\n...[truncated: store confirmation exceeds the content cap]",
    )[0]


def format_list_models_content(manifest: dict[str, Any]) -> str:
    """Render manifest models as a compact markdown table.

    Columns: model | cols | description.  Capped like every other formatter:
    the header survives, whole model rows are kept, and omitted models are
    counted.
    """
    models = manifest.get("models", []) or []
    if not isinstance(models, list) or not models:
        return "_No models defined in this Wren project._"

    lines = []
    any_model = False
    for m in models:
        if not isinstance(m, dict):
            continue
        any_model = True
        name = m.get("name", "")
        cols = m.get("columns", []) or []
        col_count = len(cols) if isinstance(cols, list) else 0
        props = m.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        desc = props.get("description") or m.get("description") or ""
        if not isinstance(desc, str):
            desc = str(desc) if desc is not None else ""
        # Trim long descriptions to keep table compact.
        if len(desc) > 80:
            desc = desc[:77] + "..."
        lines.append(f"| {name} | {col_count} | {desc} |")
    if not any_model:
        return "_No models defined in this Wren project._"

    header = "| model | cols | description |\n|---|---|---|"
    return fit_blocks(
        lines,
        separator="\n",
        cap=CONTENT_CAP_BYTES,
        footer=_models_footer,
        head=header,
    )[0]


def _models_footer(shown: int, total: int) -> str:
    if shown:
        return f"\n...[truncated: showing {shown} of {total} models]"
    return (
        f"\n...[truncated: the first of {total} models exceeds the "
        f"{CONTENT_CAP_BYTES}-byte cap]"
    )
