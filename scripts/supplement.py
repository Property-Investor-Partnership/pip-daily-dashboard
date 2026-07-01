"""Supplement the June-24 aggregate2.py output with the June-25 additions that were
lost in the sandbox reset: completions, pending, live.aum_by_developer, and the
extra totals (live_estimated_income_paid, pending_total, pending_count).

Run AFTER aggregate2.py has produced dashboard_data_v2.json. Reads the same CSV,
computes the missing sections, and merges them into dashboard_data_v2.json so the
full structure matches the live dashboard exactly.

Definitions were reverse-engineered from the live baked DATA and verified against
stable historical periods (e.g. 2024 completions matched to the penny).
"""
import csv, json, os, sys, os
from collections import defaultdict, OrderedDict
from datetime import datetime, timedelta

P = sys.argv[1] if len(sys.argv) > 1 else None
if not P or not os.path.exists(P):
    raise SystemExit("Usage: python3 supplement_v2.py <csv_path>")
def _pip_now():
    v=os.environ.get("PIP_NOW")
    if v:
        try: return datetime.fromisoformat(v)
        except Exception: pass
    return datetime.now()
NOW = _pip_now()
JSON_PATH = os.environ.get("PIP_JSON") or os.path.join(os.path.dirname(os.path.abspath(__file__)),"dashboard_data_v2.json")

# --- collision-aware read (identical to aggregate2.py) ---
rdr = csv.reader(open(P, encoding="utf-8-sig"))
hdr = next(rdr); seen = {}; keys = []
for h in hdr:
    if h == "Developer":
        seen[h] = seen.get(h, 0) + 1
        keys.append("Developer" if seen[h] == 1 else "Developer (project)")
    else:
        keys.append(h)
rows = [{k: (r[i] if i < len(r) else "") for i, k in enumerate(keys)} for r in rdr]

def num(s):
    s = str(s or "").strip().replace(",", "").replace("£", "").replace("%", "")
    if s == "" or s.lower() in ("nan", "none", "null"): return None
    try: return float(s)
    except: return None

def pdate(s):
    s = (s or "").strip()
    if not s: return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y", "%Y/%m/%d"):
        try: return datetime.strptime(s[:19] if "T" in s else s, fmt)
        except: pass
    try: return datetime.fromisoformat(s.replace("Z", ""))
    except: return None

def gv(r, f): return (r.get(f, "") or "").strip()
def stage(r): return gv(r, "Investment pipeline stage").lower()

live = [r for r in rows if gv(r, "Live Investment Status").lower() == "true"]

# ============== completions (capital that went live by Start Date) ==============
# value = "Investment"; grouped by "Developer (project)" -> "Investment Project"
def start_dt(r): return pdate(r.get("Start Date"))

# week starts Monday of the current week
week_start = (NOW - timedelta(days=NOW.weekday()))
week_start = datetime(week_start.year, week_start.month, week_start.day)
month_start = datetime(NOW.year, NOW.month, 1)
year_start = datetime(NOW.year, 1, 1)

YEARS = sorted({d.year for r in rows if (d := start_dt(r))})
# keep the same span the live dashboard used (2017..current)
YEARS = [y for y in YEARS if y >= 2017]

def build_period(records):
    """Group a record list into the developer->project->total/count structure."""
    total = 0.0; count = 0
    dev = defaultdict(lambda: {"total": 0.0, "count": 0, "projects": defaultdict(lambda: [0, 0.0])})
    for r in records:
        amt = num(r.get("Investment")) or 0
        total += amt; count += 1
        d = gv(r, "Developer (project)") or "(blank)"
        proj = gv(r, "Investment Project") or "(blank)"
        dev[d]["total"] += amt; dev[d]["count"] += 1
        dev[d]["projects"][proj][0] += 1; dev[d]["projects"][proj][1] += amt
    devs = []
    for dname, dd in sorted(dev.items(), key=lambda x: -x[1]["total"]):
        projs = [{"project": p, "total": round(v[1], 2), "count": v[0]}
                 for p, v in sorted(dd["projects"].items(), key=lambda x: -x[1][1])]
        devs.append({"developer": dname, "total": round(dd["total"], 2),
                     "count": dd["count"], "projects": projs})
    return {"total": round(total, 2), "count": count, "developers": devs}

def is_live(r): return gv(r, "Live Investment Status").lower() == "true"
def has_end_date(r): return gv(r, "End Date") != ""

def went_live(r):
    # "Capital that has gone live to date" inclusion rule (client, 26 Jun 2026):
    #   - include if Live Investment Status = true (currently live), OR
    #   - include if not live BUT an End Date is known (it matured = was live in the past).
    # Exclude if not live AND no End Date (never went live: future-dated / not-yet-started,
    # or pending/written that never progressed). This drops the 42 future-dated investments
    # while preserving all historically-matured ones.
    return is_live(r) or has_end_date(r)

def in_range(r, lo, hi=None):
    if not went_live(r): return False
    d = start_dt(r)
    if not d: return False
    if d < lo: return False
    if hi and d >= hi: return False
    return True

periods = OrderedDict()
periods["wtd"] = build_period([r for r in rows if in_range(r, week_start)])
periods["mtd"] = build_period([r for r in rows if in_range(r, month_start)])
periods["ytd"] = build_period([r for r in rows if in_range(r, year_start)])
for y in YEARS:
    lo = datetime(y, 1, 1); hi = datetime(y + 1, 1, 1)
    periods[str(y)] = build_period([r for r in rows if in_range(r, lo, hi)])

completions = {
    "as_at": NOW.strftime("%Y-%m-%d"),
    "available": True,
    "default_period": "mtd",
    "week_start": week_start.strftime("%Y-%m-%d"),
    "years": YEARS,
    "periods": periods,
}

# ============== pending (stage == Money Received) by Investment Project ==============
# Client definition (26 Jun 2026): the dashboard is for the boss, who views "Money Received"
# as pending — the money is in but the investment has not gone live yet. (There is also a
# separate "Pending" pipeline stage, but that is NOT what this box should use.)
pend = [r for r in rows if stage(r) == "money received"]
pp = defaultdict(lambda: [0, 0.0])
for r in pend:
    k = gv(r, "Investment Project") or "(blank)"
    pp[k][0] += 1; pp[k][1] += num(r.get("Investment")) or 0
pending_by_project = [{"project": k, "total": round(v[1], 2), "count": v[0]}
                      for k, v in sorted(pp.items(), key=lambda x: -x[1][1])]
pending_total = round(sum(v[1] for v in pp.values()), 2)
pending_count = sum(v[0] for v in pp.values())
pending = {"total": pending_total, "count": pending_count, "by_project": pending_by_project}

# ============== live.aum_by_developer (by "Developer (project)") ==============
ad = defaultdict(lambda: [0, 0.0])
for r in live:
    k = gv(r, "Developer (project)") or "(blank)"
    ad[k][0] += 1; ad[k][1] += num(r.get("Live Investment Amount")) or 0
aum_by_developer = [{"developer": k, "total": round(v[1], 2), "count": v[0]}
                    for k, v in sorted(ad.items(), key=lambda x: -x[1][1])]

# ============== extra totals ==============
live_estimated_income_paid = round(
    sum(num(r.get("Estimated Interest Paid")) or 0 for r in live), 2)

# ============== merge into existing JSON ==============
data = json.load(open(JSON_PATH))
data["completions"] = completions
data["pending"] = pending
data["live"]["aum_by_developer"] = aum_by_developer
data["totals"]["live_estimated_income_paid"] = live_estimated_income_paid
data["totals"]["pending_total"] = pending_total
data["totals"]["pending_count"] = pending_count

# Re-order top-level to match the live structure (generated_at, currency, completions,
# pending, totals, live, book) for cleanliness.
ordered = OrderedDict()
for k in ["generated_at", "currency", "completions", "pending", "totals", "live", "book"]:
    if k in data:
        ordered[k] = data[k]
for k in data:
    if k not in ordered:
        ordered[k] = data[k]

json.dump(ordered, open(JSON_PATH, "w"), indent=2)
print("MERGED supplement into dashboard_data_v2.json")
print("completions: wtd %.0f/%d  mtd %.0f/%d  ytd %.0f/%d  years=%s" % (
    periods["wtd"]["total"], periods["wtd"]["count"],
    periods["mtd"]["total"], periods["mtd"]["count"],
    periods["ytd"]["total"], periods["ytd"]["count"], YEARS))
print("pending: %.0f / %d  (top: %s)" % (
    pending_total, pending_count,
    pending_by_project[0]["project"] if pending_by_project else "-"))
print("aum_by_developer top3:", [(d["developer"], d["total"]) for d in aum_by_developer[:3]])
print("live_estimated_income_paid:", live_estimated_income_paid)
