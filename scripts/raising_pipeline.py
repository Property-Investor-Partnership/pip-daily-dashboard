#!/usr/bin/env python3
"""
raising_pipeline.py — SHARED module for the "Raising & Pipeline" view.

This exact file lives in BOTH repos:
  * pip-daily-dashboard            (main dashboard, new "Raising & Pipeline" tab)
  * the standalone raising repo    (single-project page)
Keep the two copies identical. CORE_VERSION is shown in the page footer so you
can see at a glance that both sides are on the same version.

Input rows use the same column LABELS as the main dashboard CSV
(fetch_hubspot.py COLUMN_MAP), so the logic is identical in both repos:
  Investments: Record ID, Name, Servicing Adviser, Investment Project,
               Investment pipeline stage, Start Date, Investment,
               Exclude from this Month's Raising Req, Tranche Number,
               Source Investment Project, Payout Type
  Companies:   Company name, Company Type, Raising Requirements,
               Monthly Raising Requirement, Sub Projects (String)

Rules (agreed with Djinh, Oct 2026):
  * NTU investments are excluded from everything.
  * "Started" = known Start Date on or before the data pull date (UK).
  * Takeover = Name contains "takeover" (case-insensitive). Excluded from ALL
    headline figures (started total, New Money / Rollover split, money
    received, current tranche). Still shown in the pipeline bar, the stage
    lists (own "Takeovers" group) and the tranche table.
  * Rollover = Name contains "rollover" or "extension"; New Money = neither
    (and not a takeover).
  * Total view: left to raise = Raising Requirements - started total.
    Negative -> "target exceeded".
  * Monthly view: started = Start Date in the current month and <= pull date,
    "Exclude from this Month's Raising Req" = true rows removed; left to raise
    = Monthly Raising Requirement - monthly started - money received (flagged
    rows removed), mirroring the existing Raising Progress monthly card.
  * Current tranche = lowest Tranche Number among Money Received investments.
    Headline total = Money Received investments in that tranche.
  * Pipeline figure = Pending + Forms Out + Written + Money Received
    (takeovers included), split B = Payout Type contains "bullet",
    Q = Payout Type contains "quarterly" (v1.1.0).
  * Main box sub stat adds Bullet / Quarterly totals of the same
    investments the box counts: total view = started; monthly view = started
    this month + money received (flagged rows removed). Takeovers excluded
    (v1.2.0).
  * include_rows=False (main dashboard) leaves every investment name, record
    id and adviser out of the data; stages carry New Money / Rollover /
    Takeover totals and counts only (v1.1.0).
  * Tranche table = started investments grouped by Tranche Number, with a
    subtotal per distinct Start Date. Blank tranche -> "No tranche" (last).
"""
import re
from collections import defaultdict
from datetime import datetime

CORE_VERSION = "1.2.0"

HUBSPOT_PORTAL = "146042580"
INVESTMENT_OBJECT = "2-143899386"
RECORD_URL = "https://app-eu1.hubspot.com/contacts/%s/record/%s/%%s" % (HUBSPOT_PORTAL, INVESTMENT_OBJECT)

# Bar stages (in order) and the extra stage shown only in the stage lists.
BAR_STAGES = [
    ("pending",        "Pending"),
    ("forms_out",      "Forms Out"),
    ("written",        "Written (processed form)"),
    ("money_received", "Money Received"),
]
LIST_STAGES = BAR_STAGES + [("project_live", "Project Live")]

# HubSpot stage label (lower-cased) -> stage key
_STAGE_KEY = {
    "pending": "pending",
    "forms out": "forms_out",
    "written": "written",
    "written (processed form)": "written",
    "money received": "money_received",
    "project live": "project_live",
}
_NTU = {"ntu"}


# ---------------------------------------------------------------- helpers ---
def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("£", "").replace("%", "")
    if s == "" or s.lower() in ("nan", "none", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(s):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:19] if "T" in s else s, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "")).date()
    except ValueError:
        return None


def _adviser(v):
    v = (v or "").strip()
    if "@" in v:  # email-style value -> display name (same as main dashboard)
        local = v.split("@", 1)[0]
        parts = local.replace(".", " ").replace("-", " ").replace("_", " ").split()
        return " ".join(p.capitalize() for p in parts if p) or v
    return v


def _tranche(v):
    """Return (sort_key, label) or None for blank. '3', '3.0' -> 3."""
    v = (v or "").strip()
    if not v:
        return None
    n = _num(v)
    if n is not None and float(n).is_integer():
        return (0, int(n), str(int(n)))
    if n is not None:
        return (0, n, v)
    return (1, 0, v)  # non-numeric labels sort after numbers


def _payout(v):
    """'bullet' / 'quarterly' / '' from the Payout Type label."""
    t = _norm(v)
    if "bullet" in t:
        return "bullet"
    if "quarterly" in t:
        return "quarterly"
    return ""


def classify(name):
    n = (name or "").lower()
    if "takeover" in n:
        return "takeover"
    if "rollover" in n or "extension" in n:
        return "rollover"
    return "new_money"


def _truthy(v):
    return (v or "").strip().lower() == "true"


def _r2(x):
    return round(x + 0.0, 2)


# ------------------------------------------------------------- matching ---
def project_matcher(cfg):
    """cfg: {"investment_projects": [...]} exact names, or
            {"investment_project_contains": "SBL Capital"}."""
    contains = _norm(cfg.get("investment_project_contains"))
    exact = {_norm(x) for x in (cfg.get("investment_projects") or []) if _norm(x)}
    if contains:
        return lambda p: contains in _norm(p)
    return lambda p: _norm(p) in exact


def find_company(companies, sub_project):
    want = _norm(sub_project)
    hits = [c for c in companies if _norm(c.get("Sub Projects (String)")) == want]
    if not hits:
        return None, 0
    # Prefer a company that actually has a requirement set.
    hits.sort(key=lambda c: -((_num(c.get("Raising Requirements")) or 0)
                              + (_num(c.get("Monthly Raising Requirement")) or 0)))
    return hits[0], len(hits)


# -------------------------------------------------------------- compute ---
def compute_project(rows, companies, now, cfg, include_rows=True):
    """Build the full data block for ONE configured project.

    include_rows=False leaves every individual investment (name, record id,
    adviser, source) OUT of the output, so the page can only show totals.
    The main dashboard uses this; the standalone page keeps the rows."""
    as_at = now.date() if hasattr(now, "date") else now
    match = project_matcher(cfg)
    sub_project = (cfg.get("sub_project") or "").strip()
    company, n_company_hits = find_company(companies, sub_project)
    req_total = (_num(company.get("Raising Requirements")) or 0.0) if company else 0.0
    req_month = (_num(company.get("Monthly Raising Requirement")) or 0.0) if company else 0.0

    inv = []
    matched_projects = defaultdict(int)
    for r in rows:
        proj = (r.get("Investment Project") or "").strip()
        if not proj or not match(proj):
            continue
        stage_label = _norm(r.get("Investment pipeline stage"))
        if stage_label in _NTU:
            continue
        matched_projects[proj] += 1
        sd = _date(r.get("Start Date"))
        rid = (r.get("Record ID") or "").strip()
        tr = _tranche(r.get("Tranche Number"))
        inv.append({
            "id": rid,
            "name": (r.get("Name") or "").strip(),
            "project": proj,
            "amount": _num(r.get("Investment")) or 0.0,
            "adviser": _adviser(r.get("Servicing Adviser")),
            "source": (r.get("Source Investment Project") or "").strip(),
            "stage": _STAGE_KEY.get(stage_label),
            "stage_label": (r.get("Investment pipeline stage") or "").strip(),
            "start": sd,
            "flag": _truthy(r.get("Exclude from this Month's Raising Req")),
            "tranche": tr,
            "kind": classify(r.get("Name")),
            "payout": _payout(r.get("Payout Type")),
        })

    def in_month(i):
        return (i["start"] is not None and i["start"] <= as_at
                and i["start"].year == as_at.year and i["start"].month == as_at.month)

    def started(i):
        return i["start"] is not None and i["start"] <= as_at

    def summ(items):
        return _r2(sum(i["amount"] for i in items)), len(items)

    # ---------------- headline: total view ----------------
    head_pool = [i for i in inv if i["kind"] != "takeover"]
    st = [i for i in head_pool if started(i)]
    mr = [i for i in head_pool if i["stage"] == "money_received"]
    st_total, st_count = summ(st)
    nm_total, nm_count = summ([i for i in st if i["kind"] == "new_money"])
    ro_total, ro_count = summ([i for i in st if i["kind"] == "rollover"])
    mr_total, mr_count = summ(mr)
    total_view = {
        "requirement": _r2(req_total),
        "started_total": st_total, "started_count": st_count,
        "new_money_total": nm_total, "new_money_count": nm_count,
        "rollover_total": ro_total, "rollover_count": ro_count,
        "money_received_total": mr_total, "money_received_count": mr_count,
        # v1.2.0: payout split of the same investments the hero counts.
        "bullet_total": summ([i for i in st if i["payout"] == "bullet"])[0],
        "quarterly_total": summ([i for i in st if i["payout"] == "quarterly"])[0],
        "left_to_raise": _r2(req_total - st_total),
        "pct": (st_total / req_total) if req_total > 0 else None,
    }

    # ---------------- headline: monthly view ----------------
    m_st = [i for i in head_pool if in_month(i) and not i["flag"]]
    m_mr = [i for i in mr if not i["flag"]]
    m_total, m_count = summ(m_st)
    m_nm_total, m_nm_count = summ([i for i in m_st if i["kind"] == "new_money"])
    m_ro_total, m_ro_count = summ([i for i in m_st if i["kind"] == "rollover"])
    m_mr_total, m_mr_count = summ(m_mr)
    monthly_view = {
        "requirement": _r2(req_month),
        "month_label": as_at.strftime("%B %Y"),
        "started_total": m_total, "started_count": m_count,
        "new_money_total": m_nm_total, "new_money_count": m_nm_count,
        "rollover_total": m_ro_total, "rollover_count": m_ro_count,
        "money_received_total": m_mr_total, "money_received_count": m_mr_count,
        # v1.2.0: monthly hero counts started this month + money received.
        "bullet_total": summ([i for i in m_st + m_mr if i["payout"] == "bullet"])[0],
        "quarterly_total": summ([i for i in m_st + m_mr if i["payout"] == "quarterly"])[0],
        "left_to_raise": _r2(req_month - m_total - m_mr_total),
        "pct": ((m_total + m_mr_total) / req_month) if req_month > 0 else None,
    }

    # ---------------- current tranche ----------------
    mr_all = [i for i in inv if i["stage"] == "money_received" and i["tranche"]]
    current_tranche = None
    if mr_all:
        low = min(i["tranche"] for i in mr_all)
        in_tr = [i for i in mr if i["tranche"] == low]  # headline: no takeovers
        t_total, t_count = summ(in_tr)
        current_tranche = {"tranche": low[2], "total": t_total, "count": t_count}
    mr_no_tranche = len([i for i in inv if i["stage"] == "money_received" and not i["tranche"]])

    # ---------------- pipeline stages (takeovers INCLUDED) ----------------
    def row_out(i):
        return {
            "id": i["id"], "name": i["name"], "amount": _r2(i["amount"]),
            "adviser": i["adviser"], "source": i["source"],
            "start": i["start"].isoformat() if i["start"] else "",
            "tranche": i["tranche"][2] if i["tranche"] else "",
            "kind": i["kind"],
            # Shown in the Monthly view's Project Live list?
            "m": bool(i["stage"] == "project_live" and in_month(i) and not i["flag"]),
        }

    def groups_of(items):
        out = {}
        for k in ("new_money", "rollover", "takeover"):
            t, c = summ([i for i in items if i["kind"] == k])
            out[k] = {"total": t, "count": c}
        return out

    stages = []
    for key, label in LIST_STAGES:
        items = [i for i in inv if i["stage"] == key]
        items.sort(key=lambda i: (-i["amount"], i["name"].lower()))
        total, count = summ(items)
        st_out = {"key": key, "label": label, "total": total, "count": count,
                  "in_bar": key != "project_live",
                  "groups": groups_of(items),
                  "rows": [row_out(i) for i in items] if include_rows else []}
        if key == "project_live":
            mm = [i for i in items if in_month(i) and not i["flag"]]
            st_out["monthly_total"], st_out["monthly_count"] = summ(mm)
            st_out["monthly_groups"] = groups_of(mm)
        stages.append(st_out)

    # ---------------- pipeline bar total + payout split ----------------
    # Same investments as the bar (Pending, Forms Out, Written, Money
    # Received; takeovers included). B = Payout Type contains "bullet",
    # Q = contains "quarterly" (any capitals).
    bar_items = [i for i in inv if i["stage"] in {k for k, _ in BAR_STAGES}]
    pl_total, pl_count = summ(bar_items)
    b_total, b_count = summ([i for i in bar_items if i["payout"] == "bullet"])
    q_total, q_count = summ([i for i in bar_items if i["payout"] == "quarterly"])
    pipeline = {"total": pl_total, "count": pl_count,
                "bullet_total": b_total, "bullet_count": b_count,
                "quarterly_total": q_total, "quarterly_count": q_count}

    # ---------------- tranche table (takeovers INCLUDED) ----------------
    by_tr = defaultdict(lambda: defaultdict(list))
    for i in inv:
        if not started(i):
            continue
        by_tr[i["tranche"]][i["start"]].append(i)
    tranches = []
    for tr in sorted([t for t in by_tr if t is not None]) + ([None] if None in by_tr else []):
        dates = []
        for d in sorted(by_tr[tr]):
            t, c = summ(by_tr[tr][d])
            dates.append({"date": d.isoformat(), "total": t, "count": c})
        t_all = _r2(sum(x["total"] for x in dates))
        c_all = sum(x["count"] for x in dates)
        tranches.append({"tranche": tr[2] if tr else None, "total": t_all,
                         "count": c_all, "dates": dates})

    tk = [i for i in inv if started(i) and i["kind"] == "takeover"]
    tk_total, tk_count = summ(tk)

    warnings = []
    if not matched_projects:
        warnings.append("No investments matched the configured investment project(s).")
    if company is None:
        warnings.append("No company found with Sub Projects (String) = %r." % sub_project)
    elif n_company_hits > 1:
        warnings.append("%d companies share Sub Projects (String) = %r; using %r."
                        % (n_company_hits, sub_project, company.get("Company name")))
    if mr_no_tranche:
        warnings.append("%d Money Received investment(s) have no tranche number." % mr_no_tranche)

    return {
        "key": cfg.get("key") or _norm(cfg.get("label") or sub_project).replace(" ", "-"),
        "label": cfg.get("label") or sub_project,
        "sub_project": sub_project,
        "company_name": (company.get("Company name") if company else "") or "",
        "investment_projects": sorted(matched_projects),
        "investment_count": len(inv),
        "total": total_view,
        "monthly": monthly_view,
        "current_tranche": current_tranche,
        "pipeline": pipeline,
        "stages": stages,
        "tranches": tranches,
        "tranche_takeover_total": tk_total,
        "tranche_takeover_count": tk_count,
        "warnings": warnings,
    }


def compute(rows, companies, now, projects_cfg, include_rows=True):
    out = {
        "show_names": bool(include_rows),
        "core_version": CORE_VERSION,
        "as_at": (now.date() if hasattr(now, "date") else now).isoformat(),
        "record_url": RECORD_URL,
        "projects": [compute_project(rows, companies, now, p, include_rows) for p in projects_cfg],
    }
    return out


def auto_projects(companies, rules=None):
    """Main dashboard default when no explicit project list is configured:
    every Developer/Project company with a total Raising Requirement > 0,
    joined on Sub Projects (String) == Investment Project (the same join the
    existing Raising Progress tab uses). `rules` can override the match for a
    sub project, e.g. {"SBL Capital Limited": {"investment_project_contains": "SBL Capital"}}."""
    rules = {_norm(k): v for k, v in (rules or {}).items()}
    out = []
    for c in companies:
        if (c.get("Company Type") or "").strip() != "Developer/Project":
            continue
        if (_num(c.get("Raising Requirements")) or 0) <= 0:
            continue
        sub = (c.get("Sub Projects (String)") or "").strip()
        if not sub:
            continue
        cfg = {"label": (c.get("Company name") or sub).strip(), "sub_project": sub}
        cfg.update(rules.get(_norm(sub)) or {"investment_projects": [sub]})
        out.append(cfg)
    out.sort(key=lambda p: p["label"].lower())
    return out


def log_summary(data, write=print):
    for p in data["projects"]:
        t = p["total"]
        ct = p["current_tranche"]
        write("  [%s] %d investments | requirement £%.0f | started £%.0f (%d) | left £%.0f | MR £%.0f (%d) | tranche %s"
              % (p["label"], p["investment_count"], t["requirement"], t["started_total"],
                 t["started_count"], t["left_to_raise"], t["money_received_total"],
                 t["money_received_count"], ("%s £%.0f" % (ct["tranche"], ct["total"])) if ct else "none"))
        pl = p.get("pipeline") or {}
        write("    pipeline £%.0f (%d) | Bullet £%.0f (%d) | Quarterly £%.0f (%d) | other/blank payout %d"
              % (pl.get("total", 0), pl.get("count", 0), pl.get("bullet_total", 0), pl.get("bullet_count", 0),
                 pl.get("quarterly_total", 0), pl.get("quarterly_count", 0),
                 pl.get("count", 0) - pl.get("bullet_count", 0) - pl.get("quarterly_count", 0)))
        for w in p["warnings"]:
            write("    WARN: " + w)
