"""
AWS EC2 on-demand pricing via the public AWS Pricing API (no credentials required).
Results are cached to ~/.cache/k8s-cost-analyzer/aws-{region}.json for 24 hours.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

CACHE_DIR = Path.home() / ".cache" / "k8s-cost-analyzer"
CACHE_TTL = 86400  # 24 hours

# Per-region pricing index (smaller than the global index.json)
_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/{region}/index.json"


def _cache_path(region: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"aws-{region}.json"


def _load_cache(region: str) -> dict | None:
    p = _cache_path(region)
    if p.exists() and (time.time() - p.stat().st_mtime) < CACHE_TTL:
        return json.loads(p.read_text())
    return None


def _save_cache(region: str, data: dict):
    _cache_path(region).write_text(json.dumps(data))


def fetch_aws_prices(instance_types: set[str], region: str = "us-east-1") -> dict[str, float]:
    cached = _load_cache(region)
    if cached:
        return cached

    print(f"  [INFO] Fetching AWS EC2 prices for {region} (cached for 24h)...")
    url = _URL.format(region=region)

    with httpx.stream("GET", url, timeout=60, follow_redirects=True) as resp:
        resp.raise_for_status()
        raw = json.loads(resp.read())

    prices: dict[str, float] = {}
    products = raw.get("products", {})
    terms = raw.get("terms", {}).get("OnDemand", {})

    for sku, product in products.items():
        attrs = product.get("attributes", {})
        if (
            attrs.get("operatingSystem") != "Linux"
            or attrs.get("tenancy") != "Shared"
            or attrs.get("preInstalledSw") != "NA"
            or attrs.get("capacitystatus") != "Used"
        ):
            continue
        itype = attrs.get("instanceType", "")
        if not itype:
            continue

        sku_terms = terms.get(sku, {})
        for offer in sku_terms.values():
            for pd in offer.get("priceDimensions", {}).values():
                usd = float(pd["pricePerUnit"].get("USD", 0))
                if usd > 0:
                    prices[itype] = usd
                    break

    _save_cache(region, prices)
    return prices
