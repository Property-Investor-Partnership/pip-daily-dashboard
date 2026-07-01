# PIP Investments Dashboard — GitHub Pages Edition

This repository hosts your investments dashboard as a **free live web link** via GitHub Pages,
and rebuilds it from a HubSpot CSV export using the same scripts you already trust.

- **Live link** (after setup): `https://<your-github-username>.github.io/<repo-name>/`
- **No Perplexity credits.** The build runs on your Mac (or, later, automatically on GitHub).
- **Same figures** as before — `aggregate.py` + `supplement.py` are unchanged in their logic.

> Privacy note 1: GitHub Pages on a free plan is a **public** link (anyone with the URL can view).
> It isn't listed or indexed anywhere unless you share it. When you want true access control,
> we can put it behind Cloudflare Access (free) — that's a later step.
>
> Privacy note 2: **Raw HubSpot CSVs are never committed.** They contain client PII (names,
> emails, amounts). `.gitignore` blocks `data/*.csv`, and the automated workflow commits only the
> built `docs/index.html` (aggregated figures, no raw rows). Keep it that way.

---

## Folder layout

```
pip-dashboard-repo/
├── docs/                       ← GitHub Pages serves THIS folder (the live site)
│   ├── index.html              ← the dashboard
│   └── chart.umd.min.js        ← charts, bundled locally
├── data/                       ← HubSpot CSV exports go here (gitignored — never committed)
│   └── .gitkeep
├── .github/workflows/
│   └── refresh-dashboard.yml    ← automated daily fetch from HubSpot (Option B, Stage 2)
├── scripts/
│   ├── build.py                ← rebuilds docs/index.html from the newest CSV
│   ├── aggregate.py            ← number-crunching (live book, totals, by-year, etc.)
│   └── supplement.py           ← completions, pending, AUM-by-developer, extra totals
├── Refresh and Publish.command ← double-click: rebuild + push live (after setup)
├── .gitignore
└── README.md
```

---

## One-time setup

### 1. Create the repository on GitHub
1. On GitHub, click **New repository**. Name it e.g. `pip-dashboard`. Leave it empty (no README,
   no .gitignore — this package already includes one).
2. On your Mac, open **Terminal** and connect this folder to it:
   ```
   cd path/to/pip-dashboard-repo
   git init
   git add .
   git commit -m "Initial dashboard"
   git branch -M main
   git remote add origin https://github.com/<your-username>/pip-dashboard.git
   git push -u origin main
   ```
   (GitHub will prompt you to log in the first time.)

### 2. Turn on GitHub Pages
1. In the repo on GitHub: **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **Deploy from a branch**.
3. Set **Branch** to `main` and the folder to **`/docs`**, then **Save**.
4. After a minute, the page shows your live URL: `https://<username>.github.io/pip-dashboard/`.

That URL is now your shareable dashboard link. **This replaces the old pplx.app link.**

---

## Daily routine (about 2 minutes)

1. Export your investments from HubSpot to CSV (as you do today).
2. Drop the CSV into the **`data`** folder.
3. Double-click **Refresh and Publish.command**.
   - It rebuilds `docs/index.html` from the newest CSV, then pushes to GitHub.
   - Your live link updates within ~1 minute.

That's it. The dashboard header reads *"As at HH:MM DD MMM YYYY"* with the time you refreshed.

### Build locally without publishing
If you just want to rebuild and check it on your Mac without pushing:
```
cd scripts
python3 build.py                 # newest CSV in ../data
open ../docs/index.html          # view it
```

---

## Requirements (one time)
- **Python 3** — check with `python3 --version`. If missing, install from
  <https://www.python.org/downloads/>. No extra libraries needed.
- **git** — check with `git --version`. If missing, run `xcode-select --install`.

---

## Troubleshooting

**"No CSV found in data."** — Add a `.csv` export to the `data` folder.

**Figures look wrong / blank.** — HubSpot may have renamed a column. The scripts read columns by
their exact names (e.g. *Investment*, *Live Investment Status*, *Start Date*, *End Date*,
*Investment Pipeline Stage*, *Money Received On*, *Developer*). Keep the export headings the same.

**Push failed.** — Usually a login/internet issue. Your local build still updated; just re-run
the command once you're back online, or push manually with `git push`.

**"This folder isn't connected to GitHub yet."** — You haven't done the one-time setup above.

**Keep raw CSVs private.** — Already handled: `.gitignore` blocks all `data/*.csv`. The dashboard
never needs the CSV online — only the aggregated figures baked into `docs/index.html`.

---

## What the figures mean (reference)
- **Live FUM** — capital where *Live Investment Status = true*.
- **Completions (W/M/Y to date)** — capital that actually went live in the period (live, or
  not-live with a known *End Date*); excludes future-dated investments not yet started.
- **Total pending** — investments at pipeline stage **Money Received** (treated as pending).
- **Capital raised by year** — *Net new money* (dark) with *Rollover* (recycled) stacked (gold).

---

## Option B, Stage 2 — automated daily refresh from HubSpot

This repo includes a GitHub Action (`.github/workflows/refresh-dashboard.yml`) that runs every
morning, pulls the latest investment data straight from HubSpot, rebuilds `docs/index.html`, and
commits it — so your live link stays current with **zero manual steps**. No more CSV exports.

### How it works
1. `scripts/fetch_hubspot.py` reads the **investments** custom object (objectTypeId `2-143899386`)
   via the HubSpot API, paging by record ID to get **all** records (beats the 10k API cap), and
   writes `data/investment-export.csv` in the exact format the build expects.
2. `scripts/build.py` runs `aggregate.py` + `supplement.py` and swaps the fresh data into
   `docs/index.html`.
3. The workflow commits **only** `docs/index.html`; GitHub Pages redeploys automatically.

### One-time setup to enable it
1. **Create a HubSpot Private App token** (Settings → Integrations → Private Apps → Create).
   Scopes needed: `crm.objects.custom.read` and `crm.schemas.custom.read`. Copy the `pat-...` token.
2. **Add it as an encrypted repo secret:** repo → **Settings → Secrets and variables → Actions**
   → **New repository secret**. Name it exactly **`HUBSPOT_TOKEN`**, paste the token, save.
3. **Enable Actions write access:** repo → **Settings → Actions → General** → **Workflow
   permissions** → select **Read and write permissions** → Save.
4. Test it: repo → **Actions** tab → **Refresh dashboard from HubSpot** → **Run workflow**.
   Watch it go green, then check your live link updated.

### Changing the schedule
Edit the `cron:` line in the workflow. It's in **UTC**. `0 6 * * *` = 06:00 UTC = 07:00 London (BST).

### Manual push still works
The **Refresh and Publish.command** (double-click) remains available as a fallback if you ever want
to push a manual CSV export instead of waiting for the scheduled run.

*Generated by Perplexity Computer.*
