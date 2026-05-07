"""
GCP Compute Engine pricing via the public GCP pricing calculator JSON.
No authentication required. Cached 24h.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

CACHE_DIR = Path.home() / ".cache" / "k8s-cost-analyzer"
CACHE_TTL = 86400

# Public pricing data used by the GCP pricing calculator
_URL = "https://cloudpricingcalculator.appspot.com/static/data/pricelist.json"

# Maps GCP machine type prefix → pricing key prefix in the pricelist
# e.g. "n1-standard-4" → look for CP-COMPUTEENGINE-VMIMAGE-N1-STANDARD-4
_PREFIX_MAP = {
    "n1-": "CP-COMPUTEENGINE-VMIMAGE-N1-",
    "n2-": "CP-COMPUTEENGINE-VMIMAGE-N2-",
    "n2d-": "CP-COMPUTEENGINE-VMIMAGE-N2D-",
    "e2-": "CP-COMPUTEENGINE-VMIMAGE-E2-",
    "c2-": "CP-COMPUTEENGINE-VMIMAGE-C2-",
    "m1-": "CP-COMPUTEENGINE-VMIMAGE-M1-",
}


def _cache_path() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / "gcp.json"


def _load_cache() -> dict | None:
    p = _cache_path()
    if p.exists() and (time.time() - p.stat().st_mtime) < CACHE_TTL:
        return json.loads(p.read_text())
    return None


def _save_cache(data: dict):
    _cache_path().write_text(json.dumps(data))


def _machine_to_key(machine_type: str) -> str | None:
    """Convert 'n1-standard-4' → 'CP-COMPUTEENGINE-VMIMAGE-N1-STANDARD-4'."""
    upper = machine_type.upper()
    for prefix, key_prefix in _PREFIX_MAP.items():
        if machine_type.startswith(prefix):
            suffix = upper[len(prefix):]
            return key_prefix + suffix.replace("-", "-")
    return None


def fetch_gcp_prices(instance_types: set[str], region: str = "us-central1") -> dict[str, float]:
    cached = _load_cache()
    raw = cached

    if raw is None:
        print("  [INFO] Fetching GCP Compute Engine prices (cached for 24h)...")
        resp = httpx.get(_URL, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        _save_cache(raw)

    gcp_prices = raw.get("gcp_price_list", {})
    # Normalize region label (e.g. "us-central1" → "us")
    # The pricelist uses short region keys like "us", "europe", "asia"
    region_key = "us"
    if region.startswith("europe"):
        region_key = "europe"
    elif region.startswith("asia"):
        region_key = "asia"

    prices: dict[str, float] = {}
    for machine_type in instance_types:
        key = _machine_to_key(machine_type)
        if not key:
            continue
        entry = gcp_prices.get(key, {})
        # Try exact region, then "us" fallback
        cost = entry.get(region_key) or entry.get("us")
        if cost:
            prices[machine_type] = float(cost)

    return prices
