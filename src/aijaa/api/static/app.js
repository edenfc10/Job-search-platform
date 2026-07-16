const state = {
  seekerId: localStorage.getItem("aijaa.seekerId") || "",
  matches: [],
};

const sampleProfile = {
  contact: {
    full_name: "Dana Levi",
    email: "dana@example.com",
    phone: "+972-50-1234567",
    location: "Tel Aviv, Israel",
    links: ["https://linkedin.com/in/danalevi", "https://github.com/danalevi"],
  },
  work_history: [
    {
      company: "CloudWorks",
      title: "Senior Backend Engineer",
      start: "2021-03",
      end: null,
      location: "Tel Aviv",
      achievements: [
        {
          fact_id: "f1",
          text: "Reduced API p95 latency by 40% by rearchitecting the caching layer in Python and Redis",
          kind: "achievement",
          quantified: true,
        },
        {
          fact_id: "f2",
          text: "Led a team of 5 engineers building FastAPI microservices on Kubernetes serving 2M users",
          kind: "achievement",
          quantified: true,
        },
      ],
    },
    {
      company: "DataNest",
      title: "Backend Engineer",
      start: "2018-06",
      end: "2021-02",
      achievements: [
        {
          fact_id: "f3",
          text: "Built ETL pipelines in Python and PostgreSQL processing 500GB daily",
          kind: "achievement",
          quantified: true,
        },
      ],
    },
  ],
  education: [
    {
      institution: "Tel Aviv University",
      degree: "B.Sc.",
      field: "Computer Science",
      year: "2018",
    },
  ],
  skills: [
    "Python",
    "FastAPI",
    "PostgreSQL",
    "Kubernetes",
    "AWS",
    "Docker",
    "Redis",
  ].map((text, i) => ({ fact_id: `s${i + 1}`, text, kind: "skill" })),
  languages: ["English", "Hebrew"],
};

const samplePrefs = {
  target_titles: ["Senior Backend Engineer", "Backend Engineer", "Staff Engineer"],
  seniority: "senior",
  industries: ["SaaS", "Cloud"],
  locations: ["Tel Aviv", "Remote"],
  remote_policy: "hybrid",
  min_salary: 30000,
  currency: "ILS",
  work_authorization: "Israeli citizen",
  dealbreakers: ["gambling"],
  resume_languages: ["en", "he"],
};

const $ = (id) => document.getElementById(id);

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function setBusy(button, busy) {
  button.disabled = busy;
}

function toast(message, type = "ok") {
  const el = $("toast");
  el.textContent = message;
  el.className = `show ${type === "error" ? "error" : ""}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => {
    el.className = "";
  }, 3200);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = res.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = typeof body === "object" ? body.detail || pretty(body) : body;
    throw new Error(detail);
  }
  return body;
}

function parseJson(id) {
  const raw = $(id).value.trim();
  return raw ? JSON.parse(raw) : {};
}

function setSeeker(id) {
  state.seekerId = id;
  $("seeker-id").value = id;
  $("active-seeker").textContent = id ? `${id.slice(0, 8)}…` : "None";
  localStorage.setItem("aijaa.seekerId", id);
}

function requireSeeker() {
  const id = $("seeker-id").value.trim() || state.seekerId;
  if (!id) throw new Error("Create or enter a seeker id first.");
  setSeeker(id);
  return id;
}

async function refreshHealth() {
  const data = await api("/healthz");
  $("health-dot").className = "ok";
  $("health-status").textContent = "Online";
  $("health-detail").textContent = `${data.llm_mode} LLM · dry_run=${data.dry_run}`;
  $("dry-run").textContent = data.dry_run ? "On" : "Off";
}

async function createSeeker() {
  const data = await api("/v1/seekers", {
    method: "POST",
    body: JSON.stringify({
      external_ref: $("external-ref").value.trim(),
      consent_recorded_at: new Date().toISOString(),
    }),
  });
  setSeeker(data.seeker_id);
  toast("Seeker created.");
}

async function runIntake() {
  const seekerId = requireSeeker();
  const data = await api(`/v1/seekers/${seekerId}/intake/turns`, {
    method: "POST",
    body: JSON.stringify({
      free_text: $("free-text").value,
      profile_patch: parseJson("profile-json"),
      preferences_patch: parseJson("prefs-json"),
    }),
  });
  $("completeness").textContent = `${data.overall_completeness}%`;
  $("profile-output").textContent = pretty(data);
  toast("Intake turn saved.");
  await refreshProfile();
}

async function refreshProfile() {
  const seekerId = requireSeeker();
  const data = await api(`/v1/seekers/${seekerId}/profile`);
  $("completeness").textContent = `${data.completeness.overall}%`;
  $("profile-output").textContent = pretty(data);
  return data;
}

async function buildResume(language) {
  const seekerId = requireSeeker();
  const data = await api(`/v1/seekers/${seekerId}/resume`, {
    method: "POST",
    body: JSON.stringify({ language }),
  });
  $("resume-output").textContent = pretty(data);
  toast(`${language.toUpperCase()} resume generated.`);
}

async function runDiscovery() {
  const body = {
    fixtures_dir: $("fixtures-dir").value.trim() || null,
    greenhouse_orgs: splitList("greenhouse-orgs"),
    lever_orgs: splitList("lever-orgs"),
  };
  const data = await api("/v1/discovery/run", { method: "POST", body: JSON.stringify(body) });
  toast(`Discovery complete: ${data.created} created, ${data.updated} updated.`);
  return data;
}

function splitList(id) {
  return $(id).value.split(",").map((x) => x.trim()).filter(Boolean);
}

async function runMatching() {
  const seekerId = requireSeeker();
  const data = await api(`/v1/seekers/${seekerId}/match/run`, { method: "POST" });
  toast(`Matching complete: ${data.matches_created} new matches.`);
  await refreshMatches();
}

async function refreshMatches() {
  const seekerId = requireSeeker();
  const matches = await api(`/v1/seekers/${seekerId}/matches`);
  state.matches = matches;
  $("pending-count").textContent = matches.filter((m) => m.status === "pending").length;
  renderMatches(matches);
}

function renderMatches(matches) {
  const host = $("match-list");
  if (!matches.length) {
    host.innerHTML = "<div class=\"empty\">No surfaced matches yet.</div>";
    return;
  }
  host.innerHTML = "";
  for (const match of matches) {
    const card = document.createElement("article");
    card.className = "match-card";
    const risks = (match.risks || []).map((risk) => `<span class="pill">${risk}</span>`).join(" ");
    const decided = match.status !== "pending";
    card.innerHTML = `
      <div>
        <div class="match-title">
          <span class="score">${match.score}</span>
          <strong>${escapeHtml(match.posting?.company || "Unknown")}</strong>
          <span>${escapeHtml(match.posting?.title || "Untitled role")}</span>
          <span class="pill">${match.status}</span>
          <span class="pill">${match.application_status || "not started"}</span>
        </div>
        <p>${escapeHtml(match.rationale || "")}</p>
        <div class="risk-row">${risks}</div>
      </div>
      <div class="match-actions">
        <button class="primary" data-action="approve" data-id="${match.match_id}" ${decided ? "disabled" : ""}>Approve</button>
        <button class="secondary" data-action="reject" data-id="${match.match_id}" ${decided ? "disabled" : ""}>Reject</button>
        <button class="secondary" data-action="handoff" data-id="${match.match_id}">Handoff</button>
        <button class="secondary" data-action="select-app" data-id="${match.application_id || ""}">Select App</button>
      </div>
    `;
    host.appendChild(card);
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;",
  })[ch]);
}

async function decide(matchId, decision) {
  const data = await api(`/v1/matches/${matchId}/decision`, {
    method: "POST",
    body: JSON.stringify({
      decision,
      decided_by: $("operator-id").value.trim() || "operator",
    }),
  });
  toast(`Match ${data.status}.`);
  await refreshMatches();
}

async function handoff(matchId) {
  const data = await api(`/v1/matches/${matchId}/handoff`);
  $("timeline-output").textContent = pretty(data);
  if (data.application_status) {
    const match = state.matches.find((m) => m.match_id === matchId);
    if (match?.application_id) $("application-id").value = match.application_id;
  }
  toast("Handoff packet loaded.");
}

async function runApplication() {
  const appId = $("application-id").value.trim();
  if (!appId) throw new Error("Select or enter an application id.");
  const data = await api(`/v1/applications/${appId}/run`, { method: "POST" });
  $("timeline-output").textContent = pretty(data);
  toast(`Application status: ${data.status}.`);
  await loadTimeline();
}

async function loadTimeline() {
  const appId = $("application-id").value.trim();
  if (!appId) throw new Error("Select or enter an application id.");
  const data = await api(`/v1/applications/${appId}/timeline`);
  $("timeline-output").innerHTML = data.events?.length ? renderTimeline(data.events) : `<pre>${pretty(data)}</pre>`;
}

function renderTimeline(events) {
  return events.map((event) => `
    <div class="timeline-row">
      <div>
        <strong>${escapeHtml(event.kind)}</strong>
        <span>${escapeHtml(event.ts || "")}</span>
      </div>
      <p>${escapeHtml(event.event || event.to || event.evidence_kind || event.reason || "")}</p>
    </div>
  `).join("");
}

async function confirmSubmit() {
  const appId = $("application-id").value.trim();
  if (!appId) throw new Error("Select or enter an application id.");
  const data = await api(`/v1/applications/${appId}/confirm-submit`, {
    method: "POST",
    body: JSON.stringify({ confirmed_by: $("operator-id").value.trim() || "operator" }),
  });
  $("timeline-output").textContent = pretty(data);
  toast(`Submit confirmation handled: ${data.status}.`);
}

async function refreshObservability() {
  const seekerId = requireSeeker();
  const [pipeline, usage, metrics] = await Promise.all([
    api(`/v1/seekers/${seekerId}/pipeline`),
    api(`/v1/seekers/${seekerId}/usage?window=30d`),
    fetch("/metrics").then((r) => r.text()),
  ]);
  $("pipeline-output").textContent = pretty(pipeline);
  $("usage-output").textContent = `${pretty(usage)}\n\n${metrics}`;
}

async function refreshAll() {
  await refreshHealth();
  if (state.seekerId) {
    await Promise.allSettled([refreshProfile(), refreshMatches(), refreshObservability()]);
  }
}

function attach(id, fn) {
  $(id).addEventListener("click", async (event) => {
    setBusy(event.currentTarget, true);
    try {
      await fn(event);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setBusy(event.currentTarget, false);
    }
  });
}

function loadSample() {
  $("profile-json").value = pretty(sampleProfile);
  $("prefs-json").value = pretty(samplePrefs);
  $("free-text").value = "Customer-ready sample profile for Dana Levi.";
  toast("Sample candidate loaded.");
}

function boot() {
  $("profile-json").value = pretty(sampleProfile);
  $("prefs-json").value = pretty(samplePrefs);
  if (state.seekerId) setSeeker(state.seekerId);

  attach("refresh-btn", refreshAll);
  attach("sample-btn", loadSample);
  attach("create-seeker-btn", createSeeker);
  attach("intake-btn", runIntake);
  attach("profile-btn", refreshProfile);
  attach("resume-en-btn", () => buildResume("en"));
  attach("resume-he-btn", () => buildResume("he"));
  attach("discovery-btn", runDiscovery);
  attach("matching-btn", runMatching);
  attach("matches-btn", refreshMatches);
  attach("run-app-btn", runApplication);
  attach("timeline-btn", loadTimeline);
  attach("submit-btn", confirmSubmit);
  attach("observability-btn", refreshObservability);

  $("match-list").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    setBusy(button, true);
    try {
      const action = button.dataset.action;
      const id = button.dataset.id;
      if (action === "approve") await decide(id, "approved");
      if (action === "reject") await decide(id, "rejected");
      if (action === "handoff") await handoff(id);
      if (action === "select-app") {
        if (!id) throw new Error("No application id on this match yet.");
        $("application-id").value = id;
        toast("Application selected.");
      }
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  });

  refreshAll().catch((error) => toast(error.message, "error"));
}

boot();
