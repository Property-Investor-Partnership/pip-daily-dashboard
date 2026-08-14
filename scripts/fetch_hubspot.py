#!/usr/bin/env python3
"""
fetch_hubspot.py — Pull the PIP "investments" custom object from HubSpot and
write a CSV matching the manual HubSpot export the dashboard scripts expect.

Auth:
  Reads a HubSpot Private App token from env var HUBSPOT_TOKEN.
    export HUBSPOT_TOKEN=pat-xxxx        # locally
  In GitHub Actions the token comes from an encrypted repo Secret (same env var).

Why the Search API + id cursor:
  The plain /objects list endpoint silently caps at ~2,500 records, and the
  Search endpoint caps at 10,000 per query. We page by hs_object_id > last_seen
  (ascending), which walks past both caps and reliably returns ALL records.

Output:
  Writes data/investment-export.csv (override with env PIP_OUT_CSV).
"""
import os, sys, csv, json, time, urllib.request, urllib.error

OBJECT_TYPE = "2-143899386"          # investments custom object
BASE = "https://api.hubapi.com"
TOKEN = os.environ.get("HUBSPOT_TOKEN", "").strip()
PAGE_SIZE = 200

# CSV column label -> HubSpot API property name (verified against live schema).
COLUMN_MAP = [
    ("Record ID",                     "hs_object_id"),
    ("Name",                          "name"),
    ("Servicing Adviser",             "advisor"),
    ("Selling Adviser",               "selling_adviser"),
    ("Investment Project",            "investment_project"),
    ("Interest Rate",                 "interest_rate"),
    ("Payout Type",                   "payout_type"),
    ("Investment pipeline stage",     "hs_pipeline_stage"),   # ID -> label
    ("Investment pipeline",           "hs_pipeline"),
    ("Start Date",                    "start_date"),
    ("Estimated End Date",            "estimated_end_date"),
    ("Project Term",                  "project_term"),
    ("End Date",                      "end_date"),
    ("Accumulated Interest",          "accumulated_interest"),
    ("Full Valuation",                "full_valuation"),
    ("Advice Type",                   "advice_type"),
    ("Money Received On",             "money_received_on"),
    ("Is Pension",                    "is_pension"),
    ("Active Pipeline True or False", "active_pipeline_true_or_false"),
    ("Developer",                     "developer"),
    ("Rollover Amount",               "rollover_amount"),
    ("Rollover Capital",              "rollover_capital"),
    ("Rollover Interest",             "rollover_interest"),
    ("Client Email",                  "client_email"),
    ("Client Company",                "client_company"),
    ("Live Investment Status",        "investment_status_b"),
    ("Investment",                    "investment"),
    ("Live Investment Amount",        "live_investment_amount"),
    ("Valuation",                     "valuation"),
    ("Total Accumulated Interest",    "total_accumulated_interest"),
    ("Estimated Interest Paid",       "estimated_interest_paid"),
    ("Exclude from this Month's Raising Req", "exclude_from_this_months_raising_req"),
]
# The export carries a second "Developer" column ("Developer (project)").
DUPLICATE_DEVELOPER = True


def _req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Content-Type", "application/json")
    last_err = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt
                sys.stderr.write(f"  429 rate-limited; retry in {wait}s\n")
                time.sleep(wait)
                continue
            last_err = f"HTTP {e.code}: {e.read().decode()[:400]}"
        except Exception as e:
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"Request failed after retries on {path}: {last_err}")


def load_stage_labels():
    d = _req("GET", f"/crm/v3/pipelines/{OBJECT_TYPE}")
    labels = {}
    for pl in d.get("results", []):
        for st in pl.get("stages", []):
            labels[st["id"]] = st.get("label", st["id"])
    return labels


def load_enum_labels(prop):
    try:
        d = _req("GET", f"/crm/v3/properties/{OBJECT_TYPE}/{prop}")
    except SystemExit:
        return {}
    return {o["value"]: o.get("label", o["value"]) for o in d.get("options", [])}


def load_owner_labels():
    """Map HubSpot owner IDs (returned as strings by owner-type properties)
    to a human-readable name. Falls back to email if the owner has no first
    or last name populated. Requires the `crm.objects.owners.read` scope.
    Returns {} on error so any fetch failure just leaves the raw IDs in
    place rather than blowing up the whole export.
    """
    out = {}
    after = None
    try:
        while True:
            path = "/crm/v3/owners?limit=100"
            if after:
                path += f"&after={after}"
            d = _req("GET", path)
            for o in d.get("results", []):
                oid = str(o.get("id", "")).strip()
                if not oid:
                    continue
                first = (o.get("firstName") or "").strip()
                last = (o.get("lastName") or "").strip()
                name = (first + " " + last).strip()
                if not name:
                    name = (o.get("email") or "").strip()
                if name:
                    out[oid] = name
            paging = d.get("paging", {}).get("next", {})
            after = paging.get("after")
            if not after:
                break
    except SystemExit:
        return out
    return out


def fetch_all(props):
    """Page by hs_object_id cursor to retrieve every record."""
    out, seen, last_id = [], set(), 0
    while True:
        body = {
            "limit": PAGE_SIZE,
            "properties": props,
            "sorts": [{"propertyName": "hs_object_id", "direction": "ASCENDING"}],
            "filterGroups": [{"filters": [
                {"propertyName": "hs_object_id", "operator": "GT", "value": str(last_id)}
            ]}],
        }
        d = _req("POST", f"/crm/v3/objects/{OBJECT_TYPE}/search", body)
        res = d.get("results", [])
        if not res:
            break
        for r in res:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append(r)
        last_id = res[-1]["id"]
        sys.stderr.write(f"  fetched {len(out)} (last id {last_id})\n")
        if len(res) < PAGE_SIZE:
            break
        time.sleep(0.15)
    return out


def main():
    if not TOKEN:
        sys.stderr.write("ERROR: HUBSPOT_TOKEN env var not set.\n")
        # In sandbox testing, auth is injected via proxy, so continue; in
        # Actions this is fatal.
    out_csv = os.environ.get("PIP_OUT_CSV", "data/investment-export.csv")

    sys.stderr.write("Loading pipeline stage labels...\n")
    stage_labels = load_stage_labels()
    sys.stderr.write("Loading dropdown labels...\n")
    payout_labels = load_enum_labels("payout_type")
    advice_labels = load_enum_labels("advice_type")
    owner_labels = load_owner_labels()
    sys.stderr.write(f"  {len(owner_labels)} owners resolved\n")
    # Owner-type properties on investments — replace numeric HubSpot User IDs
    # with real names so the CSV and downstream dashboard show "Jason Howard"
    # rather than "31139710".
    OWNER_PROPS = {"advisor", "selling_adviser"}

    props = sorted({api for _, api in COLUMN_MAP})
    sys.stderr.write(f"Fetching all records ({len(props)} properties)...\n")
    records = fetch_all(props)
    sys.stderr.write(f"Total records: {len(records)}\n")

    headers = [c for c, _ in COLUMN_MAP]
    if DUPLICATE_DEVELOPER:
        headers.append("Developer (project)")

    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    tmp = out_csv + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for rec in records:
            p = rec.get("properties", {})
            row = []
            for _, api in COLUMN_MAP:
                v = p.get(api, "")
                if v is None:
                    v = ""
                if api == "hs_pipeline_stage" and v:
                    v = stage_labels.get(str(v), v)
                elif api == "payout_type" and v:
                    v = payout_labels.get(str(v), v)
                elif api == "advice_type" and v:
                    v = advice_labels.get(str(v), v)
                elif api in OWNER_PROPS and v:
                    v = owner_labels.get(str(v), v)
                row.append(v)
            if DUPLICATE_DEVELOPER:
                row.append(p.get("developer", "") or "")
            w.writerow(row)
    os.replace(tmp, out_csv)  # atomic
    sys.stderr.write(f"Wrote {len(records)} rows -> {out_csv}\n")
    print(out_csv)

    # ------------------------------------------------------------------
    # Also fetch companies (developer/project + client) so the aggregate
    # step can compute the monthly raising-progress rollup. Uses the
    # crm.objects.companies.read + crm.schemas.companies.read scopes.
    # Non-fatal on error: if this fails, the raising_progress section is
    # simply hidden on the dashboard.
    # ------------------------------------------------------------------
    try:
        fetch_companies_csv()
    except SystemExit as e:
        # SystemExit from _req is fatal for the investments fetch (the
        # dashboard cannot render without it), but the companies fetch is
        # optional — log and continue so the workflow still completes.
        sys.stderr.write(f"WARN: companies fetch failed: {e}\n")
    except Exception as e:
        sys.stderr.write(f"WARN: companies fetch failed: {e}\n")


# ============================================================================
# COMPANIES FETCH — for the raising-progress dashboard section.
# ============================================================================
COMPANY_COLUMN_MAP = [
    ("Record ID",                        "hs_object_id"),
    ("Company name",                     "name"),
    ("Company Type",                     "company_type"),
    ("Monthly Raising Requirement",      "monthly_raising_requirement"),
    ("Raising Requirements",             "raising_requirements"),
    ("Sub Projects (String)",            "sub_projects_string"),
]


def fetch_all_companies(props):
    """Page through /crm/v3/objects/companies/search using hs_object_id cursor.

    Same cursor pattern as the investments fetch — walks past both the
    2,500-record list cap and the 10,000-per-query search cap.
    """
    out, seen, last_id = [], set(), 0
    while True:
        body = {
            "limit": PAGE_SIZE,
            "properties": props,
            "sorts": [{"propertyName": "hs_object_id", "direction": "ASCENDING"}],
            "filterGroups": [{"filters": [
                {"propertyName": "hs_object_id", "operator": "GT", "value": str(last_id)}
            ]}],
        }
        d = _req("POST", "/crm/v3/objects/companies/search", body)
        res = d.get("results", [])
        if not res:
            break
        for r in res:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append(r)
        last_id = res[-1]["id"]
        sys.stderr.write(f"  companies fetched {len(out)} (last id {last_id})\n")
        if len(res) < PAGE_SIZE:
            break
        time.sleep(0.15)
    return out


def load_company_enum_labels(prop):
    """Company object schema uses /properties/companies/{prop} (built-in object)."""
    try:
        d = _req("GET", f"/crm/v3/properties/companies/{prop}")
    except SystemExit:
        return {}
    return {o["value"]: o.get("label", o["value"]) for o in d.get("options", [])}


def fetch_companies_csv():
    out_csv = os.environ.get("PIP_COMPANIES_CSV", "data/companies-export.csv")

    sys.stderr.write("Loading company_type dropdown labels...\n")
    company_type_labels = load_company_enum_labels("company_type")

    props = sorted({api for _, api in COMPANY_COLUMN_MAP})
    sys.stderr.write(f"Fetching all companies ({len(props)} properties)...\n")
    records = fetch_all_companies(props)
    sys.stderr.write(f"Total companies: {len(records)}\n")

    headers = [c for c, _ in COMPANY_COLUMN_MAP]
    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    tmp = out_csv + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for rec in records:
            p = rec.get("properties", {})
            row = []
            for _, api in COMPANY_COLUMN_MAP:
                v = p.get(api, "")
                if v is None:
                    v = ""
                if api == "company_type" and v:
                    v = company_type_labels.get(str(v), v)
                row.append(v)
            w.writerow(row)
    os.replace(tmp, out_csv)
    sys.stderr.write(f"Wrote {len(records)} company rows -> {out_csv}\n")


if __name__ == "__main__":
    main()
