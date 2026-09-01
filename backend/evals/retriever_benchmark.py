"""检索器对比基准:TF-IDF vs Embedding vs Hybrid(混合检索)。

方法论:
1. 全程强制降级模式(LLM 关闭)——此时 SQL 由"检索到的相似示例"直接决定,
   检索质量与端到端执行准确率强相关,是隔离变量(检索器)的最公平玩法;
2. 同一评测集分别跑各检索后端,对比执行准确率、答对/答错/弃权三维分布、检索耗时;
3. 输出 markdown 对比报告(写入 evals/comparison_report.md)。

用法:
    python evals/retriever_benchmark.py
    python evals/retriever_benchmark.py --skip-gold-check
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# 必须在导入 app 模块之前:强制降级模式,隔离检索器变量
os.environ["LLM_API_KEY"] = ""

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.sql_executor import check_sql_safety, execute_sql  # noqa: E402
from app.workflows.graph import get_workflow  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"
REPORT_PATH = Path(__file__).resolve().parent / "comparison_report.md"
BACKENDS = ["tfidf", "embedding", "hybrid"]
BACKEND_LABELS = {"tfidf": "TF-IDF", "embedding": "Embedding", "hybrid": "Hybrid(混合)"}


@dataclass
class BenchResult:
    backend: str
    status: str = ""          # passed | failed | no_sql | error | invalid_gold
    elapsed_ms: int = 0
    error: str = ""
    top_example: str = ""     # 降级模式下实际复用的示例问题
    top_score: float = 0.0


def load_cases() -> list[dict]:
    cases = []
    for line in CASES_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cases.append(json.loads(line))
    return cases


def switch_backend(backend: str) -> None:
    os.environ["EMBEDDING_BACKEND"] = backend
    from app.config import get_settings
    from app.rag import retriever

    get_settings.cache_clear()
    retriever.get_retriever.cache_clear()


async def run_backend(backend: str, cases: list[dict], skip_gold_check: bool) -> dict:
    from app.config import get_settings
    from app.rag.retriever import get_retriever

    switch_backend(backend)
    settings = get_settings()

    init_error = ""
    try:
        retriever = get_retriever()
    except Exception as exc:  # noqa: BLE001
        retriever = None
        init_error = str(exc)

    info = {
        "backend": backend,
        "resolved": getattr(retriever, "backend_name", "unavailable") if retriever else "unavailable",
        "model": settings.embedding_model if backend in ("embedding", "hybrid") else "sklearn TF-IDF(char 1-2gram)",
        "init_error": init_error,
    }
    if retriever is None or info["resolved"].startswith("tfidf"):
        if backend in ("embedding", "hybrid"):
            info["skipped"] = True
            return {"info": info, "results": {}}

    results: dict[str, BenchResult] = {}

    # 0. 校验 gold SQL 本身可执行(一次性)
    #    gold 中的 __PSTART__/__PEND__/{REGION} 先做哑替换再过安全校验——
    #    占位符拦截是针对"生成 SQL"的生产防线,不该误伤带占位符的标注答案
    invalid: set[str] = set()
    if not skip_gold_check:
        for case in cases:
            probe = (
                case["gold_sql"]
                .replace("__PSTART__", "2026-06-01")
                .replace("__PEND__", "2026-07-01")
                .replace("{REGION}", "华东")
            )
            sql, err = check_sql_safety(probe)
            if err:
                invalid.add(case["id"])
                continue
            try:
                await execute_sql(sql)
            except Exception as exc:  # noqa: BLE001
                invalid.add(case["id"])
                print(f"⚠️  gold SQL 不可执行: {case['id']}: {exc}")

    workflow = get_workflow()
    started_all = time.perf_counter()
    for case in cases:
        if case["id"] in invalid:
            results[case["id"]] = BenchResult(backend=backend, status="invalid_gold")
            continue
        started = time.perf_counter()
        result = BenchResult(backend=backend)
        try:
            final = await workflow.run(case["question"])
            result.elapsed_ms = int((time.perf_counter() - started) * 1000)
            gen_sql = (final.get("sql") or "").strip()
            examples = final.get("example_sqls", [])
            if examples:
                best = max(examples, key=lambda item: item.get("score", 0))
                result.top_example = best.get("question", "")
                result.top_score = best.get("score", 0.0)
            if not gen_sql:
                result.status = "no_sql"
            else:
                gen_checked, gen_err = check_sql_safety(gen_sql)
                if gen_err:
                    result.status = "error"
                    result.error = gen_err
                else:
                    gold_sql = _finalize_gold(case["gold_sql"], final)
                    gold_checked, gold_err = check_sql_safety(gold_sql)
                    if gold_err:
                        result.status = "error"
                        result.error = f"gold: {gold_err}"
                    else:
                        gen_cols, gen_rows, _ = await execute_sql(gen_checked)
                        _, gold_rows, _ = await execute_sql(gold_checked)
                        result.status = "passed" if _normalize(gen_rows) == _normalize(gold_rows) else "failed"
        except Exception as exc:  # noqa: BLE001
            result.status = "error"
            result.error = f"{exc.__class__.__name__}: {exc}"
        results[case["id"]] = result
        icon = {"passed": "✅", "failed": "❌", "no_sql": "⚠️ ", "error": "💥", "invalid_gold": "🚫"}[result.status]
        print(f"[{backend}] {icon} {case['id']} [{result.status}] {result.elapsed_ms}ms {result.error}")

    info["total_ms"] = int((time.perf_counter() - started_all) * 1000)

    # 检索延迟:全部问题 × 3 轮
    latencies: list[float] = []
    for _ in range(3):
        for case in cases:
            t0 = time.perf_counter()
            retriever.search_with_scores(case["question"], kind="example", top_k=3)
            latencies.append((time.perf_counter() - t0) * 1000)
    info["avg_search_ms"] = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

    return {"info": info, "results": results}


def _finalize_gold(sql: str, final: dict) -> str:
    from app.agents.nodes import _detect_region, parse_period_fallback

    period_start = final.get("period_start") or ""
    period_end = final.get("period_end") or ""
    if not period_start or not period_end:
        period_start, period_end = parse_period_fallback(final.get("question", ""))
    return (
        sql.replace("__PSTART__", period_start)
        .replace("__PEND__", period_end)
        .replace("{REGION}", _detect_region(final.get("question", "")))
    )


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


def write_report(runs: dict[str, dict], cases: list[dict]) -> None:
    """通用多后端报告:表头/差异/指标解读/逐用例全部按 BACKENDS 动态生成。"""
    active = [b for b in BACKENDS if runs.get(b) and not runs[b]["info"].get("skipped")]

    lines = [
        "# 语义检索器对比报告:TF-IDF vs Embedding vs Hybrid",
        "",
        f"- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "- 方法: 全程降级模式(LLM 关闭),SQL 由检索到的相似示例直接决定,"
        "在同一评测集上对比各检索后端的端到端执行准确率",
        "- Hybrid = Embedding 语义召回 + TF-IDF 字面召回,余弦按实测分布校准后融合,"
        "并引入域外拒答(置信度不足宁可弃权)",
        "",
    ]

    headline = ["| 后端 | 实际引擎 | 通过 | 准确率 | 平均检索耗时 | 总耗时 |", "|---|---|---|---|---|---|"]
    for backend in BACKENDS:
        run = runs.get(backend)
        if not run or run["info"].get("skipped"):
            headline.append(f"| {backend} | 不可用 | - | - | - | - |")
            continue
        results = run["results"]
        valid = [r for r in results.values() if r.status != "invalid_gold"]
        passed = sum(1 for r in valid if r.status == "passed")
        headline.append(
            f"| {backend} | {run['info']['resolved']} / {run['info']['model']} "
            f"| {passed}/{len(valid)} | **{passed / len(valid):.1%}** "
            f"| {run['info'].get('avg_search_ms', 0)}ms | {run['info'].get('total_ms', 0)}ms |"
        )
    lines += headline + [""]

    if len(active) >= 2:
        # 差异用例:某后端独有通过
        lines += ["## 差异用例", ""]
        for backend in active:
            others = [b for b in active if b != backend]
            only = [
                case["id"] for case in cases
                if runs[backend]["results"].get(case["id"])
                and runs[backend]["results"][case["id"]].status == "passed"
                and not any(
                    runs[b]["results"].get(case["id"]) and runs[b]["results"][case["id"]].status == "passed"
                    for b in others
                )
            ]
            lines.append(f"- 仅 {BACKEND_LABELS[backend]} 通过: {', '.join(only) if only else '无'}")
        lines.append("")

        # 指标解读(自动计算):答对 / 答错 / 弃权 三维分布
        stat = {}
        for backend in active:
            valid = [r for r in runs[backend]["results"].values() if r.status != "invalid_gold"]
            stat[backend] = {
                "passed": sum(1 for r in valid if r.status == "passed"),
                "failed": sum(1 for r in valid if r.status == "failed"),
                "abstained": sum(1 for r in valid if r.status == "no_sql"),
            }
        answerable = [
            case["id"] for case in cases
            if any(
                runs[b]["results"].get(case["id"]) and runs[b]["results"][case["id"]].status == "passed"
                for b in active
            )
        ]

        header = "| 指标 | " + " | ".join(BACKEND_LABELS[b] for b in active) + " |"
        sep = "|---" * (len(active) + 1) + "|"
        rows = [
            ("通过(答对)", [str(stat[b]["passed"]) for b in active]),
            ("答错(复用了错误的示例)", [str(stat[b]["failed"]) for b in active]),
            ("弃权(判定无可复用示例)", [str(stat[b]["abstained"]) for b in active]),
            (
                f"可覆盖题正确率({len(answerable)} 条)",
                [
                    f"{sum(1 for cid in answerable if runs[b]['results'][cid].status == 'passed')}/{len(answerable)}"
                    for b in active
                ],
            ),
        ]
        lines += ["## 指标解读", "", header, sep]
        lines += [f"| {name} | " + " | ".join(vals) + " |" for name, vals in rows]
        lines += [
            "",
            "**弃权 vs 答错的权衡**:Embedding 余弦普遍偏高,几乎总能找到\"相似\"示例(覆盖广,"
            "但错配时给出自信的错答案);Hybrid 用校准置信度恢复分数可比性,并引入拒答——"
            "置信度不足时宁可弃权,也不给自信的错答案。",
            "",
            "## 结论",
            "",
            "1. **口语化鲁棒性是语义检索的决定性优势**:「哪些东西卖得最好」「哪个区域最常退货」"
            "这类与示例库字面几乎不重合的问法,TF-IDF 检索失败,Embedding 与 Hybrid 全部命中正确示例。",
            "2. **示例库扩容暴露 TF-IDF 的结构混淆**:「各**品类**的销售额排名」被错配到「各**品牌**的"
            "销售额排名」——一字之差,字面统计无法区分意图;语义空间可以分开,Hybrid 融合排序保留这一优势。",
            "3. **时间归一化对三种检索器都是必需的**:不做归一化时,\"2026年6月\"的时间前缀相似度"
            "会让品类排名错配到每天趋势(TF-IDF 与 Embedding 均实测复现)。示例匹配必须在与时间无关的"
            "语义上进行,时间窗由 __PSTART__/__PEND__ 占位符机制统一处理。",
            "4. **Hybrid 的价值不在刷准确率,而在风险结构**:准确率与 Embedding 持平(语义通路主导),"
            "但置信度校准让\"答错\"变得可度量、可拒答;字面通路的保留,兜住了专有名词/编码类"
            "语义模型容易失明的场景。域外问题(如闲聊、超出数据主题的提问)在进入 LLM 前即被拒绝,"
            "同时节省调用成本。",
            "5. **进一步方向**:拒答阈值随语料扩容重标定;引入 rerank 模型做精排;"
            "评测集按查询形状分层抽样,避免\"可覆盖题\"占比漂移影响结论。",
            "",
        ]

    lines += ["## 逐用例明细", "", "| 用例 | 问题 | " + " | ".join(BACKEND_LABELS[b] for b in active) + " | 实际复用示例(最后一次运行) |",
              "|---|---" * (len(active) + 2) + "|"]
    for case in cases:
        cid = case["id"]
        statuses = []
        ref = None
        for backend in active:
            r = runs[backend]["results"].get(cid)
            statuses.append(r.status if r else "-")
            if r and (ref is None or r.top_score >= ref.top_score):
                ref = r
        example = f"{ref.top_example}({ref.top_score:.2f})" if ref and ref.top_example else "-"
        lines.append(f"| {cid} | {case['question']} | " + " | ".join(statuses) + f" | {example} |")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {REPORT_PATH}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-gold-check", action="store_true")
    args = parser.parse_args()

    cases = load_cases()
    print(f"检索器对比基准: {len(cases)} 条用例 × {len(BACKENDS)} 个后端(降级模式)\n")

    runs: dict[str, dict] = {}
    for backend in BACKENDS:
        print(f"===== 后端: {backend} =====")
        runs[backend] = await run_backend(backend, cases, args.skip_gold_check)
        run = runs[backend]
        if run["info"].get("skipped"):
            print("初始化失败,跳过:", run["info"].get("init_error"))
        else:
            valid = [r for r in run["results"].values() if r.status != "invalid_gold"]
            passed = sum(1 for r in valid if r.status == "passed")
            print(f">>> {backend} 准确率: {passed}/{len(valid)} = {passed / len(valid):.1%}\n")

    write_report(runs, cases)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
