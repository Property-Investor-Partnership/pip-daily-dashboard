#!/usr/bin/env python3
"""Main-dashboard build step for the Raising & Pipeline tab.

Run by build.py after aggregate.py + supplement.py. Reads the investments CSV,
the companies CSV and config/raising_pipeline.json, computes the tab data with
the SHARED module scripts/raising_pipeline.py, and adds it to
dashboard_data_v2.json under "raising_pipeline".
"""
import csv, json, os, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import raising_pipeline as rp  # noqa: E402

ROOT = os.path.dirname(HERE)
CSV_PATH = (sys.argv[1] if len(sys.argv) > 1 else None) or os.environ.get("PIP_CSV")
JSON_PATH = os.environ.get("PIP_JSON") or os.path.join(HERE, "dashboard_data_v2.json")
COMPANIES_CSV = os.environ.get("PIP_COMPANIES_CSV") or os.path.join(ROOT, "data", "companies-export.csv")
CONFIG = os.environ.get("PIP_RP_CONFIG") or os.path.join(ROOT, "config", "raising_pipeline.json")


def now():
    v = os.environ.get("PIP_NOW")
    if v:
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            pass
    return datetime.now()


def read_rows(path):
    # Same collision-aware read as aggregate.py (two "Developer" columns).
    rdr = csv.reader(open(path, encoding="utf-8-sig"))
    hdr = next(rdr)
    keys, seen = [], {}
    for h in hdr:
        if h == "Developer":
            seen[h] = seen.get(h, 0) + 1
            keys.append("Developer" if seen[h] == 1 else "Developer (project)")
        else:
            keys.append(h)
    return [{k: (r[i] if i < len(r) else "") for i, k in enumerate(keys)} for r in rdr], keys


def main():
    if not CSV_PATH or not os.path.exists(CSV_PATH):
        raise SystemExit("raising_pipeline_step: investments CSV not found")
    rows, keys = read_rows(CSV_PATH)
    for col in ("Tranche Number", "Source Investment Project", "Payout Type"):
        if col not in keys:
            print("  WARN: column %r missing from the CSV (fetch_hubspot.py adds it)." % col)
    companies = []
    if os.path.exists(COMPANIES_CSV):
        companies = list(csv.DictReader(open(COMPANIES_CSV, encoding="utf-8-sig")))
    else:
        print("  WARN: companies CSV not found at", COMPANIES_CSV)
    cfg = {}
    if os.path.exists(CONFIG):
        cfg = json.load(open(CONFIG, encoding="utf-8"))
    projects = cfg.get("projects") or rp.auto_projects(companies, cfg.get("match_rules"))
    # include_rows=False: no investment names / record ids / advisers in the
    # main dashboard's data. Stage dropdowns show New Money / Rollover totals.
    data = rp.compute(rows, companies, now(), projects, include_rows=False)
    d = json.load(open(JSON_PATH, encoding="utf-8"))
    d["raising_pipeline"] = data
    json.dump(d, open(JSON_PATH, "w"), indent=2)
    print("Raising & Pipeline v%s: %d projects" % (rp.CORE_VERSION, len(data["projects"])))
    tr_filled = sum(1 for r in rows if (r.get("Tranche Number") or "").strip())
    print("  Tranche Number populated on %d of %d investments" % (tr_filled, len(rows)))
    rp.log_summary(data)


if __name__ == "__main__":
    main()
