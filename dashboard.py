from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DASHBOARD_DIR = ROOT / "dashboard"
MAIN_SCRIPT = ROOT / "main.py"
DATA_DIR = ROOT / "lead_data"
LEADS_FILE = DATA_DIR / "leads.json"
MEMORY_FILE_NAME = "agent_memory.md"
REQUIRED_ENV = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OBSIDIAN_VAULT_PATH",
    "N8N_WEBHOOK_URL",
    "GITHUB_TOKEN",
    "GITHUB_REPOSITORY",
]
LEAD_KEYWORDS = {
    "ideal_partner": [
        "interior designer",
        "designer",
        "property manager",
        "builder",
        "custom home",
        "remodeler",
        "remodeling",
        "real estate",
        "kitchen",
        "bathroom",
    ],
    "quality_signal": [
        "luxury",
        "high-end",
        "custom",
        "design-build",
        "waterfront",
        "renovation",
        "remodel",
        "bath",
        "shower",
        "tile",
    ],
    "competitor": [
        "tile installer",
        "tile installation",
        "flooring installer",
        "flooring store",
    ],
}


class OperationState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.logs: list[dict[str, str]] = []
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.last_exit_code: int | None = None
        self.last_command: list[str] = []

    def append_log(self, source: str, message: str) -> None:
        with self.lock:
            self.logs.append(
                {
                    "time": time.strftime("%H:%M:%S"),
                    "source": source,
                    "message": message.rstrip(),
                }
            )
            self.logs = self.logs[-600:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            return {
                "running": running,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "last_exit_code": self.last_exit_code,
                "last_command": self.last_command,
                "logs": list(self.logs),
            }


STATE = OperationState()


def load_dotenv_values() -> dict[str, str]:
    env_path = ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def merged_env() -> dict[str, str]:
    env = dict(os.environ)
    for key, value in load_dotenv_values().items():
        env.setdefault(key, value)
    return env


def masked_env_status() -> list[dict[str, Any]]:
    env = merged_env()
    status = []
    for name in REQUIRED_ENV:
        value = env.get(name, "").strip()
        status.append(
            {
                "name": name,
                "present": bool(value),
                "preview": mask_value(value),
            }
        )
    for optional in [
        "GITHUB_BRANCH",
        "DEPLOY_WORKDIR",
        "ANTHROPIC_MODEL",
        "OPENAI_MODEL",
        "GOOGLE_PLACES_API_KEY",
    ]:
        value = env.get(optional, "").strip()
        status.append(
            {
                "name": optional,
                "present": bool(value),
                "preview": mask_value(value) if value else "optional",
            }
        )
    return status


def mask_value(value: str) -> str:
    if not value:
        return "missing"
    if len(value) <= 8:
        return "set"
    return f"{value[:4]}...{value[-4:]}"


def run_short(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def engine_python() -> str:
    explicit = os.environ.get("ENGINE_PYTHON", "").strip()
    if explicit:
        return explicit

    local_venv = ROOT / ".venv" / "Scripts" / "python.exe"
    if local_venv.exists():
        return str(local_venv)

    return sys.executable


def python_inventory() -> dict[str, Any]:
    current = {
        "executable": sys.executable,
        "version": platform.python_version(),
        "supported_for_crewai": sys.version_info < (3, 14) and sys.version_info >= (3, 10),
    }
    code, output = run_short(["py", "-0p"])
    return {
        "current": current,
        "launcher_available": code == 0,
        "launcher_output": output,
        "engine_python": engine_python(),
    }


def crewai_status() -> dict[str, Any]:
    py = engine_python()
    code, output = run_short(
        [
            py,
            "-c",
            "import sys; print(sys.version); import crewai; print(getattr(crewai, '__version__', 'installed'))",
        ]
    )
    return {
        "ready": code == 0,
        "python": py,
        "detail": output,
    }


def memory_snapshot() -> dict[str, Any]:
    env = merged_env()
    vault = env.get("OBSIDIAN_VAULT_PATH", "").strip()
    if not vault:
        return {"configured": False, "path": "", "content": "OBSIDIAN_VAULT_PATH is not set."}

    memory_path = Path(vault).expanduser() / MEMORY_FILE_NAME
    if not memory_path.exists():
        return {
            "configured": True,
            "path": str(memory_path),
            "content": "No agent memory file exists yet.",
        }

    content = memory_path.read_text(encoding="utf-8", errors="replace")
    return {
        "configured": True,
        "path": str(memory_path),
        "content": content[-8000:],
    }


def generated_files() -> list[dict[str, Any]]:
    env = merged_env()
    deploy_path = Path(env.get("DEPLOY_WORKDIR", ROOT / "generated_site")).expanduser()
    if not deploy_path.exists():
        return []

    files = []
    for item in deploy_path.rglob("*"):
        if item.is_file() and ".git" not in item.parts:
            files.append(
                {
                    "path": str(item),
                    "name": item.name,
                    "size": item.stat().st_size,
                    "modified": item.stat().st_mtime,
                }
            )
    return sorted(files, key=lambda entry: entry["modified"], reverse=True)[:25]


def load_leads() -> list[dict[str, Any]]:
    if not LEADS_FILE.exists():
        return []
    try:
        data = json.loads(LEADS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def save_leads(leads: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LEADS_FILE.write_text(json.dumps(leads, indent=2), encoding="utf-8")


def lead_identity(lead: dict[str, Any]) -> str:
    basis = "|".join(
        [
            str(lead.get("name", "")).lower().strip(),
            str(lead.get("website", "")).lower().strip(),
            str(lead.get("phone", "")).lower().strip(),
            str(lead.get("email", "")).lower().strip(),
        ]
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def normalize_lead(raw: dict[str, Any]) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lead = {
        "name": str(raw.get("name", "")).strip(),
        "category": str(raw.get("category", "")).strip(),
        "website": str(raw.get("website", "")).strip(),
        "phone": str(raw.get("phone", "")).strip(),
        "email": str(raw.get("email", "")).strip(),
        "location": str(raw.get("location", "")).strip(),
        "source_url": str(raw.get("source_url", "")).strip(),
        "notes": str(raw.get("notes", "")).strip(),
        "source": str(raw.get("source", "manual")).strip() or "manual",
        "status": str(raw.get("status", "new")).strip() or "new",
        "created_at": str(raw.get("created_at", now)),
        "updated_at": now,
        "sent_to_n8n": bool(raw.get("sent_to_n8n", False)),
    }
    lead["id"] = str(raw.get("id") or lead_identity(lead))
    score, label, reasons = score_lead(lead)
    lead["score"] = score
    lead["score_label"] = label
    lead["score_reasons"] = reasons
    return lead


def score_lead(lead: dict[str, Any]) -> tuple[int, str, list[str]]:
    text = " ".join(
        str(lead.get(field, ""))
        for field in ["name", "category", "website", "location", "source_url", "notes"]
    ).lower()
    score = 20
    reasons: list[str] = ["Base public prospect record"]

    if lead.get("website"):
        score += 10
        reasons.append("Has website")
    if lead.get("phone"):
        score += 15
        reasons.append("Has phone")
    if lead.get("email"):
        score += 15
        reasons.append("Has email")

    if any(place in text for place in ["sarasota", "bradenton", "venice", "lakewood ranch", "siesta key"]):
        score += 15
        reasons.append("Local service-area signal")

    if any(keyword in text for keyword in LEAD_KEYWORDS["ideal_partner"]):
        score += 25
        reasons.append("Likely referral or project partner")

    if any(keyword in text for keyword in LEAD_KEYWORDS["quality_signal"]):
        score += 15
        reasons.append("Quality/remodeling signal")

    if any(keyword in text for keyword in LEAD_KEYWORDS["competitor"]):
        score -= 15
        reasons.append("Possible direct competitor")

    score = max(0, min(score, 100))
    if score >= 75:
        label = "hot"
    elif score >= 50:
        label = "warm"
    else:
        label = "cold"
    return score, label, reasons


def upsert_leads(new_leads: list[dict[str, Any]]) -> dict[str, Any]:
    existing = {lead["id"]: lead for lead in load_leads() if lead.get("id")}
    added = 0
    updated = 0

    for raw in new_leads:
        lead = normalize_lead(raw)
        if lead["id"] in existing:
            original_created = existing[lead["id"]].get("created_at")
            lead["created_at"] = original_created or lead["created_at"]
            existing[lead["id"]] = lead
            updated += 1
        else:
            existing[lead["id"]] = lead
            added += 1

    leads = sorted(existing.values(), key=lambda entry: entry.get("score", 0), reverse=True)
    save_leads(leads)
    return {"added": added, "updated": updated, "total": len(leads), "leads": leads}


def lead_summary() -> dict[str, Any]:
    leads = load_leads()
    counts = {"hot": 0, "warm": 0, "cold": 0}
    for lead in leads:
        label = lead.get("score_label", "cold")
        counts[label] = counts.get(label, 0) + 1

    return {
        "count": len(leads),
        "counts": counts,
        "leads": leads,
        "csv_path": str(DATA_DIR / "leads.csv"),
        "google_places_ready": bool(merged_env().get("GOOGLE_PLACES_API_KEY", "").strip()),
    }


def export_leads_csv() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = DATA_DIR / "leads.csv"
    fields = [
        "score",
        "score_label",
        "name",
        "category",
        "website",
        "phone",
        "email",
        "location",
        "source_url",
        "notes",
        "status",
        "source",
        "created_at",
        "updated_at",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for lead in load_leads():
            writer.writerow({field: lead.get(field, "") for field in fields})
    return csv_path


def google_places_search(payload: dict[str, Any]) -> dict[str, Any]:
    env = merged_env()
    api_key = env.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "message": "GOOGLE_PLACES_API_KEY is missing. Add it to .env to use web lead search.",
            "added": 0,
            "leads": load_leads(),
        }

    query = str(payload.get("query", "")).strip()
    location = str(payload.get("location", "Sarasota FL")).strip()
    limit = max(1, min(int(payload.get("limit", 10) or 10), 20))
    if not query:
        return {"ok": False, "message": "Search query is required.", "added": 0, "leads": load_leads()}

    search_url = "https://places.googleapis.com/v1/places:searchText"
    request_body = {
        "textQuery": f"{query} {location}",
        "pageSize": limit,
    }
    request = Request(
        search_url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "1L Lead Engine Dashboard",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.nationalPhoneNumber,places.websiteUri,places.googleMapsUri,"
                "places.types,places.rating,places.userRatingCount"
            ),
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    candidates = []
    for result in data.get("places", [])[:limit]:
        display_name = result.get("displayName") or {}
        candidates.append(
            {
                "name": display_name.get("text", ""),
                "category": ", ".join(result.get("types", [])),
                "website": result.get("websiteUri", ""),
                "phone": result.get("nationalPhoneNumber", ""),
                "location": result.get("formatted_address", location),
                "source_url": result.get("googleMapsUri", ""),
                "notes": f"Google rating {result.get('rating', 'n/a')}; user ratings {result.get('userRatingCount', 'n/a')}",
                "source": "google_places",
            }
        )

    result = upsert_leads(candidates)
    return {
        "ok": True,
        "message": f"Imported {result['added']} new leads and updated {result['updated']}.",
        **result,
    }


def send_leads_to_n8n(payload: dict[str, Any]) -> dict[str, Any]:
    env = merged_env()
    webhook_url = env.get("N8N_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return {"ok": False, "message": "N8N_WEBHOOK_URL is missing."}

    selected_ids = set(payload.get("ids") or [])
    leads = load_leads()
    if selected_ids:
        leads_to_send = [lead for lead in leads if lead.get("id") in selected_ids]
    else:
        leads_to_send = [lead for lead in leads if lead.get("score_label") in {"hot", "warm"}]

    if not leads_to_send:
        return {"ok": False, "message": "No warm or hot leads to send."}

    action_payload = {
        "task_type": "lead_research_batch",
        "source": "1l_lead_dashboard",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "leads": leads_to_send,
        "instructions": (
            "Prepare review-ready outreach tasks. Do not send messages without Tyler's approval."
        ),
    }
    request = Request(
        webhook_url,
        data=json.dumps(action_payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "1L Lead Engine Dashboard"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")

    lead_ids = {lead["id"] for lead in leads_to_send}
    updated = []
    for lead in leads:
        if lead.get("id") in lead_ids:
            lead["sent_to_n8n"] = True
            lead["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        updated.append(lead)
    save_leads(updated)

    return {
        "ok": True,
        "message": f"Sent {len(leads_to_send)} leads to n8n.",
        "response_preview": body[:500],
    }


def start_process(payload: dict[str, Any]) -> tuple[bool, str]:
    with STATE.lock:
        if STATE.process is not None and STATE.process.poll() is None:
            return False, "An operation is already running."

    mode = payload.get("mode", "smoke")
    iterations = int(payload.get("iterations", 1) or 1)
    iterations = max(1, min(iterations, 24))
    business_goal = str(payload.get("business_goal", "")).strip()

    command = [engine_python(), str(MAIN_SCRIPT)]
    if mode == "smoke":
        command.extend(["--dry-run", "--smoke-test"])
    elif mode == "dry-run":
        command.extend(["--dry-run", "--iterations", str(iterations)])
    elif mode == "live":
        command.extend(["--live", "--iterations", str(iterations)])
    else:
        return False, f"Unknown mode: {mode}"

    if business_goal:
        command.extend(["--business-goal", business_goal])

    env = merged_env()
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    with STATE.lock:
        STATE.process = process
        STATE.started_at = time.time()
        STATE.finished_at = None
        STATE.last_exit_code = None
        STATE.last_command = command
        STATE.logs.clear()

    STATE.append_log("dashboard", "Started: " + " ".join(command))
    threading.Thread(target=stream_process_logs, args=(process,), daemon=True).start()
    return True, "Operation started."


def stream_process_logs(process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        STATE.append_log("engine", line)

    exit_code = process.wait()
    with STATE.lock:
        STATE.last_exit_code = exit_code
        STATE.finished_at = time.time()
        STATE.process = None
    STATE.append_log("dashboard", f"Finished with exit code {exit_code}.")


def stop_process() -> tuple[bool, str]:
    with STATE.lock:
        process = STATE.process
    if process is None or process.poll() is not None:
        return False, "No operation is running."
    process.terminate()
    STATE.append_log("dashboard", "Stop requested.")
    return True, "Stop requested."


def status_payload() -> dict[str, Any]:
    py_info = python_inventory()
    crew = crewai_status()
    env = masked_env_status()
    missing = [item["name"] for item in env if not item["present"] and item["name"] in REQUIRED_ENV]

    return {
        "workspace": str(ROOT),
        "python": py_info,
        "crewai": crew,
        "environment": env,
        "missing_required_env": missing,
        "operation": STATE.snapshot(),
        "memory": memory_snapshot(),
        "generated_files": generated_files(),
        "lead_summary": lead_summary(),
        "main_exists": MAIN_SCRIPT.exists(),
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self.send_json(status_payload())
            return
        if parsed.path == "/api/logs":
            self.send_json(STATE.snapshot())
            return
        if parsed.path == "/api/memory":
            self.send_json(memory_snapshot())
            return
        if parsed.path == "/api/env-template":
            self.send_text(env_template(), content_type="text/plain")
            return
        if parsed.path == "/api/leads":
            self.send_json(lead_summary())
            return
        if parsed.path == "/api/leads/export":
            csv_path = export_leads_csv()
            self.send_text(str(csv_path), content_type="text/plain")
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            payload = self.read_json()
            ok, message = start_process(payload)
            self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.CONFLICT)
            return
        if parsed.path == "/api/stop":
            ok, message = stop_process()
            self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.CONFLICT)
            return
        if parsed.path == "/api/leads/add":
            payload = self.read_json()
            result = upsert_leads([payload])
            self.send_json({"ok": True, "message": "Lead saved.", **result})
            return
        if parsed.path == "/api/leads/search":
            payload = self.read_json()
            result = google_places_search(payload)
            self.send_json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/leads/send-n8n":
            payload = self.read_json()
            try:
                result = send_leads_to_n8n(payload)
            except Exception as exc:
                result = {"ok": False, "message": str(exc)}
            self.send_json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, payload: str, content_type: str = "text/plain") -> None:
        body = payload.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def env_template() -> str:
    return "\n".join(
        [
            "ANTHROPIC_API_KEY=sk-ant-...",
            "OPENAI_API_KEY=sk-...",
            "OBSIDIAN_VAULT_PATH=C:\\Users\\tyler\\OneDrive\\Documents\\New project",
            "N8N_WEBHOOK_URL=https://your-n8n-domain/webhook/...",
            "GITHUB_TOKEN=github_pat_...",
            "GITHUB_REPOSITORY=owner/repo",
            "GITHUB_BRANCH=main",
            "DEPLOY_WORKDIR=C:\\Users\\tyler\\OneDrive\\Documents\\New project\\generated_site",
            "ANTHROPIC_MODEL=anthropic/claude-sonnet-4",
            "OPENAI_MODEL=openai/gpt-4o",
            "GOOGLE_PLACES_API_KEY=AIza...",
        ]
    )


def parse_port() -> int:
    if len(sys.argv) >= 2:
        return int(sys.argv[1])
    return int(os.environ.get("DASHBOARD_PORT", "8787"))


def main() -> int:
    port = parse_port()
    DASHBOARD_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"Dashboard running at http://127.0.0.1:{port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
