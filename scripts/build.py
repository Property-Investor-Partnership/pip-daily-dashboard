#!/usr/bin/env python3
"""
PIP Investments Dashboard — build step for the GitHub Pages site.

Reads a HubSpot CSV export, crunches it with aggregate.py + supplement.py, and writes the
refreshed dashboard into ../docs/index.html (the folder GitHub Pages serves).

Usage:
    python3 build.py                       # uses the newest CSV in ../data
    python3 build.py /path/to/export.csv   # use a specific CSV
    python3 build.py --date 2026-06-29     # pin the "as at" date (optional)

No internet required for the build itself. Standard-library Python 3 only.
"""
import os
import re
import sys
import json
import glob
import subprocess
from datetime import datetime
try:
    from zoneinfo import ZoneInfo   # Python 3.9+
    UK_TZ = ZoneInfo("Europe/London")
except Exception:
    UK_TZ = None   # fall back to naive local time if zoneinfo unavailable


def _now_uk():
    """Return current UK local time (Europe/London — handles BST/GMT).

    On the GitHub Actions runner the system clock is UTC, so a naive
    datetime.now() reads an hour behind British Summer Time. Using ZoneInfo
    gives us the correct wall-clock time year-round.
    """
    if UK_TZ is not None:
        return datetime.now(UK_TZ)
    return datetime.now()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
SITE_HTML = os.path.join(ROOT, "docs", "index.html")
JSON_PATH = os.path.join(HERE, "dashboard_data_v2.json")


def fail(msg):
    print("\n[ERROR] " + msg)
    print("Nothing was changed.\n")
    sys.exit(1)


def find_csv(args):
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a == "--date":
            skip_next = True
            continue
        if a.startswith("--"):
            continue
        if os.path.exists(a):
            return os.path.abspath(a)
        fail("File not found: " + a)
    csvs = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    if not csvs:
        fail("No CSV found in " + DATA_DIR + ". Add a HubSpot export and re-run.")
    csvs.sort(key=os.path.getmtime, reverse=True)
    return csvs[0]


def parse_now(args):
    for i, a in enumerate(args):
        if a == "--date" and i + 1 < len(args):
            try:
                d = datetime.strptime(args[i + 1], "%Y-%m-%d")
                n = _now_uk()
                return d.replace(hour=n.hour, minute=n.minute, second=n.second)
            except ValueError:
                fail("--date must be YYYY-MM-DD")
    return _now_uk()


def run(script, csv_path, env):
    print("  -> " + os.path.basename(script))
    res = subprocess.run([sys.executable, script, csv_path], cwd=HERE, env=env,
                         capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout); print(res.stderr)
        fail(os.path.basename(script) + " failed.")
    for line in res.stdout.strip().splitlines()[-4:]:
        print("     " + line)


def swap(now):
    if not os.path.exists(SITE_HTML):
        fail("Missing site file: " + SITE_HTML)
    if not os.path.exists(JSON_PATH):
        fail("Data file not produced; aggregation may have failed.")
    data = json.load(open(JSON_PATH, encoding="utf-8"))
    # Strip tzinfo so the ISO string stays in the same shape as before (no
    # "+01:00" suffix). The wall-clock value is already UK local time.
    generated = now.replace(microsecond=0)
    if generated.tzinfo is not None:
        generated = generated.replace(tzinfo=None)
    data["generated_at"] = generated.isoformat()
    blob = "const DATA=" + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\nconst C="
    html = open(SITE_HTML, encoding="utf-8").read()
    pat = re.compile(r"const DATA=\{.*?\};\nconst C=", re.DOTALL)
    if not pat.search(html):
        fail("Could not find the data block in docs/index.html.")
    out = pat.sub(lambda _: blob, html, count=1)
    tmp = SITE_HTML + ".tmp"
    open(tmp, "w", encoding="utf-8").write(out)
    os.replace(tmp, SITE_HTML)


def main():
    args = sys.argv[1:]
    csv_path = find_csv(args)
    now = parse_now(args)
    print("Building dashboard")
    print("  CSV   : " + csv_path)
    print("  As at : " + now.strftime("%H:%M %d %b %Y"))
    env = dict(os.environ)
    env["PIP_NOW"] = now.isoformat()
    env["PIP_JSON"] = JSON_PATH
    env["PIP_CSV"] = csv_path
    run(os.path.join(HERE, "aggregate.py"), csv_path, env)
    run(os.path.join(HERE, "supplement.py"), csv_path, env)
    swap(now)
    print("BUILD OK -> docs/index.html")


if __name__ == "__main__":
    main()
