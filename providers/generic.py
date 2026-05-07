"""Load instance type pricing from a user-supplied CSV file."""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def load_csv_prices(path: str) -> dict[str, float]:
    p = Path(path)
    if not p.exists():
        print(f"ERROR: price file not found: {path}", file=sys.stderr)
        sys.exit(1)

    prices: dict[str, float] = {}
    with p.open() as f:
        for row in csv.DictReader(f):
            if row.get("instance_type", "").startswith("#"):
                continue
            itype = row.get("instance_type", "").strip()
            cost  = row.get("cost_per_hour", "").strip()
            if itype and cost:
                try:
                    prices[itype] = float(cost)
                except ValueError:
                    pass

    return prices
