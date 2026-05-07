"""
Azure VM pricing via the public Azure Retail Prices API (no auth required).
https://prices.azure.com/api/retail/prices
Cached 24h.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

CACHE_DIR = Path.home() / ".cache" / "k8s-cost-analyzer"
CACHE_TTL = 86400

_BASE_URL = "https://prices.azure.com/api/retail/prices"


def _cache_path(region: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"azure-{region}.json"


def _load_cache(region: str) -> dict | None:
    p = _cache_path(region)
    if p.exists() and (time.time() - p.stat().st_mtime) < CACHE_TTL:
        return json.loads(p.read_text())
    return None


def _save_cache(region: str, data: dict):
    _cache_path(region).write_text(json.dumps(data))


def fetch_azure_prices(instance_types: set[str], region: str = "eastus") -> dict[str, float]:
    cached = _load_cache(region)
    if cached:
        return {k: v for k, v in cached.items() if k in instance_types}

    print(f"  [INFO] Fetching Azure VM prices for {region} (cached for 24h)...")

    # Azure uses "armRegionName" for filtering
    filter_str = (
        f"serviceName eq 'Virtual Machines' "
        f"and priceType eq 'Consumption' "
        f"and armRegionName eq '{region}'"
    )

    all_items: list[dict] = []
    url = _BASE_URL
    params = {"$filter": filter_str, "api-version": "2023-01-01-preview"}

    while url:
        resp = httpx.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        all_items.extend(data.get("Items", []))
        url = data.get("NextPageLink")
        params = {}  # pagination link already has params

    # Build {skuName → retailPrice} for Linux, non-spot, non-low-priority
    prices: dict[str, float] = {}
    for item in all_items:
        sku = item.get("skuName", "")
        if "Windows" in sku or "Spot" in sku or "Low Priority" in sku:
            continue
        # skuName looks like "D4s v3" — we want "Standard_D4s_v3"
        # armSkuName is the clean key
        arm_sku = item.get("armSkuName", "")
        price = item.get("retailPrice", 0)
        if arm_sku and price > 0:
            prices[arm_sku] = price

    _save_cache(region, prices)
    return {k: v for k, v in prices.items() if k in instance_types}
