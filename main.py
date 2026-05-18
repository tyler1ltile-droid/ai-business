from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("lead_engine")
MEMORY_FILE_NAME = "agent_memory.md"
DEFAULT_BUSINESS_GOAL = (
    "Generate qualified Sarasota-area leads for 1L Tile and Remodeling, "
    "prioritizing homeowners and designers who value certified waterproofing, "
    "shower remodels, backsplashes, and standards-based tile installation."
)


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or unsafe."""


class DependencyError(RuntimeError):
    """Raised when optional runtime dependencies are not installed."""


@dataclass(frozen=True)
class AppConfig:
    anthropic_api_key: str
    openai_api_key: str
    obsidian_vault_path: Path
    n8n_webhook_url: str
    github_token: str
    github_repository: str
    github_branch: str
    deploy_workdir: Path
    dry_run: bool
    anthropic_model: str
    openai_model: str


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def load_environment(dotenv_path: Path = Path(".env")) -> None:
    """Load .env without requiring python-dotenv at import time."""
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=dotenv_path, override=False)
        return
    except ModuleNotFoundError:
        pass

    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def current_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def env_value(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def missing_environment_names(require_deploy_target: bool = True) -> list[str]:
    required = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OBSIDIAN_VAULT_PATH",
        "N8N_WEBHOOK_URL",
        "GITHUB_TOKEN",
    ]
    if require_deploy_target:
        required.append("GITHUB_REPOSITORY")
    return [name for name in required if not env_value(name)]


def build_config(args: argparse.Namespace, temp_root: Path | None = None) -> AppConfig:
    dry_run = not args.live
    if args.dry_run and args.live:
        raise ConfigurationError("Choose either --dry-run or --live, not both.")

    if dry_run:
        root = temp_root or Path(tempfile.mkdtemp(prefix="lead-engine-"))
        vault_path = root / "dry_run_obsidian_vault"
        deploy_workdir = root / "dry_run_deploy_repo"
        vault_path.mkdir(parents=True, exist_ok=True)
        deploy_workdir.mkdir(parents=True, exist_ok=True)
        return AppConfig(
            anthropic_api_key=env_value("ANTHROPIC_API_KEY", "dry-run-anthropic-key"),
            openai_api_key=env_value("OPENAI_API_KEY", "dry-run-openai-key"),
            obsidian_vault_path=vault_path,
            n8n_webhook_url=env_value("N8N_WEBHOOK_URL", "https://example.invalid/n8n"),
            github_token=env_value("GITHUB_TOKEN", "dry-run-github-token"),
            github_repository=env_value("GITHUB_REPOSITORY", "dry-run-owner/dry-run-repo"),
            github_branch=env_value("GITHUB_BRANCH", "main"),
            deploy_workdir=deploy_workdir,
            dry_run=True,
            anthropic_model=env_value("ANTHROPIC_MODEL", "anthropic/claude-sonnet-4"),
            openai_model=env_value("OPENAI_MODEL", "openai/gpt-4o"),
        )

    missing = missing_environment_names(require_deploy_target=True)
    if missing:
        names = ", ".join(missing)
        raise ConfigurationError(f"Missing required environment variables: {names}")

    vault_path = Path(env_value("OBSIDIAN_VAULT_PATH")).expanduser()
    if not vault_path.exists() or not vault_path.is_dir():
        raise ConfigurationError("OBSIDIAN_VAULT_PATH must point to an existing folder.")

    deploy_default = Path.cwd() / "generated_site"
    deploy_workdir = Path(env_value("DEPLOY_WORKDIR", str(deploy_default))).expanduser()

    return AppConfig(
        anthropic_api_key=env_value("ANTHROPIC_API_KEY"),
        openai_api_key=env_value("OPENAI_API_KEY"),
        obsidian_vault_path=vault_path,
        n8n_webhook_url=env_value("N8N_WEBHOOK_URL"),
        github_token=env_value("GITHUB_TOKEN"),
        github_repository=env_value("GITHUB_REPOSITORY"),
        github_branch=env_value("GITHUB_BRANCH", "main"),
        deploy_workdir=deploy_workdir,
        dry_run=False,
        anthropic_model=env_value("ANTHROPIC_MODEL", "anthropic/claude-sonnet-4"),
        openai_model=env_value("OPENAI_MODEL", "openai/gpt-4o"),
    )


def import_crewai() -> tuple[Any, Any, Any, Any, Any, Any, Any, Any]:
    if sys.version_info >= (3, 14):
        raise DependencyError(
            "CrewAI currently publishes releases for Python >=3.10 and <3.14. "
            "Install Python 3.13 or 3.12, create a virtual environment with that Python, "
            "then run: python -m pip install -r requirements.txt"
        )

    try:
        from crewai import Agent, Crew, LLM, Process, Task
        from crewai.tools import BaseTool
        from pydantic import BaseModel, Field
    except ModuleNotFoundError as exc:
        raise DependencyError(
            "CrewAI dependencies are missing. Install them with: "
            "python -m pip install -r requirements.txt"
        ) from exc
    return Agent, Crew, LLM, Process, Task, BaseTool, BaseModel, Field


def import_requests() -> Any:
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise DependencyError(
            "The requests package is missing. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc
    return requests


def safe_filename(filename: str) -> str:
    cleaned = Path(filename or "index.html").name
    if not cleaned.lower().endswith((".html", ".htm")):
        cleaned = f"{cleaned}.html"
    return cleaned


def inject_assets(html: str, css_filename: str, js_filename: str, has_css: bool, has_js: bool) -> str:
    result = html or "<!doctype html><html><head><title>1L Tile</title></head><body></body></html>"
    if has_css and css_filename not in result:
        link = f'<link rel="stylesheet" href="{css_filename}">'
        result = result.replace("</head>", f"  {link}\n</head>") if "</head>" in result else f"{link}\n{result}"
    if has_js and js_filename not in result:
        script = f'<script src="{js_filename}" defer></script>'
        result = result.replace("</body>", f"  {script}\n</body>") if "</body>" in result else f"{result}\n{script}"
    return result


def git_auth_header(token: str) -> str:
    raw = f"x-access-token:{token}".encode("utf-8")
    return "AUTHORIZATION: basic " + base64.b64encode(raw).decode("ascii")


def run_git(args: list[str], cwd: Path | None, token: str | None = None) -> subprocess.CompletedProcess[str]:
    command = ["git"]
    if token:
        command.extend(["-c", f"http.https://github.com/.extraheader={git_auth_header(token)}"])
    command.extend(args)
    LOGGER.debug("Running git command: git %s", " ".join(args))
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )


def ensure_git_checkout(config: AppConfig) -> None:
    if config.dry_run:
        config.deploy_workdir.mkdir(parents=True, exist_ok=True)
        return

    repo_url = f"https://github.com/{config.github_repository}.git"
    if (config.deploy_workdir / ".git").exists():
        run_git(["fetch", "origin", config.github_branch], config.deploy_workdir, config.github_token)
        run_git(["checkout", config.github_branch], config.deploy_workdir)
        run_git(["pull", "--ff-only", "origin", config.github_branch], config.deploy_workdir, config.github_token)
        return

    if config.deploy_workdir.exists() and any(config.deploy_workdir.iterdir()):
        raise ConfigurationError(
            f"DEPLOY_WORKDIR is not empty and is not a git checkout: {config.deploy_workdir}"
        )

    config.deploy_workdir.parent.mkdir(parents=True, exist_ok=True)
    run_git(
        ["clone", "--branch", config.github_branch, repo_url, str(config.deploy_workdir)],
        cwd=None,
        token=config.github_token,
    )


def create_tool_classes(config: AppConfig) -> tuple[Any, Any, Any]:
    _, _, _, _, _, BaseTool, BaseModel, Field = import_crewai()

    class MemoryInput(BaseModel):
        action: str = Field(..., description="Use 'read' to read memory or 'append' to add a memory entry.")
        content: str = Field("", description="Text to append when action is 'append'.")

    class DeployInput(BaseModel):
        filename: str = Field("index.html", description="HTML filename to create or update.")
        html: str = Field(..., description="Complete HTML for the page.")
        css: str = Field("", description="Optional CSS to write to styles.css.")
        js: str = Field("", description="Optional JavaScript to write to script.js.")
        commit_message: str = Field("Update landing page", description="Git commit message.")

    class N8NInput(BaseModel):
        task_type: str = Field(..., description="Marketing task type, such as social_post or campaign_brief.")
        text: str = Field(..., description="Marketing text or task instructions to send to n8n.")
        metadata: dict[str, Any] = Field(default_factory=dict, description="Extra structured context.")

    class ObsidianMemoryTool(BaseTool):
        name: str = "obsidian_memory"
        description: str = (
            "Read or append the long-term memory file agent_memory.md inside the Obsidian vault."
        )
        args_schema: Any = MemoryInput

        def _run(self, action: str, content: str = "") -> str:
            memory_path = config.obsidian_vault_path / MEMORY_FILE_NAME
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            normalized = action.strip().lower()

            if normalized == "read":
                if not memory_path.exists():
                    return "No memory file exists yet."
                return memory_path.read_text(encoding="utf-8")

            if normalized == "append":
                entry = content.strip()
                if not entry:
                    return "No content supplied; memory was not changed."
                with memory_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"\n\n## {current_timestamp()}\n{entry}\n")
                return f"Appended memory entry to {memory_path.name}."

            return "Invalid action. Use 'read' or 'append'."

    class GitHubVercelDeployTool(BaseTool):
        name: str = "github_vercel_deploy"
        description: str = (
            "Write frontend code to the deployment repo and push it to GitHub so Vercel can deploy it."
        )
        args_schema: Any = DeployInput

        def _run(
            self,
            filename: str = "index.html",
            html: str = "",
            css: str = "",
            js: str = "",
            commit_message: str = "Update landing page",
        ) -> str:
            ensure_git_checkout(config)
            config.deploy_workdir.mkdir(parents=True, exist_ok=True)

            html_name = safe_filename(filename)
            css_name = "styles.css"
            js_name = "script.js"
            final_html = inject_assets(
                html=html,
                css_filename=css_name,
                js_filename=js_name,
                has_css=bool(css.strip()),
                has_js=bool(js.strip()),
            )

            html_path = config.deploy_workdir / html_name
            html_path.write_text(final_html, encoding="utf-8")
            written_files = [html_name]

            if css.strip():
                (config.deploy_workdir / css_name).write_text(css, encoding="utf-8")
                written_files.append(css_name)
            if js.strip():
                (config.deploy_workdir / js_name).write_text(js, encoding="utf-8")
                written_files.append(js_name)

            if config.dry_run:
                return json.dumps(
                    {
                        "dry_run": True,
                        "deploy_workdir": str(config.deploy_workdir),
                        "repository": config.github_repository,
                        "branch": config.github_branch,
                        "written_files": written_files,
                        "commit_message": commit_message,
                        "pushed": False,
                    },
                    indent=2,
                )

            run_git(["config", "user.name", "1L Lead Engine"], config.deploy_workdir)
            run_git(["config", "user.email", "lead-engine@users.noreply.github.com"], config.deploy_workdir)
            run_git(["add", *written_files], config.deploy_workdir)
            status = run_git(["status", "--short"], config.deploy_workdir).stdout.strip()
            if not status:
                return "No deployment changes detected; nothing to commit."

            run_git(["commit", "-m", commit_message[:200]], config.deploy_workdir)
            run_git(["push", "origin", config.github_branch], config.deploy_workdir, config.github_token)
            return f"Committed and pushed {', '.join(written_files)} to {config.github_repository}."

    class N8NWebhookTool(BaseTool):
        name: str = "n8n_webhook"
        description: str = "Send a structured marketing or social-media action payload to the n8n webhook."
        args_schema: Any = N8NInput

        def _run(self, task_type: str, text: str, metadata: dict[str, Any] | None = None) -> str:
            payload = {
                "task_type": task_type,
                "text": text,
                "metadata": metadata or {},
                "source": "crewai_1l_tile_lead_engine",
                "timestamp": current_timestamp(),
                "dry_run": config.dry_run,
            }

            if config.dry_run:
                return json.dumps({"dry_run": True, "payload": payload, "sent": False}, indent=2)

            requests = import_requests()
            response = requests.post(config.n8n_webhook_url, json=payload, timeout=30)
            response.raise_for_status()
            return f"n8n webhook accepted payload with status {response.status_code}."

    return ObsidianMemoryTool, GitHubVercelDeployTool, N8NWebhookTool


def build_crew(config: AppConfig, verbose: bool = False) -> Any:
    Agent, Crew, LLM, Process, Task, *_ = import_crewai()
    ObsidianMemoryTool, GitHubVercelDeployTool, N8NWebhookTool = create_tool_classes(config)

    llm_provider = env_value("LLM_PROVIDER", "anthropic").lower()
    if llm_provider == "openai":
        strategist_llm = marketer_llm = LLM(
            model=config.openai_model,
            api_key=config.openai_api_key,
            temperature=0.45,
            max_tokens=4096,
        )
        LOGGER.info("LLM_PROVIDER=openai — strategist and marketer on %s", config.openai_model)
    else:
        strategist_llm = LLM(
            model=config.anthropic_model,
            api_key=config.anthropic_api_key,
            temperature=0.35,
            max_tokens=4096,
        )
        marketer_llm = LLM(
            model=config.anthropic_model,
            api_key=config.anthropic_api_key,
            temperature=0.55,
            max_tokens=4096,
        )
    developer_llm = LLM(
        model=config.openai_model,
        api_key=config.openai_api_key,
        temperature=0.25,
    )

    memory_tool = ObsidianMemoryTool()
    deploy_tool = GitHubVercelDeployTool()
    n8n_tool = N8NWebhookTool()

    strategist = Agent(
        role="CEO / Strategist for 1L Tile Lead Generation",
        goal=(
            "Use the business memory to choose the highest-leverage next campaign "
            "for qualified Sarasota tile, shower, backsplash, and remodeling leads."
        ),
        backstory=(
            "You are the strategic operator for 1L Tile and Remodeling. You protect the brand: "
            "certified, standards-based, waterproofing-first, designer-friendly, locally accountable."
        ),
        llm=strategist_llm,
        tools=[memory_tool],
        verbose=verbose,
        allow_delegation=False,
        max_iter=6,
    )

    developer = Agent(
        role="Frontend Developer / Deployment Engineer",
        goal=(
            "Create a focused lead-generation sales page and deploy it through the GitHub/Vercel workflow."
        ),
        backstory=(
            "You build clean, mobile-friendly sales pages that make homeowners trust the craft, "
            "understand waterproofing value, and take the next contact step."
        ),
        llm=developer_llm,
        tools=[deploy_tool],
        verbose=verbose,
        allow_delegation=False,
        max_iter=8,
    )

    marketer = Agent(
        role="Local Marketing Operator",
        goal=(
            "Turn the campaign and deployed page into direct-response social and marketing tasks."
        ),
        backstory=(
            "You write practical, trust-building promotional content for Sarasota homeowners, "
            "designers, property managers, and referral partners."
        ),
        llm=marketer_llm,
        tools=[n8n_tool],
        verbose=verbose,
        allow_delegation=False,
        max_iter=6,
    )

    strategy_task = Task(
        description=(
            "Read Obsidian memory, then choose one campaign objective for this run. "
            "Business goal: {business_goal}. Current date: {current_date}. "
            "Append a concise strategic note to memory with the chosen objective, audience, offer, "
            "proof points, and next action. Return a campaign brief the developer and marketer can use."
        ),
        expected_output=(
            "A concise campaign brief with audience, offer, page angle, proof points, CTA, "
            "and success metric."
        ),
        agent=strategist,
    )

    development_task = Task(
        description=(
            "Using the campaign brief, create a complete responsive landing page for 1L Tile. "
            "Use the deployment tool with filename 'index.html'. The page must include a strong headline, "
            "local Sarasota trust signals, waterproofing education, services, guarantee language, "
            "and a contact CTA using phone 941-650-1222 and email tyler1ltile@gmail.com. "
            "Keep it honest and avoid unsupported claims."
        ),
        expected_output=(
            "Deployment summary containing written files, repository, branch, and whether this was dry-run or live."
        ),
        agent=developer,
    )

    marketing_task = Task(
        description=(
            "Using the campaign brief and deployment summary, draft a social promotion package and send it "
            "to n8n with task_type 'local_tile_lead_campaign'. Include 3 social captions, one short outreach "
            "message for designers or property managers, CTA, target audience, and deployment context."
        ),
        expected_output="n8n webhook result plus the exact marketing package summary.",
        agent=marketer,
    )

    memory_task = Task(
        description=(
            "Summarize the strategy, page deployment result, marketing result, unresolved risks, "
            "and the next best action. Append that summary to Obsidian memory."
        ),
        expected_output="A final operations log entry with next action.",
        agent=strategist,
    )

    return Crew(
        agents=[strategist, developer, marketer],
        tasks=[strategy_task, development_task, marketing_task, memory_task],
        process=Process.sequential,
        verbose=verbose,
        memory=False,
    )


def run_smoke_test(config: AppConfig, verbose: bool = False) -> int:
    LOGGER.info("Running dry-run smoke test.")

    missing = missing_environment_names(require_deploy_target=True)
    if missing:
        LOGGER.info("Environment check: missing %s", ", ".join(missing))
    else:
        LOGGER.info("Environment check: all expected names are present.")

    ObsidianMemoryTool, GitHubVercelDeployTool, N8NWebhookTool = create_tool_classes(config)

    memory_tool = ObsidianMemoryTool()
    append_result = memory_tool._run("append", "Smoke test memory entry.")
    read_result = memory_tool._run("read")
    if "Smoke test memory entry." not in read_result:
        raise RuntimeError("Memory smoke test failed.")
    LOGGER.info("Memory tool ok: %s", append_result)

    deploy_tool = GitHubVercelDeployTool()
    deploy_result = deploy_tool._run(
        filename="index.html",
        html="<!doctype html><html><head><title>Smoke</title></head><body><h1>1L Tile</h1></body></html>",
        css="body { font-family: Arial, sans-serif; }",
        js="console.log('dry run');",
        commit_message="Smoke test deployment",
    )
    deploy_payload = json.loads(deploy_result)
    if deploy_payload.get("pushed") is not False:
        raise RuntimeError("Deployment dry-run smoke test unexpectedly pushed.")
    LOGGER.info("Deployment tool ok: wrote %s", ", ".join(deploy_payload["written_files"]))

    n8n_tool = N8NWebhookTool()
    n8n_result = n8n_tool._run(
        task_type="smoke_test",
        text="Dry-run test payload.",
        metadata={"business": "1L Tile"},
    )
    n8n_payload = json.loads(n8n_result)
    if n8n_payload.get("sent") is not False:
        raise RuntimeError("n8n dry-run smoke test unexpectedly sent.")
    LOGGER.info("n8n tool ok: payload built, not sent.")

    crew = build_crew(config, verbose=verbose)
    if len(crew.agents) != 3 or len(crew.tasks) != 4:
        raise RuntimeError("Crew initialization smoke test failed.")
    LOGGER.info("Crew initialization ok: %s agents, %s tasks.", len(crew.agents), len(crew.tasks))
    LOGGER.info("Smoke test complete.")
    return 0


def run_iteration(config: AppConfig, business_goal: str, verbose: bool = False) -> Any:
    crew = build_crew(config, verbose=verbose)
    return crew.kickoff(
        inputs={
            "business_goal": business_goal,
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "dry_run": str(config.dry_run),
        }
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CrewAI 1L Tile autonomous lead-generation engine.")
    parser.add_argument("--dry-run", action="store_true", help="Run without GitHub pushes or n8n posts.")
    parser.add_argument("--live", action="store_true", help="Allow live GitHub pushes and n8n webhook calls.")
    parser.add_argument("--iterations", type=int, default=1, help="Number of crew iterations to run.")
    parser.add_argument("--loop", action="store_true", help="Continue running until stopped.")
    parser.add_argument("--interval-minutes", type=float, default=60.0, help="Delay between loop iterations.")
    parser.add_argument("--business-goal", default=DEFAULT_BUSINESS_GOAL, help="Goal supplied to the crew.")
    parser.add_argument("--smoke-test", action="store_true", help="Test tools and crew initialization only.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    configure_logging(verbose=args.verbose)
    load_environment()

    if args.iterations < 1:
        raise ConfigurationError("--iterations must be at least 1.")
    if args.interval_minutes <= 0:
        raise ConfigurationError("--interval-minutes must be greater than 0.")

    with tempfile.TemporaryDirectory(prefix="lead-engine-") as temp_dir:
        config = build_config(args, temp_root=Path(temp_dir))
        LOGGER.info("Mode: %s", "DRY RUN" if config.dry_run else "LIVE")

        if args.smoke_test:
            if not config.dry_run:
                raise ConfigurationError("Smoke tests must be run in dry-run mode.")
            return run_smoke_test(config, verbose=args.verbose)

        completed = 0
        while True:
            completed += 1
            LOGGER.info("Starting crew iteration %s.", completed)
            result = run_iteration(config, args.business_goal, verbose=args.verbose)
            LOGGER.info("Crew iteration %s complete: %s", completed, result)

            if not args.loop and completed >= args.iterations:
                break
            if args.loop and completed >= args.iterations:
                completed = 0

            sleep_seconds = int(args.interval_minutes * 60)
            LOGGER.info("Sleeping for %s seconds before the next iteration.", sleep_seconds)
            time.sleep(sleep_seconds)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfigurationError, DependencyError) as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(2)
    except subprocess.CalledProcessError as exc:
        LOGGER.error("Command failed with exit code %s: %s", exc.returncode, exc.stderr.strip())
        raise SystemExit(exc.returncode or 1)
