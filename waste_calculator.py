"""
Core cost and waste calculation.

Cost model (CPU-weighted, industry standard):
  pod_cpu_share   = pod_total_req_cpu_m / node_allocatable_cpu_m
  pod_cost_hr     = node_cost_hr * pod_cpu_share

Waste (when metrics available):
  cpu_waste_frac  = (req_cpu_m - actual_cpu_m) / req_cpu_m   [clamped 0–1]
  waste_cost_hr   = pod_cost_hr * cpu_waste_frac

Flags (estimation mode, no metrics):
  NO_REQUESTS  — all containers have zero CPU/mem requests
  NO_LIMITS    — at least one container has no CPU/mem limits
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PodCost:
    namespace: str
    pod: str
    node: str
    instance_type: str
    node_cost_hr: float          # full node $/hr
    pod_cost_hr: float           # this pod's share of node cost
    req_cpu_m: int               # total requested CPU across all containers (millicores)
    lim_cpu_m: int               # total CPU limits (0 = not set)
    req_mem_mi: int              # total requested memory (MiB)
    lim_mem_mi: int              # total memory limits (0 = not set)
    actual_cpu_m: int | None     # from metrics-server, None if unavailable
    actual_mem_mi: int | None
    waste_cost_hr: float | None  # None if no metrics
    waste_pct: float | None      # 0–100, None if no metrics
    flags: list[str] = field(default_factory=list)
    has_metrics: bool = False


def calculate_waste(
    pods: list[dict],
    nodes: list[dict],
    prices: dict[str, float],
    metrics: dict[str, dict],
) -> list[PodCost]:
    node_map = {n["name"]: n for n in nodes}
    results: list[PodCost] = []

    for pod in pods:
        node_name = pod["node_name"]
        node = node_map.get(node_name)
        if not node:
            continue

        instance_type = node["instance_type"]
        node_cost_hr = prices.get(instance_type, 0.0)
        alloc_cpu = node["allocatable_cpu_m"] or 1  # avoid div/0

        containers = pod["containers"]

        total_req_cpu = sum(c["req_cpu_m"] for c in containers)
        total_lim_cpu = sum(c["lim_cpu_m"] for c in containers)
        total_req_mem = sum(c["req_mem_mi"] for c in containers)
        total_lim_mem = sum(c["lim_mem_mi"] for c in containers)

        pod_cpu_share = min(total_req_cpu / alloc_cpu, 1.0)
        pod_cost_hr = node_cost_hr * pod_cpu_share

        # Flags
        flags: list[str] = []
        if all(c["no_requests"] for c in containers):
            flags.append("NO_REQUESTS")
        if any(c["no_limits"] for c in containers):
            flags.append("NO_LIMITS")

        # Metrics
        key = f"{pod['namespace']}/{pod['name']}"
        m = metrics.get(key)
        actual_cpu = m["cpu_m"] if m else None
        actual_mem = m["mem_mi"] if m else None

        waste_cost_hr: float | None = None
        waste_pct: float | None = None

        if actual_cpu is not None and total_req_cpu > 0:
            used_frac = min(actual_cpu / total_req_cpu, 1.0)
            waste_frac = max(0.0, 1.0 - used_frac)
            waste_cost_hr = pod_cost_hr * waste_frac
            waste_pct = waste_frac * 100.0

        results.append(PodCost(
            namespace=pod["namespace"],
            pod=pod["name"],
            node=node_name,
            instance_type=instance_type,
            node_cost_hr=node_cost_hr,
            pod_cost_hr=pod_cost_hr,
            req_cpu_m=total_req_cpu,
            lim_cpu_m=total_lim_cpu,
            req_mem_mi=total_req_mem,
            lim_mem_mi=total_lim_mem,
            actual_cpu_m=actual_cpu,
            actual_mem_mi=actual_mem,
            waste_cost_hr=waste_cost_hr,
            waste_pct=waste_pct,
            flags=flags,
            has_metrics=m is not None,
        ))

    return results


def rank(rows: list[PodCost], sort: str = "waste", top: int = 20) -> list[PodCost]:
    if sort == "cost":
        key = lambda r: -(r.pod_cost_hr or 0)
    elif sort == "name":
        key = lambda r: (r.namespace, r.pod)
    else:  # waste (default)
        key = lambda r: -(r.waste_cost_hr or (r.pod_cost_hr if r.flags else 0))

    ranked = sorted(rows, key=key)
    return ranked[:top] if top > 0 else ranked


def cluster_summary(rows: list[PodCost]) -> dict:
    total_cost = sum(r.pod_cost_hr for r in rows)
    total_waste = sum(r.waste_cost_hr for r in rows if r.waste_cost_hr is not None)
    pods_with_metrics = sum(1 for r in rows if r.has_metrics)
    flagged = sum(1 for r in rows if r.flags)

    return {
        "total_pods": len(rows),
        "total_cost_hr": round(total_cost, 4),
        "total_waste_hr": round(total_waste, 4),
        "waste_pct": round((total_waste / total_cost * 100) if total_cost else 0, 1),
        "pods_with_metrics": pods_with_metrics,
        "flagged_pods": flagged,
    }
