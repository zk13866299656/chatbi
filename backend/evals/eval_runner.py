"""ChatBI 离线评测:执行准确率(execution accuracy)。

流程:加载 JSONL 用例 → 跑完整问数工作流 → 把生成 SQL 与标注 SQL 分别执行 →
对比结果集(行级多重集合,数值四舍五入)→ 输出通过率与耗时报告。

用法:
    python evals/eval_runner.py --limit 5 --no-gate
    python evals/eval_runner.py --gate-threshold 0.6   # CI 门禁,低于阈值退出码 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.nodes import _detect_region, parse_period_fallback
from app.services.sql_executor import check_sql_safety, execute_sql
from app.workflows.graph import get_workflow

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"


@dataclass
class CaseResult:
    case_id: str
    question: str
    status: str            # passed | failed | no_sql | error
    mode: str = ""
    elapsed_ms: int = 0
    gen_rows: int = 0
    gold_rows: int = 0
    message: str = ""
    detail: dict = field(default_factory=dict)


def _normalize(rows: list[list]) -> list[tuple]:
    normalized = []
    for row in rows:
        cells = []
        for value in row:
            if isinstance(value, float):
                cells.append(round(value, 2))
            else:
                try:
                    cells.append(round(float(value), 2) if value not in ("", None) else value)
                except (TypeError, ValueError):
                    cells.append(str(value))
        normalized.append(tuple(cells))
    return sorted(normalized)


def _finalize_gold(sql: str, period_start: str, period_end: str, question: str) -> str:
    """gold SQL 中的占位符与系统解析的时间窗对齐。"""
    if not period_start or not period_end:
        period_start, period_end = parse_period_fallback(question)
    return (
        sql.replace("__PSTART__", period_start)
        .replace("__PEND__", period_end)
        .replace("{REGION}", _detect_region(question))
    )


async def run_case(case: dict, workflow) -> CaseResult:
    started = time.perf_counter()
    try:
        final = await workflow.run(case["question"])
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        gen_sql = (final.get("sql") or "").strip()
        if not gen_sql:
            return CaseResult(case["id"], case["question"], "no_sql", final.get("mode", ""),
                              elapsed_ms, message="未生成 SQL")

        gold_sql = _finalize_gold(case["gold_sql"], final.get("period_start", ""),
                                  final.get("period_end", ""), case["question"])

        gen_checked, gen_err = check_sql_safety(gen_sql)
        if gen_err:
            return CaseResult(case["id"], case["question"], "error", final.get("mode", ""),
                              elapsed_ms, message=f"生成 SQL 未通过安全校验: {gen_err}")
        gold_checked, gold_err = check_sql_safety(gold_sql)
        if gold_err:
            return CaseResult(case["id"], case["question"], "error", final.get("mode", ""),
                              elapsed_ms, message=f"标注 SQL 未通过安全校验: {gold_err}")

        gen_cols, gen_rows, _ = await execute_sql(gen_checked)
        gold_cols, gold_rows, _ = await execute_sql(gold_checked)

        if _normalize(gen_rows) == _normalize(gold_rows):
            return CaseResult(case["id"], case["question"], "passed", final.get("mode", ""),
                              elapsed_ms, len(gen_rows), len(gold_rows))
        return CaseResult(case["id"], case["question"], "failed", final.get("mode", ""),
                          elapsed_ms, len(gen_rows), len(gold_rows),
                          message="执行结果与标注不一致")
    except Exception as exc:  # noqa: BLE001
        return CaseResult(case["id"], case["question"], "error",
                          elapsed_ms=int((time.perf_counter() - started) * 1000),
                          message=f"{exc.__class__.__name__}: {exc}")


def _load_cases(limit: int | None) -> list[dict]:
    cases = []
    for line in CASES_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cases.append(json.loads(line))
    return cases[:limit] if limit else cases


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-gate", action="store_true", help="不启用通过率门禁")
    parser.add_argument("--gate-threshold", type=float, default=0.6)
    args = parser.parse_args()

    cases = _load_cases(args.limit)
    workflow = get_workflow()
    print(f"开始评测: {len(cases)} 条用例")

    results: list[CaseResult] = []
    for case in cases:
        result = await run_case(case, workflow)
        results.append(result)
        icon = {"passed": "✅", "failed": "❌", "no_sql": "⚠️ ", "error": "💥"}[result.status]
        print(f"{icon} {result.case_id} [{result.status}] {result.elapsed_ms}ms {result.message}")

    passed = sum(1 for r in results if r.status == "passed")
    accuracy = passed / len(results) if results else 0
    avg_ms = sum(r.elapsed_ms for r in results) / len(results) if results else 0
    summary = {
        "total": len(results),
        "passed": passed,
        "accuracy": round(accuracy, 4),
        "avg_elapsed_ms": int(avg_ms),
        "mode": "llm" if (results and results[0].mode == "llm") else "fallback",
    }

    report_dir = Path(__file__).resolve().parent
    report_path = report_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    lines = [
        "# ChatBI 问数评测报告",
        "",
        f"- 用例数: {summary['total']}",
        f"- 通过: {summary['passed']}",
        f"- 执行准确率: **{summary['accuracy']:.1%}**",
        f"- 平均耗时: {summary['avg_elapsed_ms']}ms",
        f"- 运行模式: {summary['mode']}",
        "",
        "| 用例 | 问题 | 状态 | 耗时ms | 说明 |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.case_id} | {r.question} | {r.status} | {r.elapsed_ms} | {r.message} |" for r in results
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {report_path}")
    print(json.dumps(summary, ensure_ascii=False))

    if not args.no_gate and accuracy < args.gate_threshold:
        print(f"未达到门禁阈值 {args.gate_threshold:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
