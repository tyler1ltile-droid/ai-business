const elements = {
  workspace: document.querySelector("#workspace"),
  runStatus: document.querySelector("#run-status"),
  enginePython: document.querySelector("#engine-python"),
  summaryList: document.querySelector("#summary-list"),
  envList: document.querySelector("#env-list"),
  runtimeList: document.querySelector("#runtime-list"),
  pythonVersions: document.querySelector("#python-versions"),
  logOutput: document.querySelector("#log-output"),
  memoryPath: document.querySelector("#memory-path"),
  memoryOutput: document.querySelector("#memory-output"),
  filesList: document.querySelector("#files-list"),
  leadTotal: document.querySelector("#lead-total"),
  leadHot: document.querySelector("#lead-hot"),
  leadWarm: document.querySelector("#lead-warm"),
  leadCold: document.querySelector("#lead-cold"),
  leadQuery: document.querySelector("#lead-query"),
  leadLocation: document.querySelector("#lead-location"),
  leadLimit: document.querySelector("#lead-limit"),
  leadSearchButton: document.querySelector("#lead-search-button"),
  manualName: document.querySelector("#manual-name"),
  manualCategory: document.querySelector("#manual-category"),
  manualWebsite: document.querySelector("#manual-website"),
  manualPhone: document.querySelector("#manual-phone"),
  manualEmail: document.querySelector("#manual-email"),
  manualLocation: document.querySelector("#manual-location"),
  manualNotes: document.querySelector("#manual-notes"),
  leadAddButton: document.querySelector("#lead-add-button"),
  leadExportButton: document.querySelector("#lead-export-button"),
  leadSendButton: document.querySelector("#lead-send-button"),
  leadMessage: document.querySelector("#lead-message"),
  leadList: document.querySelector("#lead-list"),
  businessGoal: document.querySelector("#business-goal"),
  iterations: document.querySelector("#iterations"),
  refreshButton: document.querySelector("#refresh-button"),
  smokeButton: document.querySelector("#smoke-button"),
  dryButton: document.querySelector("#dry-button"),
  liveButton: document.querySelector("#live-button"),
  stopButton: document.querySelector("#stop-button"),
};

let lastStatus = null;

function indicator(kind) {
  return `<span class="indicator ${kind}" aria-hidden="true"></span>`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setStatus(operation) {
  elements.runStatus.classList.remove("running", "error", "idle");
  if (operation.running) {
    elements.runStatus.textContent = "Running";
    elements.runStatus.classList.add("running");
    return;
  }
  if (operation.last_exit_code && operation.last_exit_code !== 0) {
    elements.runStatus.textContent = "Needs attention";
    elements.runStatus.classList.add("error");
    return;
  }
  elements.runStatus.textContent = "Idle";
  elements.runStatus.classList.add("idle");
}

function renderSummary(data) {
  const missingEnv = data.missing_required_env.length;
  const crewReady = data.crewai.ready;
  const pythonOk = data.python.current.supported_for_crewai;
  const mainExists = data.main_exists;
  const operation = data.operation.running;
  const leadCount = data.lead_summary?.count || 0;

  const items = [
    {
      ok: mainExists,
      title: mainExists ? "Engine script is in place" : "Engine script is missing",
      meta: mainExists
        ? "main.py exists and can be launched from this dashboard."
        : "The dashboard cannot find main.py in the workspace.",
    },
    {
      ok: pythonOk,
      title: pythonOk ? "Python version supports CrewAI" : "Python 3.13 or 3.12 is still needed",
      meta: pythonOk
        ? `Current Python ${data.python.current.version} is compatible.`
        : `Current Python ${data.python.current.version} is too new for current CrewAI releases.`,
    },
    {
      ok: crewReady,
      title: crewReady ? "CrewAI is installed for the engine" : "CrewAI is not ready yet",
      meta: crewReady
        ? "The selected engine Python can import CrewAI."
        : "Create the project environment with Python 3.13 or 3.12, then install requirements.",
    },
    {
      ok: missingEnv === 0,
      title: missingEnv === 0 ? "Environment is configured" : `${missingEnv} required settings missing`,
      meta: missingEnv === 0
        ? "The dashboard found all required .env values."
        : data.missing_required_env.join(", "),
    },
    {
      ok: leadCount > 0,
      title: leadCount > 0 ? `${leadCount} leads in database` : "Lead database is empty",
      meta: leadCount > 0
        ? "Lead Finder is saving and scoring prospects."
        : "Add a prospect manually or connect Google Places search.",
    },
    {
      ok: !operation,
      title: operation ? "An operation is running" : "No operation running",
      meta: operation ? "Watch logs below or stop the run." : "Ready for a smoke test once runtime is fixed.",
    },
  ];

  elements.summaryList.innerHTML = items
    .map((item) => `
      <div class="summary-item">
        ${indicator(item.ok ? "ok" : "bad")}
        <div>
          <p class="item-title">${item.title}</p>
          <p class="item-meta">${item.meta}</p>
        </div>
      </div>
    `)
    .join("");
}

function renderEnv(data) {
  elements.envList.innerHTML = data.environment
    .map((item) => `
      <div class="check-item">
        ${indicator(item.present ? "ok" : item.preview === "optional" ? "" : "bad")}
        <div>
          <p class="item-title">${item.name}</p>
          <p class="item-meta">${item.present ? item.preview : item.preview}</p>
        </div>
        <strong>${item.present ? "Set" : item.preview === "optional" ? "Optional" : "Missing"}</strong>
      </div>
    `)
    .join("");
}

function renderRuntime(data) {
  const runtimeItems = [
    {
      ok: data.python.current.supported_for_crewai,
      title: `Current Python ${data.python.current.version}`,
      meta: data.python.current.supported_for_crewai
        ? "Compatible with CrewAI."
        : "CrewAI currently needs Python below 3.14.",
    },
    {
      ok: data.crewai.ready,
      title: "CrewAI import test",
      meta: data.crewai.ready ? "Ready." : data.crewai.detail || "Not ready.",
    },
  ];

  elements.runtimeList.innerHTML = runtimeItems
    .map((item) => `
      <div class="check-item">
        ${indicator(item.ok ? "ok" : "bad")}
        <div>
          <p class="item-title">${item.title}</p>
          <p class="item-meta">${item.meta}</p>
        </div>
        <strong>${item.ok ? "OK" : "Fix"}</strong>
      </div>
    `)
    .join("");
  elements.pythonVersions.textContent = data.python.launcher_output || "Python launcher did not return a version list.";
}

function renderLogs(operation) {
  if (!operation.logs.length) {
    elements.logOutput.textContent = "Waiting for activity...";
    return;
  }
  elements.logOutput.textContent = operation.logs
    .map((entry) => `[${entry.time}] ${entry.source}: ${entry.message}`)
    .join("\n");
  elements.logOutput.scrollTop = elements.logOutput.scrollHeight;
}

function renderMemory(memory) {
  elements.memoryPath.textContent = memory.path || "OBSIDIAN_VAULT_PATH is not configured.";
  elements.memoryOutput.textContent = memory.content || "No memory content yet.";
}

function renderFiles(files) {
  if (!files.length) {
    elements.filesList.innerHTML = `
      <div class="file-item">
        ${indicator("")}
        <div>
          <p class="item-title">No generated files yet</p>
          <p class="item-meta">Run a dry-run or live operation once the engine is ready.</p>
        </div>
      </div>
    `;
    return;
  }

  elements.filesList.innerHTML = files
    .map((file) => `
      <div class="file-item">
        ${indicator("ok")}
        <div>
          <p class="item-title">${escapeHtml(file.name)}</p>
          <p class="item-meta">${escapeHtml(file.path)} - ${file.size} bytes</p>
        </div>
      </div>
    `)
    .join("");
}

function renderLeadSummary(summary) {
  const counts = summary?.counts || {};
  elements.leadTotal.textContent = summary?.count || 0;
  elements.leadHot.textContent = counts.hot || 0;
  elements.leadWarm.textContent = counts.warm || 0;
  elements.leadCold.textContent = counts.cold || 0;

  const leads = summary?.leads || [];
  if (!leads.length) {
    elements.leadList.innerHTML = `
      <div class="lead-item">
        <span class="score-pill cold">0</span>
        <div>
          <p class="item-title">No leads saved yet</p>
          <p class="item-meta">Add a lead manually or connect Google Places search.</p>
        </div>
      </div>
    `;
    return;
  }

  elements.leadList.innerHTML = leads
    .map((lead) => {
      const reasons = (lead.score_reasons || []).join(", ");
      return `
        <div class="lead-item">
          <span class="score-pill ${lead.score_label}">${lead.score}</span>
          <div>
            <p class="item-title">${escapeHtml(lead.name || "Unnamed lead")} <span class="score-pill ${lead.score_label}">${lead.score_label}</span></p>
            <p class="item-meta">${escapeHtml(lead.category || "Unknown category")} - ${escapeHtml(lead.location || "No location")}</p>
            <div class="lead-contact">
              ${lead.website ? `<span>${escapeHtml(lead.website)}</span>` : ""}
              ${lead.phone ? `<span>${escapeHtml(lead.phone)}</span>` : ""}
              ${lead.email ? `<span>${escapeHtml(lead.email)}</span>` : ""}
            </div>
            <p class="item-meta">${escapeHtml(reasons)}</p>
          </div>
        </div>
      `;
    })
    .join("");
}

async function refresh() {
  const response = await fetch("/api/status");
  const data = await response.json();
  lastStatus = data;

  elements.workspace.textContent = data.workspace;
  elements.enginePython.textContent = data.python.engine_python;
  setStatus(data.operation);
  renderSummary(data);
  renderEnv(data);
  renderRuntime(data);
  renderLogs(data.operation);
  renderMemory(data.memory);
  renderFiles(data.generated_files);
  renderLeadSummary(data.lead_summary);
}

async function runMode(mode) {
  if (mode === "live") {
    const confirmed = window.confirm("Live run can push to GitHub and trigger n8n. Continue?");
    if (!confirmed) return;
  }

  const payload = {
    mode,
    iterations: Number(elements.iterations.value || 1),
    business_goal: elements.businessGoal.value.trim(),
  };
  const response = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!result.ok) {
    window.alert(result.message);
  }
  await refresh();
}

async function stopRun() {
  const response = await fetch("/api/stop", { method: "POST" });
  const result = await response.json();
  if (!result.ok) {
    window.alert(result.message);
  }
  await refresh();
}

async function addManualLead() {
  const payload = {
    name: elements.manualName.value.trim(),
    category: elements.manualCategory.value.trim(),
    website: elements.manualWebsite.value.trim(),
    phone: elements.manualPhone.value.trim(),
    email: elements.manualEmail.value.trim(),
    location: elements.manualLocation.value.trim(),
    notes: elements.manualNotes.value.trim(),
    source: "manual",
  };
  if (!payload.name) {
    window.alert("Add a business name first.");
    return;
  }
  const response = await fetch("/api/leads/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  elements.leadMessage.textContent = result.message || "Lead saved.";
  if (result.ok) {
    elements.manualName.value = "";
    elements.manualCategory.value = "";
    elements.manualWebsite.value = "";
    elements.manualPhone.value = "";
    elements.manualEmail.value = "";
    elements.manualLocation.value = "";
    elements.manualNotes.value = "";
  }
  await refresh();
}

async function searchLeads() {
  const payload = {
    query: elements.leadQuery.value.trim(),
    location: elements.leadLocation.value.trim(),
    limit: Number(elements.leadLimit.value || 10),
  };
  const response = await fetch("/api/leads/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  elements.leadMessage.textContent = result.message || "Search complete.";
  await refresh();
}

async function exportLeads() {
  const response = await fetch("/api/leads/export");
  const text = await response.text();
  elements.leadMessage.textContent = `CSV exported to ${text}`;
}

async function sendLeadsToN8N() {
  const confirmed = window.confirm("Send warm and hot leads to n8n for review-ready outreach tasks?");
  if (!confirmed) return;
  const response = await fetch("/api/leads/send-n8n", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const result = await response.json();
  elements.leadMessage.textContent = result.message || "n8n handoff complete.";
  await refresh();
}

elements.refreshButton.addEventListener("click", refresh);
elements.smokeButton.addEventListener("click", () => runMode("smoke"));
elements.dryButton.addEventListener("click", () => runMode("dry-run"));
elements.liveButton.addEventListener("click", () => runMode("live"));
elements.stopButton.addEventListener("click", stopRun);
elements.leadAddButton.addEventListener("click", addManualLead);
elements.leadSearchButton.addEventListener("click", searchLeads);
elements.leadExportButton.addEventListener("click", exportLeads);
elements.leadSendButton.addEventListener("click", sendLeadsToN8N);

window.addEventListener("hashchange", () => {
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === window.location.hash);
  });
});

refresh();
setInterval(refresh, 2500);
