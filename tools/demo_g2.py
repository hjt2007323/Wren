#!/usr/bin/env python3
"""Live demo of the G2 change through the real Wren SDK tool path.

Not a mock: a temporary Wren project is built on top of a real DuckDB file, the
LangChain tools are obtained from ``WrenToolkit.get_tools()`` and invoked as an
agent would invoke them.  The same Arrow table / planned SQL / manifest is then
also rendered by the frozen upstream formatter, so the before/after numbers come
from the *same data*, not from two different fixtures.

Everything is created under the system temp directory and removed afterwards;
the result JSON records whether cleanup succeeded.

    python tools/demo_g2.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from g2_cases import CAP  # noqa: E402

OUT_DIR = ROOT / "docs" / "evidence" / "demo"
BASELINE_FILE = ROOT / "docs" / "evidence" / "baseline" / "upstream_format_548eee3e.py"

CITIES = ["上海", "北京", "深圳", "广州", "杭州"]


def build_project(base: Path) -> tuple[Path, int]:
    """Create a DuckDB file with Chinese content and a matching Wren project."""
    db_dir = base / "db"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "sample.duckdb"

    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE orders("
            "id INTEGER, city VARCHAR, amount DOUBLE, note VARCHAR)"
        )
        rows = [
            (
                i,
                CITIES[i % len(CITIES)],
                round(i * 1.5, 2),
                f"订单备注 {i}：" + "客户要求尽快发货，注意包装。" * 3,
            )
            for i in range(400)
        ]
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", rows)
        count = con.execute("SELECT count(*) FROM orders").fetchone()[0]
    finally:
        con.close()

    manifest = {
        "catalog": "wren",
        "schema": "public",
        "models": [
            {
                "name": "orders",
                "tableReference": {
                    "catalog": "sample",
                    "schema": "main",
                    "table": "orders",
                },
                "columns": [
                    {"name": "id", "type": "integer"},
                    {"name": "city", "type": "varchar"},
                    {"name": "amount", "type": "double"},
                    {"name": "note", "type": "varchar"},
                ],
                "primaryKey": "id",
                "properties": {"description": "演示订单表（中文城市与备注）"},
            }
        ],
    }
    (base / "wren_project.yml").write_text("schema_version: 1\n", encoding="utf-8")
    target = base / "target"
    target.mkdir()
    (target / "mdl.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return db_dir, count


def patch_profile(db_dir: Path) -> None:
    """Point profile resolution at the demo DuckDB directory (as the tests do)."""
    from wren_langchain._providers import connection

    profile = {"datasource": "duckdb", "url": str(db_dir), "format": "duckdb"}
    connection.list_profiles = lambda: {"demo": dict(profile)}
    connection.get_active_profile = lambda: ("demo", dict(profile))


def describe(content: str, warnings: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    record = {
        "content_bytes": len(content.encode("utf-8")),
        "cap_ok": len(content.encode("utf-8")) <= CAP,
        "warnings": warnings,
        "head": content[:220].replace("\n", "\\n"),
        "tail": content[-160:].replace("\n", "\\n"),
    }
    if extra:
        record.update(extra)
    return record


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="g2-demo-"))
    result: dict[str, Any] = {
        "python": sys.version.split()[0],
        "cap_bytes": CAP,
        "workdir": str(workdir),
        "steps": {},
        "cleanup": {},
    }
    exit_code = 0
    toolkit = None
    try:
        db_dir, row_count = build_project(workdir)
        patch_profile(db_dir)

        from wren_langchain import WrenToolkit

        toolkit = WrenToolkit.from_project(workdir)
        tools = {tool.name: tool for tool in toolkit.get_tools()}
        result["tools"] = sorted(tools)
        result["duckdb_rows"] = row_count

        # ── 1. small result: readable Chinese, untruncated ---------------------
        small_envelope = tools["wren_query"].invoke(
            {"sql": "SELECT id, city, note FROM orders WHERE id < 3 ORDER BY id", "limit": 10}
        )
        result["steps"]["wren_query_small_zh"] = describe(
            small_envelope.get("content", ""),
            small_envelope.get("warnings", []),
            {
                "ok": small_envelope.get("ok"),
                "row_count": (small_envelope.get("data") or {}).get("row_count"),
                "error": small_envelope.get("error"),
            },
        )

        # ── 2. big result: capped, maximal prefix ------------------------------
        big_sql = "SELECT id, city, note FROM orders ORDER BY id"
        big_envelope = tools["wren_query"].invoke({"sql": big_sql, "limit": 400})
        big_content = big_envelope["content"]
        big_record = describe(big_content, big_envelope.get("warnings", []))
        parsed, end = json.JSONDecoder().raw_decode(big_content)
        big_record.update(
            {
                "ok": big_envelope["ok"],
                "rows_shown": len(parsed),
                "rows_total": big_envelope["data"]["row_count"],
                "footer": big_content[end:].strip(),
                "first_row_chinese_readable": "上海" in big_content or "北京" in big_content,
                "escaped_unicode": "\\u" in big_content,
            }
        )
        result["steps"]["wren_query_400_rows"] = big_record

        # Same Arrow table through the frozen upstream formatter (A/B, same data).
        table = toolkit.query(big_sql, limit=400)
        baseline = load_baseline()
        before_content, before_warnings = baseline.format_query_content(table, 400)
        try:
            before_rows = len(json.JSONDecoder().raw_decode(before_content)[0])
        except json.JSONDecodeError:
            before_rows = 0
        result["baseline_same_table"] = {
            "content_bytes": len(before_content.encode("utf-8")),
            "cap_ok": len(before_content.encode("utf-8")) <= CAP,
            "rows_shown": before_rows,
            "warnings": before_warnings,
        }
        result["same_table_delta_rows"] = big_record["rows_shown"] - result["baseline_same_table"]["rows_shown"]

        # ── 3. long dry_plan: truncated SQL is marked incomplete ----------------
        long_sql = (
            "SELECT id FROM orders WHERE city IN ("
            + ", ".join(f"'城市{i}'" for i in range(2000))
            + ")"
        )
        plan_envelope = tools["wren_dry_plan"].invoke({"sql": long_sql})
        plan_record = describe(plan_envelope["content"], plan_envelope.get("warnings", []))
        plan_record.update(
            {
                "ok": plan_envelope["ok"],
                "incomplete_marked": "incomplete" in plan_envelope["content"].lower(),
                "dialect_sql_bytes": len(
                    plan_envelope["data"].get("dialect_sql", "").encode("utf-8")
                ),
            }
        )
        if plan_envelope["ok"] and "dialect_sql" in plan_envelope["data"]:
            before_plan = baseline.format_dry_plan_content(plan_envelope["data"]["dialect_sql"])
            plan_record["baseline_same_sql_bytes"] = len(before_plan.encode("utf-8"))
            plan_record["baseline_marked"] = "incomplete" in before_plan.lower()
        result["steps"]["wren_dry_plan_long_sql"] = plan_record

        # ── 4. list_models: unchanged short output ------------------------------
        models_envelope = tools["wren_list_models"].invoke({})
        result["steps"]["wren_list_models"] = describe(
            models_envelope["content"], models_envelope.get("warnings", [])
        )
    except Exception:  # noqa: BLE001 - the failure itself is evidence
        result["error"] = traceback.format_exc()
        exit_code = 2
    finally:
        if toolkit is not None:
            connector = getattr(toolkit, "_connector_cache", None)
            if connector is not None:
                try:
                    connector.close()
                except Exception:  # noqa: BLE001
                    result["cleanup"]["connector_close"] = traceback.format_exc()
        shutil.rmtree(workdir, ignore_errors=True)
        result["cleanup"]["workdir_removed"] = not workdir.exists()

    (OUT_DIR / "demo.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


def load_baseline():
    import importlib.util

    spec = importlib.util.spec_from_file_location("g2_demo_baseline", BASELINE_FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
