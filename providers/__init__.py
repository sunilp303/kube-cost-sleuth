"""
Provider detection and price aggregation.
"""

from __future__ import annotations

import sys

from providers.aws import fetch_aws_prices
from providers.azure import fetch_azure_prices
from providers.gcp import fetch_gcp_prices
from providers.generic import load_csv_prices


def detect_provider(nodes: list[dict]) -> str:
    """Inspect node labels to identify the cloud provider."""
    for node in nodes:
        labels = node.get("labels", {})
        if any(k.startswith("eks.amazonaws.com") for k in labels):
            return "aws"
        if "cloud.google.com/gke-nodepool" in labels or "cloud.google.com/machine-type" in labels:
            return "gcp"
        if any(k.startswith("kubernetes.azure.com") for k in labels):
            return "azure"
        # Heuristic: instance type format
        it = node.get("instance_type", "")
        if it.startswith("Standard_"):
            return "azure"
        if it.startswith("n1-") or it.startswith("n2-") or it.startswith("e2-") or it.startswith("c2-"):
            return "gcp"
        if it and it[0] in "tmcr" and "." in it:
            return "aws"
    return "generic"


def get_prices(nodes: list[dict], price_file: str | None = None) -> dict[str, float]:
    """
    Fetch prices for every instance type found on the nodes.
    Strategy: try cloud API → merge/fallback with CSV if provided or API fails.
    Returns {instance_type: cost_per_hour}.
    """
    provider = detect_provider(nodes)
    instance_types = {n["instance_type"] for n in nodes if n["instance_type"] != "unknown"}
    regions = {n["region"] for n in nodes}
    region = next(iter(regions), "us-east-1")

    prices: dict[str, float] = {}

    # --- Try cloud API ---
    try:
        if provider == "aws":
            prices = fetch_aws_prices(instance_types, region)
        elif provider == "gcp":
            prices = fetch_gcp_prices(instance_types)
        elif provider == "azure":
            prices = fetch_azure_prices(instance_types, region)
    except Exception as e:
        print(f"  [WARN] Cloud pricing API failed ({e}). Falling back to CSV.", file=sys.stderr)

    # --- Merge CSV (fills gaps or overrides) ---
    if price_file:
        csv_prices = load_csv_prices(price_file)
        prices = {**prices, **csv_prices}

    # Report any instance types we have no price for
    missing = instance_types - set(prices)
    if missing:
        print(
            f"  [WARN] No price found for: {', '.join(sorted(missing))}. "
            "Use --price-file to supply custom pricing.",
            file=sys.stderr,
        )

    return prices
