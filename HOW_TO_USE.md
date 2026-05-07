# How to Use k8s-cost-analyzer

## Installation

```bash
git clone https://github.com/sunilp303/kube-cost-sleuth.git
cd k8s-cost-analyzer
pip install -r requirements.txt
```

Verify kubectl is configured:
```bash
kubectl cluster-info
```

---

## Basic Usage

```bash
python cost_analyzer.py
```

This runs against your current kubectl context, scans all namespaces, fetches cloud pricing automatically, and prints the top 20 most wasteful pods.

---

## All Options

```
--namespace=NS       Scope to one namespace (default: all namespaces)
--output=FORMAT      table | json | html  (default: table)
--html-out=FILE      HTML report filename  (default: k8s-cost-report.html)
--price-file=FILE    CSV with instance_type,cost_per_hour columns
--sort=FIELD         waste | cost | name  (default: waste)
--top=N              Show top N pods — 0 means all  (default: 20)
--no-metrics         Skip metrics-server, show estimates and flags only
```

---

## Common Examples

### See the most wasteful pods across the whole cluster

```bash
python cost_analyzer.py
```

### Focus on a single namespace

```bash
python cost_analyzer.py --namespace=production
```

### Show all pods, sorted by pod cost (not waste)

```bash
python cost_analyzer.py --top=0 --sort=cost
```

### Generate an HTML report to share with your team

```bash
python cost_analyzer.py --output=html --html-out=cost-report.html
open cost-report.html   # macOS
# or: start cost-report.html  (Windows)
```

The HTML file is fully self-contained — no internet connection needed to open it.

### Get JSON output and pipe to jq

```bash
# Summary only
python cost_analyzer.py --output=json | jq .summary

# Pods wasting more than $0.01/hr
python cost_analyzer.py --output=json | jq '[.pods[] | select(.waste_cost_hr > 0.01)]'

# List all flagged pods
python cost_analyzer.py --output=json | jq '[.pods[] | select(.flags | length > 0)]'
```

### Run without metrics-server (flag-based analysis only)

```bash
python cost_analyzer.py --no-metrics
```

Waste % and waste $/hr columns will show `—`, but `NO_REQUESTS` and `NO_LIMITS` flags still appear. These flags alone are actionable.

### Use a custom price file (on-prem or override cloud prices)

```bash
cp prices.csv.example prices.csv
# Edit prices.csv with your actual instance costs
python cost_analyzer.py --price-file=prices.csv
```

You can also use `--price-file` alongside cloud pricing — the CSV values take precedence over the API for any instance types listed in the file.

---

## Understanding the Output

### Terminal table columns

| Column | Description |
|---|---|
| NAMESPACE | Pod namespace |
| POD | Pod name |
| TYPE | Node instance type (e.g. `m5.xlarge`, `n1-standard-4`) |
| NODE $/HR | Full hourly cost of the node this pod runs on |
| POD $/HR | This pod's cost share: `node_cost × (req_cpu / node_cpu)` |
| CPU-REQ | Total CPU requested across all containers (millicores) |
| CPU-USE | Actual CPU used (from metrics-server) — `—` if unavailable |
| MEM-REQ | Total memory requested |
| WASTE $/HR | Cost of requested-but-unused CPU — `—` if no metrics |
| WASTE % | `(req − actual) / req × 100` — red ≥70%, yellow ≥40% |
| FLAGS | `⚑NO_REQUESTS`, `⚑NO_LIMITS` (see below) |

### Metrics indicator

| Symbol | Meaning |
|---|---|
| `●` (green) | Live metrics from metrics-server |
| `○` (dim) | No metrics — cost is estimated from requests only |

### Flags

| Flag | What it means | Why it matters |
|---|---|---|
| `NO_REQUESTS` | Pod has no CPU or memory requests set | K8s scheduler treats this pod as free — it gets scheduled anywhere and can starve other pods |
| `NO_LIMITS` | At least one container has no CPU/memory limits | Pod can consume unlimited resources and evict neighbors |

Both flags appear even without metrics-server and are immediately actionable.

---

## Cloud Pricing

The tool auto-detects your cloud provider from node labels and fetches current on-demand prices:

| Provider | Detection label | API |
|---|---|---|
| AWS | `eks.amazonaws.com/nodegroup` | AWS Pricing API (public) |
| GCP | `cloud.google.com/gke-nodepool` | GCP Pricing Calculator JSON (public) |
| Azure | `kubernetes.azure.com/cluster` | Azure Retail Prices API (public) |

**No credentials are required** — all three APIs are publicly accessible.

Prices are cached in `~/.cache/k8s-cost-analyzer/` for 24 hours. To force a refresh:

```bash
rm -rf ~/.cache/k8s-cost-analyzer/
python cost_analyzer.py
```

If cloud detection fails or you're on a non-cloud cluster, supply a price file:

```bash
python cost_analyzer.py --price-file=prices.csv
```

Format (`prices.csv.example` contains a template):

```
instance_type,cost_per_hour
m5.xlarge,0.192
n1-standard-4,0.190
Standard_D4s_v3,0.192
```

---

## Integrating into CI / Daily Reports

### Save a daily report via cron

```bash
# crontab entry — run at 8am, save HTML report
0 8 * * * cd /path/to/k8s-cost-analyzer && python cost_analyzer.py \
  --output=html --html-out=/var/www/html/k8s-cost-$(date +\%Y-\%m-\%d).html
```

### Post waste summary to Slack

```bash
python cost_analyzer.py --output=json | jq -r \
  '"K8s waste today: $" + (.summary.total_waste_hr|tostring) + "/hr (" + (.summary.waste_pct|tostring) + "%)"' \
  | xargs -I{} curl -s -X POST "$SLACK_WEBHOOK_URL" -d "{\"text\":\"{}\"}"
```

### Alert if waste exceeds a threshold

```bash
WASTE=$(python cost_analyzer.py --output=json | jq '.summary.waste_pct')
if (( $(echo "$WASTE > 50" | bc -l) )); then
  echo "ALERT: cluster waste is ${WASTE}%" | mail -s "K8s cost alert" team@example.com
fi
```

### Use with k8s-triage

Run cost analysis after a triage scan to understand the financial impact of findings:

```bash
./triage.sh --layer=workloads --no-color | tee triage-workloads.txt
python cost_analyzer.py --namespace=production --output=json | jq .summary
```

---

## Troubleshooting

**"kubectl not found"**
Install kubectl and ensure it's in your `PATH`. Verify with `kubectl version`.

**"No price found for instance type X"**
The cloud pricing API didn't return a price for that instance type. Supply a `--price-file` with the correct price, or check that your node labels include `node.kubernetes.io/instance-type`.

**Waste column shows `—` for all pods**
metrics-server is not installed. Install it:
```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```
Or run with `--no-metrics` to get flag-based analysis without waste percentages.

**Cost is $0.00 for all pods**
No prices were found for any instance type. Check:
```bash
kubectl get nodes -o json | jq -r '.items[].metadata.labels | to_entries[] | select(.key | contains("instance")) | .value'
```
Then supply those exact values in a `--price-file`.

**Prices seem outdated**
Delete the cache and re-run:
```bash
rm -rf ~/.cache/k8s-cost-analyzer/
```
