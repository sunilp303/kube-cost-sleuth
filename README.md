# kube-cost-sleuth - DRAFT 

A Kubernetes cost analyzer that maps every pod's resource requests to the node it runs on, looks up that node's hourly cloud price, and ranks pods by how much money they're wasting.

```
  NAMESPACE        POD                          TYPE           $/HR   POD$/HR  CPU-REQ  CPU-USE  WASTE/HR  WASTE%
  payments         api-7d9b-xkj2p               m5.xlarge     $0.192   $0.028    500m     45m      $0.019   68.0%  ●
  default          idle-worker-6f8c             n1-standard-4 $0.150   $0.021   2000m     12m      $0.019   91.3%  ●
  staging          test-runner-abc123           m5.large      $0.096   $0.012    250m      —            —      —    ○ ⚑NO_LIMITS
```

---

## What it does

- **Calculates each pod's cost share** — `node_cost × (pod_cpu_requests / node_allocatable_cpu)`
- **Measures waste** — cost of requested-but-unused resources, using live metrics-server data when available
- **Flags problems** without metrics: `NO_REQUESTS` (pod has no resource requests), `NO_LIMITS` (pod has no CPU/memory limits)
- **Auto-detects cloud provider** from node labels (AWS, GCP, Azure) and fetches live on-demand pricing — no configuration required
- **Falls back to a CSV price file** for on-prem clusters or custom pricing
- **Outputs** a terminal table, JSON (pipeable to `jq`), or a self-contained HTML report with a bar chart and sortable table

---

## Requirements

- Python 3.10+
- `kubectl` configured with a valid kubeconfig
- `httpx` (`pip install -r requirements.txt`)
- `kubectl top` (optional) — requires [metrics-server](https://github.com/kubernetes-sigs/metrics-server) for live waste calculation

---

## Quick Start

```bash
git clone https://github.com/sunilp303/kube-cost-sleuth.git
cd kube-cost-sleuth
pip install -r requirements.txt
python cost_analyzer.py
```

---

## Output formats

| Flag | Output |
|---|---|
| _(default)_ | Colored terminal table, top 20 pods by waste |
| `--output=json` | JSON — pipeable to `jq` |
| `--output=html` | Self-contained HTML report with chart + sortable table |

---

## Cloud pricing support

| Provider | How | Auth needed? |
|---|---|---|
| AWS | EC2 Pricing API (public) | No |
| GCP | GCP Pricing Calculator JSON (public) | No |
| Azure | Azure Retail Prices API (public) | No |
| Generic / on-prem | User-supplied `prices.csv` | N/A |

Prices are **cached for 24 hours** in `~/.cache/k8s-cost-analyzer/` — the first run fetches from the API, subsequent runs are instant.

---

## Project structure

```
k8s-cost-analyzer/
├── cost_analyzer.py       # CLI entry point
├── k8s_client.py          # kubectl wrapper (nodes, pods, metrics)
├── waste_calculator.py    # Cost model and waste math
├── report_html.py         # Self-contained HTML report generator
├── providers/
│   ├── __init__.py        # Provider detection + price aggregation
│   ├── aws.py             # AWS Pricing API
│   ├── gcp.py             # GCP Billing SKU API
│   ├── azure.py           # Azure Retail Prices API
│   └── generic.py         # CSV price file loader
├── prices.csv.example     # Template for custom pricing
├── requirements.txt
├── README.md
└── HOW_TO_USE.md          # Detailed usage guide with examples
```

---

## Cost model

```
pod_cpu_share   = pod_total_req_cpu_m / node_allocatable_cpu_m
pod_cost_hr     = node_cost_hr × pod_cpu_share

# With metrics-server:
waste_frac      = (req_cpu_m − actual_cpu_m) / req_cpu_m
waste_cost_hr   = pod_cost_hr × waste_frac
```

This is a CPU-weighted cost model — the same approach used by tools like Kubecost and OpenCost.

---

See [HOW_TO_USE.md](HOW_TO_USE.md) for detailed examples, flag explanations, and integration patterns.
