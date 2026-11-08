#!/usr/bin/env python3
"""One-click before/after reproduction for the G2 Wren SDK content-budget work.

Runs the frozen case table (``tools/g2_cases.py``) against two implementations of
``wren_langchain/_format.py``:

* ``before`` — the byte-frozen upstream file, loaded from
  ``docs/evidence/baseline/upstream_format_548eee3e.py`` by path;
* ``after``  — the working tree at ``sdk/wren-langchain/src/...``.

Both are real modules: nothing is copied, stubbed or re-implemented.  The only
isolation is ``wren_langchain/__init__.py`` (it imports langchain/wrenai), which
is bypassed with an empty package shell so the formatter module can be loaded
without the rest of the SDK.

Examples
--------
    python tools/reproduce_g2.py --side before --out docs/evidence
    python tools/reproduce_g2.py --side both --check
    python tools/reproduce_g2.py --bench --bench-repeat 20
    python tools/reproduce_g2.py --demo

Exit code is non-zero when ``--check`` is given and a gate fails on the side
being checked (``after`` when both sides run).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import importlib
import importlib.util
import json
import platform
import statistics
import sys
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "sdk" / "wren-langchain" / "src"
BASELINE_FILE = ROOT / "docs" / "evidence" / "baseline" / "upstream_format_548eee3e.py"

sys.path.insert(0, str(ROOT / "tools"))

from g2_cases import (  # noqa: E402  (path bootstrap must run first)
    CAP,
    COMPAT_EXACT_IDS,
    Case,
    build_cases,
    perf_tables,
)

FORMATTERS = (
    "format_query_content",
    "format_dry_plan_content",
    "format_fetch_context_content",
    "format_recall_content",
    "format_store_content",
    "format_list_models_content",
)

# ``before`` results live next to the frozen upstream source they came from.
SIDE_DIRS = {"before": "baseline", "after": "after"}


# --------------------------------------------------------------------------
# module loading
# --------------------------------------------------------------------------


def load_baseline_module():
    if not BASELINE_FILE.is_file():
        raise SystemExit(f"missing frozen baseline: {BASELINE_FILE}")
    spec = importlib.util.spec_from_file_location("g2_baseline_format", BASELINE_FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_after_module():
    """Import ``wren_langchain._format`` from the working tree.

    ``wren_langchain/__init__.py`` pulls langchain/wrenai; an empty package shell
    with the real ``__path__`` lets the submodule import resolve normally (its
    relative ``._budget`` import included) without executing that __init__.
    """
    if "wren_langchain" not in sys.modules:
        shell = types.ModuleType("wren_langchain")
        shell.__path__ = [str(SRC / "wren_langchain")]
        shell.__package__ = "wren_langchain"
        sys.modules["wren_langchain"] = shell
    return importlib.import_module("wren_langchain._format")


def module_path(module) -> str:
    return getattr(module, "__file__", "<unknown>")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


# --------------------------------------------------------------------------
# running cases
# --------------------------------------------------------------------------


@dataclass
class Observation:
    case: Case
    side: str
    content: str
    warnings: list[str]
    elapsed_ms: float
    error: str | None = None
    parsed: Any = None
    footer: str = ""
    json_error: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)

    @property
    def utf8_bytes(self) -> int:
        return len(self.content.encode("utf-8"))

    @property
    def truncated(self) -> bool:
        return bool(self.warnings)

    @property
    def rows_shown(self) -> int | None:
        if self.parsed is None:
            return None
        return len(self.parsed) if isinstance(self.parsed, list) else None

    @property
    def rows_total(self) -> int:
        if self.case.tool == "query":
            total = self.case.args.get("total_rows")
            rows = len(self.case.args["table"])
            return max(total if total is not None else rows, rows)
        return 0


def parse_query_content(content: str) -> tuple[Any, str, str | None]:
    """Split ``JSON body [+ footer]`` exactly the way the contract describes."""
    decoder = json.JSONDecoder()
    try:
        body, end = decoder.raw_decode(content)
    except json.JSONDecodeError as exc:
        return None, "", str(exc)
    if not isinstance(body, list):
        return None, "", "body is not a JSON array"
    return body, content[end:], None


def run_case(module, case: Case, side: str) -> Observation:
    args = case.args
    started = time.perf_counter()
    try:
        if case.tool == "query":
            content, warnings = module.format_query_content(args["table"], args["total_rows"])
        elif case.tool == "dry_plan":
            content, warnings = module.format_dry_plan_content(args["sql"]), []
        elif case.tool == "recall":
            content, warnings = module.format_recall_content(args["rows"]), []
        elif case.tool == "list_models":
            content, warnings = module.format_list_models_content(args["manifest"]), []
        elif case.tool == "fetch_context":
            content, warnings = module.format_fetch_context_content(args["result"]), []
        elif case.tool == "store":
            content, warnings = (
                module.format_store_content(args["nl"], args["sql"], args["tags"]),
                [],
            )
        else:  # pragma: no cover - guarded by the frozen table
            raise ValueError(f"unknown tool {case.tool!r}")
    except Exception as exc:  # noqa: BLE001 - an exception is itself a finding
        elapsed = (time.perf_counter() - started) * 1000
        return Observation(case=case, side=side, content="", warnings=[], elapsed_ms=elapsed, error=repr(exc))
    elapsed = (time.perf_counter() - started) * 1000

    obs = Observation(
        case=case,
        side=side,
        content=content,
        warnings=list(warnings),
        elapsed_ms=elapsed,
    )
    if case.tool == "query":
        obs.parsed, obs.footer, obs.json_error = parse_query_content(content)
    return obs


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------


def _normalize_rows(rows: list[Any]) -> Any:
    return json.loads(json.dumps(rows, default=str, ensure_ascii=False))


def _next_row_bytes(case: Case, shown: int) -> int:
    table = case.args["table"]
    rows = table.to_pylist()
    return len(json.dumps(rows[shown], default=str, ensure_ascii=False).encode("utf-8"))


def check(case: Case, obs: Observation) -> tuple[dict[str, bool], list[str]]:
    content = obs.content
    results: dict[str, bool] = {}
    failed: list[str] = []

    def record(name: str, ok: bool) -> None:
        results[name] = bool(ok)
        if not ok:
            failed.append(name)

    for name in case.checks:
        if name == "cap":
            record(name, obs.utf8_bytes <= CAP)
        elif name == "no_truncation":
            record(name, not obs.warnings and obs.utf8_bytes <= CAP)
        elif name == "full_json":
            expected = _normalize_rows(case.expected["rows"])
            record(name, obs.json_error is None and not obs.footer.strip() and obs.parsed == expected)
        elif name == "exact_cap":
            expected = case.expected["content"]
            record(name, obs.utf8_bytes == CAP and not obs.warnings and content == expected)
        elif name == "over_cap_truncated":
            record(name, obs.truncated and obs.utf8_bytes <= CAP)
        elif name == "single_row_diag":
            record(name, "0 of 1" in content and "exceeds" in content.lower() and obs.utf8_bytes <= CAP)
        elif name == "empty_plain":
            record(name, content == "[]" and not obs.warnings)
        elif name == "empty_total_diag":
            record(name, "0 of 100" in content and obs.truncated and obs.utf8_bytes <= CAP)
        elif name == "truncated_json":
            ok = (
                obs.json_error is None
                and obs.parsed is not None
                and 0 < len(obs.parsed) < obs.rows_total
                and bool(obs.footer.strip())
                and obs.utf8_bytes <= CAP
            )
            record(name, ok)
        elif name == "maximal_prefix":
            ok = False
            if obs.json_error is None and obs.parsed is not None and 0 < len(obs.parsed) < obs.rows_total:
                extra = 2 + _next_row_bytes(case, len(obs.parsed))
                ok = obs.utf8_bytes + extra > CAP
            record(name, ok)
        elif name == "zh_readable":
            record(name, "\\u" not in content and any("\u4e00" <= ch <= "\u9fff" for ch in content))
        elif name == "zh_kept":
            ok = obs.json_error is None and obs.parsed is not None and "\\u" not in content
            if ok:
                ok = all("上海" in str(row.get("city", "")) for row in obs.parsed)
            record(name, ok)
        elif name == "emoji_readable":
            record(name, "😀" in content and "\\u" not in content)
        elif name == "data_intact":
            expected = _normalize_rows(case.expected["rows"])
            record(name, obs.json_error is None and obs.parsed == expected)
        elif name == "dry_plan_marked":
            record(
                name,
                content.startswith("```sql")
                and "incomplete" in content.lower()
                and obs.utf8_bytes <= CAP,
            )
        elif name == "recall_capped":
            record(name, obs.utf8_bytes <= CAP and "truncated" in content.lower())
        elif name == "models_capped":
            record(name, obs.utf8_bytes <= CAP and "truncated" in content.lower())
        elif name == "fetch_capped":
            record(name, obs.utf8_bytes <= CAP)
        elif name == "store_exact":
            record(name, content == case.expected["content"])
        elif name == "store_capped":
            record(name, obs.utf8_bytes <= CAP)
        else:  # pragma: no cover - typo guard
            raise ValueError(f"unknown check {name!r} in case {case.id}")

    return results, failed


# --------------------------------------------------------------------------
# evidence writing
# --------------------------------------------------------------------------


def env_fingerprint(modules: dict[str, Any]) -> dict[str, Any]:
    import pyarrow as pa

    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "pyarrow": pa.__version__,
        "platform": platform.platform(),
        "cap_bytes": CAP,
        "modules": {
            side: {"path": module_path(mod), "sha256": sha256_bytes(Path(module_path(mod)).read_bytes())}
            for side, mod in modules.items()
        },
    }


def write_side(out_root: Path, side: str, module, observations: list[Observation], env: dict[str, Any]):
    side_dir = out_root / SIDE_DIRS.get(side, side)
    content_dir = side_dir / "content"
    content_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for obs in observations:
        (content_dir / f"{obs.case.id}.txt").write_text(obs.content, encoding="utf-8", newline="")
        records.append(
            {
                "case": obs.case.id,
                "tool": obs.case.tool,
                "note": obs.case.note,
                "utf8_bytes": obs.utf8_bytes,
                "over_cap": obs.utf8_bytes > CAP,
                "warnings": obs.warnings,
                "truncated": obs.truncated,
                "rows_shown": obs.rows_shown,
                "rows_total": obs.rows_total,
                "footer": obs.footer.strip()[:200],
                "json_ok": obs.json_error is None,
                "json_error": obs.json_error,
                "content_sha256": sha256_text(obs.content),
                "checks": obs.checks,
                "failed_checks": obs.failed,
                "error": obs.error,
            }
        )

    payload = {"side": side, "module": env["modules"][side], "environment": env, "cases": records}
    (side_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline=""
    )

    with (side_dir / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case",
                "tool",
                "utf8_bytes",
                "over_cap",
                "truncated",
                "rows_shown",
                "rows_total",
                "json_ok",
                "content_sha256",
                "failed_checks",
            ]
        )
        for rec in records:
            writer.writerow(
                [
                    rec["case"],
                    rec["tool"],
                    rec["utf8_bytes"],
                    rec["over_cap"],
                    rec["truncated"],
                    "" if rec["rows_shown"] is None else rec["rows_shown"],
                    rec["rows_total"],
                    rec["json_ok"],
                    rec["content_sha256"],
                    ";".join(rec["failed_checks"]),
                ]
            )
    return records


def print_table(by_side: dict[str, list[dict[str, Any]]]) -> None:
    sides = list(by_side)
    print(f"{'case':<22}{'side':<8}{'bytes':>7}{'over':>6}{'rows':>7}  failed gates")
    print("-" * 82)
    for idx, rec in enumerate(by_side[sides[0]]):
        for side in sides:
            row = by_side[side][idx]
            rows = "" if row["rows_shown"] is None else str(row["rows_shown"])
            over = "OVER" if row["over_cap"] else ""
            failed = ",".join(row["failed_checks"]) or "-"
            print(f"{row['case']:<22}{side:<8}{row['utf8_bytes']:>7}{over:>6}{rows:>7}  {failed}")


# --------------------------------------------------------------------------
# benchmark
# --------------------------------------------------------------------------


def run_bench(sides: dict[str, Any], repeat: int) -> dict[str, Any]:
    tables = perf_tables()
    results: dict[str, Any] = {"repeat": repeat, "datasets": {}, "python": sys.version.split()[0]}
    import pyarrow as pa

    results["pyarrow"] = pa.__version__
    for side, module in sides.items():
        for name, table in tables.items():
            module.format_query_content(table, len(table))  # warm-up
            timings = []
            content = ""
            warnings: list[str] = []
            for _ in range(repeat):
                start = time.perf_counter()
                content, warnings = module.format_query_content(table, len(table))
                timings.append((time.perf_counter() - start) * 1000.0)
            body, _, _ = parse_query_content(content)
            results["datasets"].setdefault(name, {"rows": len(table), "columns": table.num_columns})[side] = {
                "runs": len(timings),
                "min_ms": round(min(timings), 3),
                "median_ms": round(statistics.median(timings), 3),
                "max_ms": round(max(timings), 3),
                "content_bytes": len(content.encode("utf-8")),
                "rows_shown": 0 if body is None else len(body),
                "warnings": warnings,
            }
    return results


def write_bench(out_root: Path, bench: dict[str, Any]) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "perf.json").write_text(
        json.dumps(bench, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline=""
    )
    with (out_root / "perf.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["dataset", "side", "runs", "min_ms", "median_ms", "max_ms", "content_bytes", "rows_shown"]
        )
        for name, per_side in bench["datasets"].items():
            for side, metrics in per_side.items():
                if not isinstance(metrics, dict):
                    continue
                writer.writerow(
                    [
                        name,
                        side,
                        metrics["runs"],
                        metrics["min_ms"],
                        metrics["median_ms"],
                        metrics["max_ms"],
                        metrics["content_bytes"],
                        metrics["rows_shown"],
                    ]
                )


# --------------------------------------------------------------------------
# demo
# --------------------------------------------------------------------------

DEMO_CASES = ("Q2_zh_10", "Q3_emoji", "Q9_5000_rows", "Q8_empty_total_100", "D2_dry_huge")


def run_demo(sides: dict[str, Any], observations: dict[str, dict[str, Observation]], limit: int = 420) -> None:
    print("=" * 78)
    for case_id in DEMO_CASES:
        print(f"\n### {case_id}")
        for side, obs in observations.items():
            shown = obs.content[:limit].replace("\n", "\\n")
            suffix = " ..." if len(obs.content) > limit else ""
            print(f"  [{side}] bytes={obs.utf8_bytes} warnings={obs.warnings}")
            print(f"  {shown}{suffix}")
    print("\n" + "=" * 78)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--side", choices=("before", "after", "both"), default="both")
    parser.add_argument("--out", default=str(ROOT / "docs" / "evidence"))
    parser.add_argument("--check", action="store_true", help="exit 1 when a gate fails")
    parser.add_argument("--bench", action="store_true")
    parser.add_argument("--bench-repeat", type=int, default=20)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--repeat", type=int, default=1, help="extra repetitions of each case (timing stability)")
    args = parser.parse_args(argv)

    out_root = Path(args.out)
    cases = build_cases()
    modules: dict[str, Any] = {}
    if args.side in ("before", "both"):
        modules["before"] = load_baseline_module()
    if args.side in ("after", "both"):
        modules["after"] = load_after_module()

    # contract: same signatures on both sides
    signature_report = {}
    for name in FORMATTERS:
        per_side = {}
        for side, mod in modules.items():
            fn = getattr(mod, name, None)
            per_side[side] = str(inspect.signature(fn)) if fn else "<missing>"
        signature_report[name] = per_side
    mismatched = [name for name, per in signature_report.items() if len(set(per.values())) > 1]

    env = env_fingerprint(modules)
    observations: dict[str, dict[str, Observation]] = {}
    by_side: dict[str, list[dict[str, Any]]] = {}
    for side, mod in modules.items():
        side_obs: dict[str, Observation] = {}
        for case in cases:
            obs = run_case(mod, case, side)
            if obs.error is None:
                obs.checks, obs.failed = check(case, obs)
            else:
                obs.failed = ["raised"]
            side_obs[case.id] = obs
        observations[side] = side_obs
        records = write_side(out_root, side, mod, [side_obs[c.id] for c in cases], env)
        by_side[side] = records

    print_table(by_side)

    if len(modules) == 2:
        print("\ncompat (byte-identical) controls:")
        for case_id in COMPAT_EXACT_IDS:
            before = observations["before"][case_id]
            after = observations["after"][case_id]
            same = sha256_text(before.content) == sha256_text(after.content)
            print(f"  {case_id:<22} {'IDENTICAL' if same else 'DIFFERS'}")

    print("\nsignatures:", "MATCH" if not mismatched else f"MISMATCH {mismatched}")
    for name, per in signature_report.items():
        print(f"  {name}{per.get('after', per.get('before'))}")

    total_failed = {side: sum(len(o.failed) for o in obs.values()) for side, obs in observations.items()}
    print("\nfailed gates per side:", total_failed)

    if args.bench:
        bench = run_bench(modules, args.bench_repeat)
        write_bench(out_root, bench)
        print("\nbenchmark (component-level only):")
        for name, per_side in bench["datasets"].items():
            print(f"  {name}: rows={per_side['rows']} columns={per_side['columns']}")
            for side, metrics in per_side.items():
                if isinstance(metrics, dict):
                    print(
                        f"    {side:<7} median={metrics['median_ms']:>8.3f} ms "
                        f"min={metrics['min_ms']:>8.3f} max={metrics['max_ms']:>8.3f} "
                        f"bytes={metrics['content_bytes']:>6} rows_shown={metrics['rows_shown']}"
                    )

    if args.demo:
        run_demo(modules, observations)

    exit_code = 0
    if args.check:
        gate_side = "after" if "after" in observations else "before"
        if total_failed[gate_side]:
            exit_code = 1
        if mismatched:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
