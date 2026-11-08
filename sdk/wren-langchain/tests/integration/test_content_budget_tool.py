"""End-to-end budget checks through the real LangChain tool wrappers.

The unit tests call the formatters directly; these call the tools an agent calls
(``wren_query`` / ``wren_list_models``) against a real DuckDB-backed project and
assert the envelope contract: ``content`` stays within 16 KiB, the JSON prefix is
whole rows, truncation is self-reported, and the envelope's own ``data`` payload
is unchanged (the cap is a content-layer concern, not an envelope rewrite).
"""

from __future__ import annotations

import json

import duckdb

from wren_langchain import WrenToolkit

CAP = 16 * 1024


def _add_model(project, name: str, table: str, columns: list[dict]) -> None:
    manifest_path = project / "target" / "mdl.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["models"].append(
        {
            "name": name,
            "tableReference": {"catalog": "sample", "schema": "main", "table": table},
            "columns": columns,
            "primaryKey": columns[0]["name"],
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_wren_query_content_capped_on_large_real_result(duckdb_project):
    """400 wide Chinese rows through the real tool: capped, whole rows, readable."""
    con = duckdb.connect(str(duckdb_project / "db" / "sample.duckdb"))
    try:
        con.execute("CREATE TABLE wide(id INTEGER, label VARCHAR)")
        con.executemany(
            "INSERT INTO wide VALUES (?, ?)",
            [(i, f"中文标签 {i} " + "客户要求尽快发货。" * 4) for i in range(400)],
        )
    finally:
        con.close()
    _add_model(
        duckdb_project,
        "wide",
        "wide",
        [{"name": "id", "type": "integer"}, {"name": "label", "type": "varchar"}],
    )

    toolkit = WrenToolkit.from_project(duckdb_project)
    wren_query = next(t for t in toolkit.get_tools() if t.name == "wren_query")

    envelope = wren_query.invoke(
        {"sql": "SELECT id, label FROM wide ORDER BY id", "limit": 400}
    )

    assert envelope["ok"] is True
    content = envelope["content"]
    assert len(content.encode("utf-8")) <= CAP
    assert "\\u" not in content  # Chinese stays readable through the tool path

    rows, end = json.JSONDecoder().raw_decode(content)
    assert 0 < len(rows) < 400
    assert rows == envelope["data"]["rows"][: len(rows)]  # whole ordered rows
    assert "showing" in content[end:]  # truncation is self-reported
    assert envelope["warnings"]

    # Boundary, asserted on purpose: the cap covers `content` only.  `data.rows`
    # still carries every row (bounded by MAX_QUERY_ROWS in the wrapper).
    assert len(envelope["data"]["rows"]) == 400
    assert envelope["data"]["row_count"] == 400
    assert envelope["data"]["content_truncated"] is True


def test_wren_list_models_content_capped_and_header_kept(duckdb_project):
    """A 300-model manifest through the real tool: header kept, footer counted."""
    manifest_path = duckdb_project / "target" / "mdl.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["models"] = [
        {
            "name": f"model_{i:03d}",
            "columns": [{"name": f"c{j}"} for j in range(8)],
            "properties": {"description": "long model description " * 6},
        }
        for i in range(300)
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    toolkit = WrenToolkit.from_project(duckdb_project)
    list_models = next(t for t in toolkit.get_tools() if t.name == "wren_list_models")

    envelope = list_models.invoke({})

    assert envelope["ok"] is True
    content = envelope["content"]
    assert len(content.encode("utf-8")) <= CAP
    assert content.startswith("| model | cols | description |")
    assert "[truncated: showing" in content
    assert len(envelope["data"]["models"]) == 300  # data payload unchanged
