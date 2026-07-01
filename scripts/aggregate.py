import csv, json
from collections import defaultdict
from datetime import datetime

import os, sys
# CSV source: live HubSpot fetch by default if present, else the original manual export.
# Override with arg1 or the PIP_CSV env var.
_DEFAULT_LIVE=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","data","investments_live.csv")
_DEFAULT_EXPORT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","data","investment-export-sample.csv")
P=(sys.argv[1] if len(sys.argv)>1 else None) or os.environ.get("PIP_CSV") or (_DEFAULT_LIVE if os.path.exists(_DEFAULT_LIVE) else _DEFAULT_EXPORT)
print("Reading:", P)

# --- Collision-aware CSV read ---
# The export can contain TWO columns literally named "Developer":
#   (1) the original field (project/company-style names, e.g. "Zenzic Secure Lending") that all
#       the existing aggregations (e.g. the Top developers card) have always used; and
#   (2) a NEW project-dependent property (parent developer company, e.g. "Prosperity",
#       "Zenzic Capital") that the client added on 24 Jun 2026 for future breakdowns.
# Plain csv.DictReader would silently keep only the LAST duplicate (the new field), which would
# quietly change the existing Top developers card. To preserve current behaviour exactly we read
# rows positionally: the FIRST "Developer" keeps the key "Developer" (old field, unchanged), and
# the SECOND becomes "Developer (project)" (new field, stored for later, not yet rendered).
def _read_rows(path):
    rdr=csv.reader(open(path,encoding='utf-8-sig'))
    hdr=next(rdr)
    seen={}
    keys=[]
    for h in hdr:
        if h=="Developer":
            seen[h]=seen.get(h,0)+1
            keys.append("Developer" if seen[h]==1 else "Developer (project)")
        else:
            keys.append(h)
    out=[]
    for r in rdr:
        d={}
        for i,k in enumerate(keys):
            d[k]=r[i] if i<len(r) else ""
        out.append(d)
    return out, keys
rows, _HEADER_KEYS = _read_rows(P)
HAS_DEV_PROJECT = "Developer (project)" in _HEADER_KEYS
DEV_PROJ_FIELD="Developer (project)"
# NOW drives the WTD/MTD/YTD windows, the maturity horizon and generated_at.
# The refresh orchestrator sets PIP_NOW (ISO) to the real run time; if absent we use now().
def _pip_now():
    v=os.environ.get("PIP_NOW")
    if v:
        try: return datetime.fromisoformat(v)
        except Exception: pass
    return datetime.now()
NOW=_pip_now()

def num(s):
    if s is None: return None
    s=str(s).strip().replace(",","").replace("£","").replace("%","")
    if s=="" or s.lower() in("nan","none","null"): return None
    try: return float(s)
    except: return None

def parse_date(s):
    s=(s or "").strip()
    if not s: return None
    for fmt in ("%Y-%m-%d","%d/%m/%Y","%m/%d/%Y","%Y-%m-%dT%H:%M:%S","%d-%m-%Y","%Y/%m/%d"):
        try: return datetime.strptime(s[:19] if "T" in s else s, fmt)
        except: pass
    try: return datetime.fromisoformat(s.replace("Z",""))
    except: return None

def email_to_name(s):
    # Convert an email-style adviser value into a display name, e.g.
    # 'kelvin-redwood@pip.net' -> 'Kelvin Redwood'
    local=s.split('@',1)[0]
    parts=local.replace('.',' ').replace('-',' ').replace('_',' ').split()
    return ' '.join(p.capitalize() for p in parts if p) or s

# adviser fields that may contain emails instead of names
_ADVISER_FIELDS={"Servicing Adviser","Selling Adviser"}

def g(r,f):
    v=(r.get(f,"") or "").strip()
    if f in _ADVISER_FIELDS and "@" in v:
        return email_to_name(v)
    return v

# ---- Capital-raised cleaning rules (per client guidance) ----
# Stages where NO capital has actually been received yet, or that never proceeded.
# These must be EXCLUDED from any "capital raised" figure.
NON_RECEIVED_STAGES={
    "pending","forms out","written","written (processed form)",
    "ntu","form sent","form received",
}
def stage_of(r):
    return (r.get("Investment pipeline stage") or "").strip().lower()
def is_received(r):
    # capital has actually been received (stage progressed past the paperwork stages)
    return stage_of(r) not in NON_RECEIVED_STAGES
def is_rollover(r):
    # A rollover recycles existing capital at maturity rather than raising new money.
    # Best signal: the investment name contains "rollover" (the client confirmed this,
    # corroborated by the 'Successor'/'Original' association labels still being cleaned up).
    return "rollover" in (r.get("Name","") or "").lower()
def is_net_new(r):
    # Genuinely new external capital: received AND not a recycled rollover.
    return is_received(r) and not is_rollover(r)

def agg(records, field, valfield="Investment", blank_label="(blank)"):
    d=defaultdict(lambda:[0,0.0])
    for r in records:
        k=g(r,field) or blank_label
        d[k][0]+=1; d[k][1]+= num(r.get(valfield)) or 0
    return [{"key":k,"count":v[0],"sum":round(v[1],2)} for k,v in sorted(d.items(),key=lambda x:-x[1][1])]

# ---- Sets ----
live=[r for r in rows if g(r,"Live Investment Status").lower()=="true"]
total_book=sum(num(r.get("Investment")) or 0 for r in rows)
live_aum=sum(num(r.get("Live Investment Amount")) or 0 for r in live)
live_full_val=sum(num(r.get("Full Valuation")) or 0 for r in live)
# Live accrued-interest box uses the "Total Accumulated Interest" column (client change 25 Jun 2026).
live_acc_int=sum(num(r.get("Total Accumulated Interest")) or 0 for r in live)
# Whole-book accrued-interest figure stays on the "Accumulated Interest" column.
total_acc_int=sum(num(r.get("Accumulated Interest")) or 0 for r in rows)

rates_live=[(num(r.get("Interest Rate")) or 0)*100 for r in live if num(r.get("Interest Rate")) is not None]
avg_rate_live=sum(rates_live)/len(rates_live) if rates_live else 0
rates_all=[(num(r.get("Interest Rate")) or 0)*100 for r in rows if num(r.get("Interest Rate")) is not None]
avg_rate_all=sum(rates_all)/len(rates_all) if rates_all else 0

# weighted avg rate on live (by live amount)
wnum=wden=0
for r in live:
    rt=num(r.get("Interest Rate")); amt=num(r.get("Live Investment Amount")) or 0
    if rt is not None: wnum+= rt*100*amt; wden+=amt
w_avg_rate_live = wnum/wden if wden else 0

# unique counts
def uniq(records, field):
    return len(set(g(r,field) for r in records if g(r,field)))

# income vs growth (live)
def payout_class(pt):
    pt=pt.lower()
    if pt=="bullet": return "Growth (Bullet)"
    if pt in ("quarterly","biannual"): return "Income ("+pt.capitalize()+")"
    return "Unspecified"
ig=defaultdict(lambda:[0,0.0])
for r in live:
    cls="Growth" if g(r,"Payout Type").lower()=="bullet" else ("Income" if g(r,"Payout Type").lower() in("quarterly","biannual") else "Unspecified")
    ig[cls][0]+=1; ig[cls][1]+= num(r.get("Live Investment Amount")) or 0
income_growth=[{"key":k,"count":v[0],"sum":round(v[1],2)} for k,v in sorted(ig.items(),key=lambda x:-x[1][1])]

# ---- MATURITY profile (live) ----
def maturity_date(r):
    return parse_date(r.get("End Date")) or parse_date(r.get("Estimated End Date"))
# by year
mat_y=defaultdict(lambda:[0,0.0]); no_mat=[0,0.0]
for r in live:
    dt=maturity_date(r); amt=num(r.get("Live Investment Amount")) or 0
    if dt: mat_y[dt.year][0]+=1; mat_y[dt.year][1]+=amt
    else: no_mat[0]+=1; no_mat[1]+=amt
maturity_by_year=[{"year":y,"count":mat_y[y][0],"sum":round(mat_y[y][1],2)} for y in sorted(mat_y)]
# monthly, future only (next 24 months)
mat_m=defaultdict(lambda:[0,0.0])
for r in live:
    dt=maturity_date(r)
    if dt and dt>=datetime(NOW.year,NOW.month,1):
        key=f"{dt.year}-{dt.month:02d}"
        mat_m[key][0]+=1; mat_m[key][1]+= num(r.get("Live Investment Amount")) or 0
maturity_by_month=[{"month":k,"count":mat_m[k][0],"sum":round(mat_m[k][1],2)} for k in sorted(mat_m)][:24]
# monthly maturity broken down by project (merged phased names) for the overview filter
import re as _re_m
_PHASE_M=_re_m.compile(r"\s*\(\d+\)\s*$")
def _base_name_m(p): return _PHASE_M.sub("", p).strip() or p
_mat_months=[d["month"] for d in maturity_by_month]            # the (<=24) months shown
_mat_idx={m:i for i,m in enumerate(_mat_months)}
_matp=defaultdict(lambda:[0.0]*len(_mat_months))               # project -> [sum per month]
_matp_tot=defaultdict(float)
for r in live:
    dt=maturity_date(r)
    if not dt: continue
    key=f"{dt.year}-{dt.month:02d}"
    if key not in _mat_idx: continue
    proj=_base_name_m((g(r,"Investment Project") or "(blank)"))
    amt=num(r.get("Live Investment Amount")) or 0
    _matp[proj][_mat_idx[key]]+=amt
    _matp_tot[proj]+=amt
_matp_order=sorted(_matp.keys(),key=lambda p:-_matp_tot[p])
maturity_by_month_projects={
    "months":[mb["month"] for mb in maturity_by_month],
    "projects":[{"name":p,"total":round(_matp_tot[p],2),"series":[round(v,2) for v in _matp[p]]} for p in _matp_order],
}
# monthly maturity broken down by parent DEVELOPER (project-dependent Developer property).
# Built from the same live records, summing each row's Live Investment Amount into its
# Developer (project) value at the row's maturity month. Mirrors the project rollup so the
# developer-mode stack reconciles to the exact same monthly totals.
maturity_by_month_developers={"months":[mb["month"] for mb in maturity_by_month],"developers":[]}
if HAS_DEV_PROJECT:
    _matd=defaultdict(lambda:[0.0]*len(_mat_months))          # developer -> [sum per month]
    _matd_tot=defaultdict(float)
    for r in live:
        dt=maturity_date(r)
        if not dt: continue
        key=f"{dt.year}-{dt.month:02d}"
        if key not in _mat_idx: continue
        dev=(r.get(DEV_PROJ_FIELD,"") or "").strip() or "(no developer)"
        amt=num(r.get("Live Investment Amount")) or 0
        _matd[dev][_mat_idx[key]]+=amt
        _matd_tot[dev]+=amt
    _matd_order=sorted(_matd.keys(),key=lambda d:-_matd_tot[d])
    maturity_by_month_developers["developers"]=[
        {"name":d,"total":round(_matd_tot[d],2),"series":[round(v,2) for v in _matd[d]]} for d in _matd_order]

# ---- Capital-raised cleaning: headline figures ----
net_new=[r for r in rows if is_net_new(r)]            # genuinely new external capital
received=[r for r in rows if is_received(r)]          # all received (incl. rollovers)
non_received=[r for r in rows if not is_received(r)]  # paperwork stages + NTU (no capital in)
rollover_received=[r for r in received if is_rollover(r)]  # recycled at maturity

net_new_capital=sum(num(r.get("Investment")) or 0 for r in net_new)
gross_received_capital=sum(num(r.get("Investment")) or 0 for r in received)
rollover_recycled_capital=sum(num(r.get("Investment")) or 0 for r in rollover_received)
non_received_capital=sum(num(r.get("Investment")) or 0 for r in non_received)

# ---- Net NEW capital raised by year (the honest growth metric) ----
# Excludes rollovers (recycled capital) and non-received stages.
# Date = Money Received On, fallback Start Date.
yr=defaultdict(lambda:[0,0.0])
for r in net_new:
    dt=parse_date(r.get("Money Received On")) or parse_date(r.get("Start Date"))
    if dt: yr[dt.year][0]+=1; yr[dt.year][1]+= num(r.get("Investment")) or 0
# ---- Rollover (recycled) capital by year, same date basis & is_rollover rule ----
# Lets the Executive year chart stack rollover on top of net new. Uses the identical
# is_rollover() identification as the Adviser Stats league.
yrr=defaultdict(lambda:[0,0.0])
for r in rollover_received:
    dt=parse_date(r.get("Money Received On")) or parse_date(r.get("Start Date"))
    if dt: yrr[dt.year][0]+=1; yrr[dt.year][1]+= num(r.get("Investment")) or 0
by_year=[{"year":y,"count":yr[y][0],"sum":round(yr[y][1],2),
          "rollover":round(yrr[y][1],2),"rollover_count":yrr[y][0]} for y in sorted(yr)]

# ---- For reference: gross throughput by year (incl. rollovers) ----
yrg=defaultdict(lambda:[0,0.0])
for r in received:
    dt=parse_date(r.get("Money Received On")) or parse_date(r.get("Start Date"))
    if dt: yrg[dt.year][0]+=1; yrg[dt.year][1]+= num(r.get("Investment")) or 0
by_year_gross=[{"year":y,"count":yrg[y][0],"sum":round(yrg[y][1],2)} for y in sorted(yrg)]

# ---- Capital invested in each PROJECT over time (monthly stock series) ----
# An investment's capital is "in" its project from Start Date until End Date.
# No End Date => still live => active through the present (and any future start is
# counted from its start month onward). Fallback to Estimated End Date when an
# investment has ended but no hard End Date. We include all RECEIVED capital here
# (incl. rollovers) because the question is "how much money is parked in the project
# at a point in time", not "new capital raised".
from datetime import date
def _ym(d):  # absolute month index (year*12 + month-1)
    return d.year*12 + (d.month-1)
def _ym_label(i):  # absolute month index -> 'YYYY-MM'
    return f"{i//12}-{i%12+1:02d}"
HORIZON=datetime(NOW.year, NOW.month, 1)
proj_received=[r for r in rows if is_received(r) and parse_date(r.get("Start Date"))]
# timeline bounds
start_idx=min(_ym(parse_date(r.get("Start Date"))) for r in proj_received)
end_idx=_ym(HORIZON)  # up to current month
months=[_ym_label(i) for i in range(start_idx, end_idx+1)]
# per project: array aligned to months
proj_series=defaultdict(lambda:[0.0]*len(months))
for r in proj_received:
    proj=g(r,"Investment Project") or "(blank)"
    amt=num(r.get("Investment")) or 0
    if amt<=0: continue
    s=parse_date(r.get("Start Date"))
    e=parse_date(r.get("End Date")) or parse_date(r.get("Estimated End Date"))
    si=_ym(s)
    # active end month index: if no end date and live -> runs through horizon;
    # if end date exists -> active up to (and including) the month before it matures.
    is_live = g(r,"Live Investment Status").lower()=="true"
    if e:
        ei=_ym(e)-1  # capital leaves the month it matures
        if is_live and ei<end_idx:  # live but stale end date: keep through horizon
            ei=max(ei, end_idx)
    else:
        ei=end_idx if is_live else _ym(s)  # no end & not live: single month presence
    lo=max(si, start_idx); hi=min(ei, end_idx)
    for i in range(lo, hi+1):
        proj_series[proj][i-start_idx]+=amt
# total live capital per project (for ranking / colour priority)
proj_totals=defaultdict(float)
for r in rows:
    if g(r,"Live Investment Status").lower()=="true":
        proj_totals[g(r,"Investment Project") or "(blank)"]+= num(r.get("Live Investment Amount")) or 0
# latest maturity date per project (date the final investment(s) of the project matured).
# Used to label/sort ended (no-live-capital) projects. Uses End Date, falling back to
# Estimated End Date, across that project's received investments; keep the max (latest).
proj_end_date={}
for r in proj_received:
    proj=g(r,"Investment Project") or "(blank)"
    e=parse_date(r.get("End Date")) or parse_date(r.get("Estimated End Date"))
    if not e: continue
    if proj not in proj_end_date or e>proj_end_date[proj]:
        proj_end_date[proj]=e

# ---- Merge phased projects: same name but a trailing "(N)" suffix ----
# e.g. "LiveMore (1)", "LiveMore (2)", "LiveMore (3)" -> one "LiveMore" line.
# Names with no trailing (N) (incl. distinct SBL Capital - X locations) are left as-is.
import re as _re
_PHASE=_re.compile(r"\s*\(\d+\)\s*$")
def _base_name(p):
    return _PHASE.sub("", p).strip() or p
merged_series=defaultdict(lambda:[0.0]*len(months))
merged_totals=defaultdict(float)
merged_end_date={}
for p,arr in proj_series.items():
    b=_base_name(p)
    for i,v in enumerate(arr):
        merged_series[b][i]+=v
for p,t in proj_totals.items():
    merged_totals[_base_name(p)]+=t
for p,e in proj_end_date.items():
    b=_base_name(p)
    if b not in merged_end_date or e>merged_end_date[b]:
        merged_end_date[b]=e
proj_series=merged_series
proj_totals=merged_totals
proj_end_date=merged_end_date
proj_order=sorted(proj_series.keys(), key=lambda p:-proj_totals.get(p,0))
# downsample to quarterly points to keep payload small but smooth
q_idx=[i for i,mm in enumerate(months) if int(mm[5:7]) in (1,4,7,10)]
if (len(months)-1) not in q_idx: q_idx.append(len(months)-1)
project_timeline={
  "months":[months[i] for i in q_idx],
  "projects":[{"key":p,
               "total_live":round(proj_totals.get(p,0),2),
               "has_live":round(proj_totals.get(p,0),2)>0,
               "end_date":(proj_end_date[p].isoformat() if p in proj_end_date else None),
               "series":[round(proj_series[p][i],2) for i in q_idx]} for p in proj_order],
}

# ---- Rate distribution (whole book by Investment) ----
rb=defaultdict(lambda:[0,0.0])
for r in rows:
    rt=num(r.get("Interest Rate"))
    if rt is None: continue
    lo=int(rt*100)
    rb[lo][0]+=1; rb[lo][1]+= num(r.get("Investment")) or 0
rate_dist=[{"bucket":f"{lo}\u2013{lo+1}%","count":rb[lo][0],"sum":round(rb[lo][1],2)} for lo in sorted(rb)]

# ---- Project term (live, by live amount) ----
def term_agg(records, valfield):
    d=defaultdict(lambda:[0,0.0])
    for r in records:
        t=num(r.get("Project Term"))
        if t is None: continue
        d[int(t)][0]+=1; d[int(t)][1]+= num(r.get(valfield)) or 0
    return [{"term":t,"count":d[t][0],"sum":round(d[t][1],2)} for t in sorted(d)]

# ---- Adviser league table: capital that WENT LIVE each period ----
# "Went live" = a received investment (capital actually arrived) with a Start Date in the period.
# We split each adviser's capital into NEW MONEY vs ROLLOVER (recycled at maturity).
# NOTE: rollover investments can later be topped up with new money; the current export doesn't
# separate the top-up portion, so a rollover row is counted wholly as rollover for now.
def _q_of(d):  # 'YYYY-Qn'
    return f"{d.year}-Q{(d.month-1)//3+1}"
league_received=[r for r in rows if is_received(r) and parse_date(r.get("Start Date"))]
CUR_YEAR=NOW.year
def build_league(adviser_field):
    # period_key -> adviser -> [new_sum, new_cnt, roll_sum, roll_cnt]
    per=defaultdict(lambda:defaultdict(lambda:[0.0,0,0.0,0]))
    def add(pk, adv, amt, roll):
        cell=per[pk][adv]
        if roll: cell[2]+=amt; cell[3]+=1
        else:    cell[0]+=amt; cell[1]+=1
    for r in league_received:
        d=parse_date(r.get("Start Date"))
        amt=num(r.get("Investment")) or 0
        if amt<=0: continue
        adv=g(r,adviser_field) or "(unassigned)"
        roll=is_rollover(r)
        q=_q_of(d); y=str(d.year)
        add(q, adv, amt, roll)        # quarter bucket
        add(y, adv, amt, roll)        # full-year bucket
        add("ALL", adv, amt, roll)    # all-time bucket (since the start of PIP)
        if d.year==CUR_YEAR:
            add(f"{CUR_YEAR}-YTD", adv, amt, roll)  # year-to-date bucket
    # assemble each period: ranked advisers + period summary
    out_periods={}
    for pk,advs in per.items():
        rank=[]
        for adv,(ns,nc,rs,rc) in advs.items():
            rank.append({"adviser":adv,"new_money":round(ns,2),"new_count":nc,
                         "rollover":round(rs,2),"rollover_count":rc,
                         "total":round(ns+rs,2),"count":nc+rc})
        rank.sort(key=lambda x:-x["total"])
        tot_new=round(sum(a["new_money"] for a in rank),2)
        tot_roll=round(sum(a["rollover"] for a in rank),2)
        tot=round(tot_new+tot_roll,2)
        out_periods[pk]={
            "advisers":rank,
            "total":tot,"total_new":tot_new,"total_rollover":tot_roll,
            "count":sum(a["count"] for a in rank),
            "new_pct":round(100*tot_new/tot,1) if tot else 0,
            "rollover_pct":round(100*tot_roll/tot,1) if tot else 0,
        }
    return out_periods
# ordered period menu: quarters (newest first), then years (newest first), then YTD
_qkeys=sorted({_q_of(parse_date(r.get("Start Date"))) for r in league_received}, reverse=True)
_ykeys=sorted({str(parse_date(r.get("Start Date")).year) for r in league_received}, reverse=True)
period_menu=(
    [{"key":"ALL","label":"All time (since 2017)","type":"all"}]
    + [{"key":f"{CUR_YEAR}-YTD","label":f"{CUR_YEAR} (year to date)","type":"ytd"}]
    + [{"key":q,"label":q.replace("-Q"," Q"),"type":"quarter"} for q in _qkeys]
    + [{"key":y,"label":y,"type":"year"} for y in _ykeys]
)
adviser_league={
    "period_menu":period_menu,
    "servicing":build_league("Servicing Adviser"),
    "selling":build_league("Selling Adviser"),
    "default_period":_qkeys[0] if _qkeys else f"{CUR_YEAR}-YTD",
}

# ---- NEW project-dependent Developer property (stored, not yet rendered) ----
# The client added a "Developer" property in HubSpot that depends on Investment Project and
# names the parent developer company (e.g. Smithfield Lofts -> Prosperity). The export now
# carries TWO "Developer" columns; our collision-aware reader exposes the new one as the key
# "Developer (project)" (the OLD "Developer" field is untouched so existing cards don't change).
# We pre-compute the project->developer map and per-developer capital so the breakdowns the
# client wants later are a small UI change away — but nothing here is wired into the dashboard yet.
def _devp(r):
    return (r.get(DEV_PROJ_FIELD,"") or "").strip()
dev_project_map={}          # Investment Project -> developer (first non-blank wins)
dev_cap=defaultdict(lambda:{"net_new":0.0,"gross":0.0,"live":0.0,"count":0})
if HAS_DEV_PROJECT:
    for r in rows:
        proj=g(r,"Investment Project")
        dev=_devp(r)
        if proj and dev and proj not in dev_project_map:
            dev_project_map[proj]=dev
    for r in rows:
        dev=_devp(r) or "(blank)"
        cell=dev_cap[dev]; cell["count"]+=1
        if is_net_new(r): cell["net_new"]+= num(r.get("Investment")) or 0
        if is_received(r): cell["gross"]+= num(r.get("Investment")) or 0
        if g(r,"Live Investment Status").lower()=="true": cell["live"]+= num(r.get("Live Investment Amount")) or 0
dev_project_capital=sorted(
    [{"developer":k,"net_new":round(v["net_new"],2),"gross":round(v["gross"],2),
      "live":round(v["live"],2),"count":v["count"]} for k,v in dev_cap.items()],
    key=lambda x:-x["live"])
developer_project_data={
    "available": HAS_DEV_PROJECT,
    "note": "Project-dependent Developer property added 24 Jun 2026. Now powers the maturity-by-month developer filter; also retained for future breakdowns.",
    "distinct_developers": len(dev_cap),
    "project_to_developer": dev_project_map,
    "capital_by_developer": dev_project_capital,
}

out={
 "generated_at": NOW.isoformat(),
 "currency":"GBP",
 "totals":{
   "total_records": len(rows),
   "total_book": round(total_book,2),
   "net_new_capital": round(net_new_capital,2),
   "net_new_count": len(net_new),
   "gross_received_capital": round(gross_received_capital,2),
   "gross_received_count": len(received),
   "rollover_recycled_capital": round(rollover_recycled_capital,2),
   "rollover_recycled_count": len(rollover_received),
   "non_received_capital": round(non_received_capital,2),
   "non_received_count": len(non_received),
   "live_count": len(live),
   "live_aum": round(live_aum,2),
   "live_full_valuation": round(live_full_val,2),
   "live_accumulated_interest": round(live_acc_int,2),
   "total_accumulated_interest": round(total_acc_int,2),
   "avg_rate_live": round(avg_rate_live,2),
   "avg_rate_all": round(avg_rate_all,2),
   "weighted_avg_rate_live": round(w_avg_rate_live,2),
   "unique_contacts": uniq(rows,"Associated Contact"),
   "unique_companies": uniq(rows,"Client Company"),
   "unique_projects": uniq(rows,"Investment Project"),
   "unique_advisers": uniq(rows,"Servicing Adviser"),
   "live_avg_investment": round(live_aum/len(live),2) if live else 0,
   "max_investment": round(max((num(r.get("Investment")) or 0) for r in rows),2),
 },
 "live":{
   "income_growth": income_growth,
   "by_payout": agg(live,"Payout Type","Live Investment Amount"),
   "by_advice": agg(live,"Advice Type","Live Investment Amount"),
   "by_project": agg(live,"Investment Project","Live Investment Amount"),
   "by_servicing_adviser": agg(live,"Servicing Adviser","Live Investment Amount"),
   "by_term": term_agg(live,"Live Investment Amount"),
   "maturity_by_year": maturity_by_year,
   "maturity_by_month": maturity_by_month,
   "maturity_by_month_projects": maturity_by_month_projects,
   "maturity_by_month_developers": maturity_by_month_developers,
   "maturity_no_date": {"count":no_mat[0],"sum":round(no_mat[1],2)},
 },
 "book":{
   "by_pipeline_stage": agg(rows,"Investment pipeline stage"),
   "by_pipeline": agg(rows,"Investment pipeline"),
   "by_advice": agg(rows,"Advice Type"),
   "by_payout": agg(rows,"Payout Type"),
   "by_year": by_year,
   "by_year_gross": by_year_gross,
   "rate_distribution": rate_dist,
   "by_term": term_agg(rows,"Investment"),
   "project_timeline": project_timeline,
   "top_projects": agg(rows,"Investment Project")[:15],
   "top_servicing_advisers": agg(rows,"Servicing Adviser")[:15],
   "top_selling_advisers": agg(rows,"Selling Adviser")[:15],
   "by_developer": agg(rows,"Developer")[:15],
   "adviser_league": adviser_league,
   # NEW (24 Jun 2026): the project-dependent "Developer" property the client added.
   # Stored for FUTURE developer breakdowns; intentionally NOT rendered anywhere yet.
   # `dev_project_map` = Investment Project -> parent developer company.
   # `dev_project_capital` = parent developer -> net-new / gross / live capital (for later use).
   "developer_project": developer_project_data,
 }
}

json.dump(out, open(os.environ.get("PIP_JSON") or os.path.join(os.path.dirname(os.path.abspath(__file__)),"dashboard_data_v2.json"),"w"), indent=2)
print("WROTE dashboard_data_v2.json")
print("Live AUM:",out["totals"]["live_aum"],"| Total book:",out["totals"]["total_book"])
print("Net NEW capital: £%.2fM (%d)"%(net_new_capital/1e6,len(net_new)))
print("Gross received:  £%.2fM (%d) | rollover recycled: £%.2fM (%d) | non-received: £%.2fM (%d)"%(
    gross_received_capital/1e6,len(received),rollover_recycled_capital/1e6,len(rollover_received),
    non_received_capital/1e6,len(non_received)))
print("Net-new by year:",[(b["year"],round(b["sum"]/1e6,1)) for b in by_year])
print("Project timeline: %d projects x %d quarterly points (%s -> %s)"%(
    len(project_timeline['projects']),len(project_timeline['months']),
    project_timeline['months'][0],project_timeline['months'][-1]))
_last={p['key']:p['series'][-1] for p in project_timeline['projects']}
print("  latest-point total across projects: £%.1fM"%(sum(_last.values())/1e6))
print("  top 5 now:",[(p['key'],round(p['series'][-1]/1e6,1)) for p in project_timeline['projects'][:5]])
print("Maturity years:",[(m["year"],round(m["sum"]/1e6,1)) for m in maturity_by_year])
print("Income/Growth:",income_growth)
print("Weighted avg rate live:",out["totals"]["weighted_avg_rate_live"])
print("Months in maturity schedule:",len(maturity_by_month))
_al=adviser_league
print("Adviser league periods:",len(_al['period_menu']),"| default:",_al['default_period'])
_dp=_al['servicing'][_al['default_period']]
print("  %s servicing: \u00a3%.1fM live (%.0f%% new / %.0f%% rollover), %d advisers"%(
    _al['default_period'],_dp['total']/1e6,_dp['new_pct'],_dp['rollover_pct'],len(_dp['advisers'])))
print("JSON size:",len(json.dumps(out)))
