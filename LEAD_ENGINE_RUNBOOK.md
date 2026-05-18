# 1L Lead Engine Runbook

## Where Things Stand

The CrewAI engine and local dashboard are built.

Current blocker: this computer is using Python 3.14.4, but current CrewAI releases require Python 3.10 through 3.13. The dashboard will run on Python 3.14, but the CrewAI engine needs a Python 3.13 or 3.12 virtual environment.

## Files

- `main.py` - CrewAI multi-agent engine.
- `dashboard.py` - local dashboard server.
- `dashboard/` - dashboard web interface.
- `requirements.txt` - Python packages for the engine.
- `pyproject.toml` - project metadata and supported Python version.
- `.gitignore` - keeps `.env`, `.venv`, caches, and generated files out of git.

## Start The Dashboard

Easiest option:

- Double-click `1L Lead Engine Dashboard` on the Desktop.

Project-folder option:

- Double-click `Start_Dashboard.bat` in the project folder.

PowerShell option:

```powershell
python dashboard.py 8787
```

Then open:

```text
http://127.0.0.1:8787
```

If PowerShell says it cannot find `dashboard.py`, you are in the wrong folder. Run:

```powershell
cd "C:\Users\tyler\OneDrive\Documents\New project"
python dashboard.py 8787
```

Leave that PowerShell window open while using the dashboard. If you close it, the dashboard stops.

The desktop shortcut was created at:

```text
C:\Users\tyler\OneDrive\Desktop\1L Lead Engine Dashboard.lnk
```

## After The Dashboard Opens

Do these in order.

1. Click the `Lead Finder` tab.
2. Try `Add a lead manually` first.
3. Use a real public business prospect, for example an interior designer, property manager, builder, remodeler, or real estate agent.
4. Click `Save Lead`.
5. Look at the score:
   - `hot` means strong target.
   - `warm` means possible target.
   - `cold` means weak target or missing info.
6. Click `Export CSV` to create `lead_data/leads.csv`.
7. Do not click `Send Warm/Hot to n8n` until `N8N_WEBHOOK_URL` is configured.

This manual test proves the lead database, scoring, and CSV export work before adding live automation.

## Fix The CrewAI Runtime

Recommended automated setup:

```powershell
cd "C:\Users\tyler\OneDrive\Documents\New project"
.\setup_lead_engine.ps1
```

If PowerShell blocks scripts, run this once, then try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

The setup script will:
- Look for Python 3.13.
- Download/install Python 3.13 locally into `.python313` if needed.
- Also check common Python 3.13 install locations if the Python launcher does not list it.
- Recreate `.venv` if it was made with Python 3.14.
- Install `requirements.txt`.
- Run the dry-run smoke test.

Manual setup:

Install Python 3.13 or 3.12, then create the project environment:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --dry-run --smoke-test
```

If Python 3.13 is not installed yet, install it from python.org and make sure the Python launcher is enabled.

If you already have a broken `.venv` from Python 3.14, remove it first:

```powershell
cd "C:\Users\tyler\OneDrive\Documents\New project"
Remove-Item -Recurse -Force .venv
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then test:

```powershell
.\.venv\Scripts\python.exe main.py --dry-run --smoke-test
```

The dashboard should then show CrewAI as ready.

## Required `.env` Values

```text
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OBSIDIAN_VAULT_PATH=C:\Users\tyler\OneDrive\Documents\New project
N8N_WEBHOOK_URL=https://your-n8n-domain/webhook/...
GITHUB_TOKEN=github_pat_...
GITHUB_REPOSITORY=owner/repo
GITHUB_BRANCH=main
DEPLOY_WORKDIR=C:\Users\tyler\OneDrive\Documents\New project\generated_site
ANTHROPIC_MODEL=anthropic/claude-sonnet-4
OPENAI_MODEL=openai/gpt-4o
GOOGLE_PLACES_API_KEY=AIza...
```

`GOOGLE_PLACES_API_KEY` is optional, but it is what turns the Lead Finder search box into real public business discovery. Without it, the dashboard still supports manual lead entry, scoring, CSV export, and n8n handoff.

## Total Automation Stack

Recommended stack:

- Cursor AI: editing the code, asking questions about files, running terminal commands, and helping you fix setup errors.
- Codex: building and modifying the automation system.
- Python 3.13: runs CrewAI and the dashboard backend.
- CrewAI: runs the CEO, Developer, Marketer, and future Lead Finder agents.
- Obsidian: long-term memory and strategy log.
- Google Places API: public business discovery for lead finding.
- Local `lead_data` folder: first lead database.
- Google Sheets: later lead review dashboard if you want cloud access.
- n8n: real-world automation, outreach task creation, social posting, notifications, and approvals.
- GitHub: stores website/app code.
- Vercel: publishes landing pages automatically from GitHub.

Cursor AI can absolutely help, but use it as the workbench, not the automation brain. The automation brain is this project: dashboard, CrewAI, lead database, n8n, GitHub, and Obsidian.

## Safe Test

Use this before any live push or n8n post:

```powershell
.\.venv\Scripts\python.exe main.py --dry-run --smoke-test
```

## Lead Finder

The dashboard now has a Lead Finder tab.

What works now:

- Add public business prospects manually.
- Score prospects automatically.
- Export prospects to `lead_data/leads.csv`.
- Send warm/hot prospects to n8n for review-ready outreach tasks.

What needs one more key:

- Add `GOOGLE_PLACES_API_KEY` to `.env` to search public businesses from the dashboard, such as `interior designers Sarasota FL`, `property managers Sarasota FL`, or `custom home builders Sarasota FL`.

Lead data is stored locally in `lead_data/leads.json`. That folder is ignored by git because it may contain prospect contact information.

For Google Places setup details, see `GOOGLE_PLACES_SETUP.md`.

## Live Run

Only run this once the smoke test passes and the dashboard shows the required settings are present:

```powershell
.\.venv\Scripts\python.exe main.py --live --iterations 1
```
