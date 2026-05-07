#!/usr/bin/env python3
"""
k8s-cost-analyzer — maps pod resource requests to node costs and ranks waste.

Usage:
  python cost_analyzer.py [--namespace=NS] [--output=table|json|html]
                          [--html-out=FILE] [--price-file=FILE]
                          [--sort=waste|cost|name] [--top=N] [--no-metrics]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from k8s_client import get_metrics, get_nodes, get_pods
from providers import get_prices
from report_html import write_report
from waste_calculator import PodCost, calculate_waste, cluster_summary, rank

# ── Terminal colours ───────────────────────────────────────────────────────────
RED    = "\033[0;31m"
YELLOW = "\033[1;33m"
GREEN  = "\033[0;32m"
CYAN   = "\033[0;36m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _c(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if sys.stdout.isatty() else text


# ── Formatting helpers ─────────────────────────────────────────────────────────
def _fmt_cost(v: float | None, width: int = 8) -> str:
    s = f"${v:.4f}" if v is not None else "—"
    return s.rjust(width)


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "  —  "
    color = RED if v >= 70 else (YELLOW if v >= 40 else GREEN)
    return _c(f"{v:5.1f}%", color)


def _fmt_cpu(m: int | None) -> str:
    if m is None:
        return "  —"
    return f"{m}m" if m < 1000 else f"{m/1000:.1f} "


def _fmt_mem(mi: int | None) -> str:
    if mi is None:
        return "—"
    return f"{mi/1024:.1f}Gi" if mi >= 1024 else f"{mi}Mi"


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# ── Table output ───────────────────────────────────────────────────────────────
def print_table(rows: list[PodCost], summary: dict):
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    live = "live metrics" if summary["pods_with_metrics"] > 0 else "estimates only (no metrics-server)"

    print()
    print(_c(f" K8s Cost Analyzer", BOLD) + f"  —  {ts}  —  {live}")
    print(
        f" Total: {_c(_fmt_cost(summary['total_cost_hr']).strip(), BOLD)}/hr"
        f"  |  Waste: {_c(_fmt_cost(summary['total_waste_hr']).strip(), RED)}/hr"
        f"  ({_c(str(summary['waste_pct'])+'%', YELLOW)})"
        f"  |  Flagged pods: {summary['flagged_pods']}"
    )
    print()

    # Header
    h = (
        f"  {'NAMESPACE':<16} {'POD':<36} {'TYPE':<16}"
        f" {'$/HR':>8} {'POD$/HR':>8}"
        f" {'CPU-REQ':>7} {'CPU-USE':>7} {'MEM-REQ':>7}"
        f" {'WASTE/HR':>9} {'WASTE%':>7}  FLAGS"
    )
    print(_c(h, DIM))
    print(_c("  " + "─" * (len(h) - 2), DIM))

    for r in rows:
        waste_hr_s = _fmt_cost(r.waste_cost_hr, 9)
        if r.waste_cost_hr and r.waste_cost_hr > 0.01:
            waste_hr_s = _c(waste_hr_s, RED)

        flags_s = " ".join(_c(f"⚑{f}", YELLOW) for f in r.flags)
        metrics_dot = _c("●", GREEN) if r.has_metrics else _c("○", DIM)

        print(
            f"  {_truncate(r.namespace, 16):<16}"
            f" {_truncate(r.pod, 36):<36}"
            f" {_truncate(r.instance_type, 16):<16}"
            f" {_fmt_cost(r.node_cost_hr)}"
            f" {_fmt_cost(r.pod_cost_hr)}"
            f" {_fmt_cpu(r.req_cpu_m):>7}"
            f" {_fmt_cpu(r.actual_cpu_m):>7}"
            f" {_fmt_mem(r.req_mem_mi):>7}"
            f" {waste_hr_s}"
            f" {_fmt_pct(r.waste_pct)}"
            f"  {metrics_dot} {flags_s}"
        )

    print()
    print(_c(f"  ● live metrics   ○ no metrics   ⚑ flag", DIM))
    print()


# ── JSON output ────────────────────────────────────────────────────────────────
def _row_to_dict(r: PodCost) -> dict:
    return {
        "namespace":     r.namespace,
        "pod":           r.pod,
        "node":          r.node,
        "instance_type": r.instance_type,
        "node_cost_hr":  round(r.node_cost_hr, 6),
        "pod_cost_hr":   round(r.pod_cost_hr, 6),
        "req_cpu_m":     r.req_cpu_m,
        "lim_cpu_m":     r.lim_cpu_m,
        "req_mem_mi":    r.req_mem_mi,
        "lim_mem_mi":    r.lim_mem_mi,
        "actual_cpu_m":  r.actual_cpu_m,
        "actual_mem_mi": r.actual_mem_mi,
        "waste_cost_hr": round(r.waste_cost_hr, 6) if r.waste_cost_hr is not None else None,
        "waste_pct":     round(r.waste_pct, 2) if r.waste_pct is not None else None,
        "flags":         r.flags,
        "has_metrics":   r.has_metrics,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Map Kubernetes pod resource requests to node costs and rank by waste.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--namespace",  default="",              help="Scope to a namespace (default: all)")
    p.add_argument("--output",     default="table",         choices=["table", "json", "html"])
    p.add_argument("--html-out",   default="k8s-cost-report.html", metavar="FILE")
    p.add_argument("--price-file", default=None,            metavar="FILE",
                   help="CSV file with instance_type,cost_per_hour columns")
    p.add_argument("--sort",       default="waste",         choices=["waste", "cost", "name"])
    p.add_argument("--top",        default=20,   type=int,  help="Show top N pods (0 = all)")
    p.add_argument("--no-metrics", action="store_true",     help="Skip metrics-server calls")
    return p.parse_args()


def main():
    args = parse_args()

    print(f"  Fetching nodes...", end="", flush=True)
    nodes = get_nodes()
    print(f" {len(nodes)} found")

    print(f"  Fetching pods...", end="", flush=True)
    pods = get_pods(args.namespace)
    print(f" {len(pods)} running/pending")

    metrics: dict = {}
    if not args.no_metrics:
        print(f"  Fetching metrics...", end="", flush=True)
        metrics = get_metrics(args.namespace)
        status = f"{len(metrics)} pods with metrics" if metrics else "metrics-server not available"
        print(f" {status}")

    print(f"  Fetching prices...", end="", flush=True)
    prices = get_prices(nodes, args.price_file)
    priced = sum(1 for n in nodes if n["instance_type"] in prices)
    print(f" {priced}/{len(nodes)} node types priced")
    print()

    all_rows  = calculate_waste(pods, nodes, prices, metrics)
    ranked    = rank(all_rows, sort=args.sort, top=args.top)
    summary   = cluster_summary(all_rows)

    if args.output == "table":
        print_table(ranked, summary)

    elif args.output == "json":
        out = {
            "summary": summary,
            "pods": [_row_to_dict(r) for r in ranked],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(out, indent=2))

    elif args.output == "html":
        write_report(ranked, summary, args.html_out)
        print(f"  Report written → {args.html_out}")

    # Always write HTML alongside table/json if --html-out is explicitly set
    # (only when --output != html to avoid double write)
    elif args.html_out != "k8s-cost-report.html":
        write_report(ranked, summary, args.html_out)
        print(f"  Report also written → {args.html_out}")


if __name__ == "__main__":
    main()
