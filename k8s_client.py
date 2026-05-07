"""
Thin kubectl wrapper — no Python k8s SDK required.
All functions return plain dicts; CPU is in millicores (m), memory in MiB.
"""

import json
import re
import subprocess
import sys


def _run(cmd: list[str]) -> dict | list:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        print("ERROR: kubectl not found. Install kubectl and configure kubeconfig.", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print(f"ERROR: kubectl timed out: {' '.join(cmd)}", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        print(f"ERROR: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    return json.loads(result.stdout)


def _parse_cpu(s: str | None) -> int:
    """Convert k8s CPU string to millicores. None → 0."""
    if not s:
        return 0
    s = s.strip()
    if s.endswith("m"):
        return int(s[:-1])
    if s.endswith("n"):
        return max(1, int(s[:-1]) // 1_000_000)
    return int(float(s) * 1000)


def _parse_mem(s: str | None) -> int:
    """Convert k8s memory string to MiB. None → 0."""
    if not s:
        return 0
    s = s.strip()
    units = {
        "Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 ** 2,
        "K": 1 / 1.024 / 1024, "M": 1 / 1.024, "G": 1024 / 1.024,
    }
    for suffix, factor in units.items():
        if s.endswith(suffix):
            return max(1, int(float(s[: -len(suffix)]) * factor))
    return int(s) // (1024 * 1024)


# ── Node labels used for provider/instance detection ──────────────────────────
_INSTANCE_LABELS = [
    "node.kubernetes.io/instance-type",
    "beta.kubernetes.io/instance-type",
    "cloud.google.com/machine-type",
]
_REGION_LABELS = [
    "topology.kubernetes.io/region",
    "failure-domain.beta.kubernetes.io/region",
]


def get_nodes() -> list[dict]:
    data = _run(["kubectl", "get", "nodes", "-o", "json"])
    nodes = []
    for item in data.get("items", []):
        labels = item["metadata"].get("labels", {})
        instance_type = next((labels[k] for k in _INSTANCE_LABELS if k in labels), "unknown")
        region = next((labels[k] for k in _REGION_LABELS if k in labels), "us-east-1")
        alloc = item["status"].get("allocatable", {})
        nodes.append({
            "name": item["metadata"]["name"],
            "instance_type": instance_type,
            "region": region,
            "labels": labels,
            "allocatable_cpu_m": _parse_cpu(alloc.get("cpu")),
            "allocatable_mem_mi": _parse_mem(alloc.get("memory")),
        })
    return nodes


def get_pods(namespace: str = "") -> list[dict]:
    cmd = ["kubectl", "get", "pods", "-o", "json"]
    cmd += ["-n", namespace] if namespace else ["-A"]
    data = _run(cmd)

    pods = []
    for item in data.get("items", []):
        phase = item["status"].get("phase", "")
        if phase not in ("Running", "Pending"):
            continue

        meta = item["metadata"]
        spec = item["spec"]

        containers = []
        for c in spec.get("containers", []):
            res = c.get("resources", {})
            req = res.get("requests", {})
            lim = res.get("limits", {})
            req_cpu  = _parse_cpu(req.get("cpu"))
            req_mem  = _parse_mem(req.get("memory"))
            lim_cpu  = _parse_cpu(lim.get("cpu"))
            lim_mem  = _parse_mem(lim.get("memory"))
            containers.append({
                "name":        c["name"],
                "req_cpu_m":   req_cpu,
                "req_mem_mi":  req_mem,
                "lim_cpu_m":   lim_cpu,
                "lim_mem_mi":  lim_mem,
                "no_requests": req_cpu == 0 and req_mem == 0,
                "no_limits":   lim_cpu == 0 and lim_mem == 0,
            })

        pods.append({
            "name":       meta["name"],
            "namespace":  meta.get("namespace", "default"),
            "node_name":  spec.get("nodeName", ""),
            "containers": containers,
        })
    return pods


def get_metrics(namespace: str = "") -> dict[str, dict]:
    """
    Returns {"{ns}/{pod}": {"cpu_m": int, "mem_mi": int}}.
    Returns empty dict if metrics-server is not installed.
    """
    cmd = ["kubectl", "top", "pods", "--no-headers"]
    cmd += ["-n", namespace] if namespace else ["-A"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    if result.returncode != 0:
        return {}

    metrics: dict[str, dict] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3:
            # namespaced: NAMESPACE POD CPU MEM — but -A gives 4 cols
            ns, pod, cpu_s, mem_s = parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else parts[2]
        elif len(parts) == 4:
            ns, pod, cpu_s, mem_s = parts
        else:
            continue
        metrics[f"{ns}/{pod}"] = {
            "cpu_m":  _parse_cpu(cpu_s),
            "mem_mi": _parse_mem(mem_s),
        }
    return metrics
