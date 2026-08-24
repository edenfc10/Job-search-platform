const state = {
  seekerId: sessionStorage.getItem("aijaa.seekerId") || "",
  selectedMatchId: sessionStorage.getItem("aijaa.selectedMatchId") || "",
  selected: null,
  matches: [],
  health: null,
  searchStats: null,
  profileIssues: [],
};

const sampleCv = `Dana Levi
Tel Aviv, Israel | dana@example.com | +972-50-1234567
LinkedIn: https://linkedin.com/in/danalevi
GitHub: https://github.com/danalevi

Senior Backend Engineer with Python, FastAPI, PostgreSQL, Kubernetes, AWS, Docker, and Redis experience.

CloudWorks - Senior Backend Engineer - 2021-03 to Present - Tel Aviv
- Reduced API p95 latency by 40% by rearchitecting the caching layer in Python and Redis.
- Led a team of 5 engineers building FastAPI microservices on Kubernetes serving 2M users.

DataNest - Backend Engineer - 2018-06 to 2021-02
- Built ETL pipelines in Python and PostgreSQL processing 500GB daily.

Education: B.Sc. Computer Science, Tel Aviv University, 2018
Languages: English, Hebrew
Preferences: Senior Backend Engineer or Backend Engineer, Tel Aviv or Remote, minimum salary 30000 ILS, Israeli citizen, avoid gambling companies.`;

const $ = (id) => document.getElementById(id);

function pretty(value) {
  return JSON.stringify(value, null, 2);
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
  if (!res.ok) throw new Error(typeof body === "object" ? body.detail || pretty(body) : body);
  return body;
}

async function upload(path, formData) {
  const res = await fetch(path, { method: "POST", body: formData });
  const contentType = res.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error(typeof body === "object" ? body.detail || pretty(body) : body);
  return body;
}

function setBusy(button, busy) {
  button.disabled = busy;
}

function setSeeker(id) {
  state.seekerId = id;
  if (id) sessionStorage.setItem("aijaa.seekerId", id);
  else sessionStorage.removeItem("aijaa.seekerId");
  $("active-seeker").textContent = id ? `${id.slice(0, 8)}…` : "None";
}

function setSelected(match) {
  state.selected = match || null;
  state.selectedMatchId = match?.match_id || "";
  if (state.selectedMatchId) sessionStorage.setItem("aijaa.selectedMatchId", state.selectedMatchId);
  else sessionStorage.removeItem("aijaa.selectedMatchId");
  $("selected-job").textContent = match?.posting?.company || "None";
  $("selected-card").textContent = match ? pretty(match) : "Select a job from the search results.";
  updateActionButtons();
}

function profileProblems(profile, preferences) {
  const problems = [];
  const name = (profile?.contact?.full_name || "").trim().toLowerCase();
  const email = (profile?.contact?.email || "").trim().toLowerCase();
  const placeholderNames = new Set(["cv", "resume", "sample resume", "curriculum vitae"]);
  const placeholderEmails = new Set(["mail@email.com", "email@example.com"]);
  if (!name) problems.push("candidate full name");
  else if (placeholderNames.has(name)) problems.push("a real candidate name (not a CV heading)");
  if (!email) problems.push("candidate email");
  else if (placeholderEmails.has(email)) problems.push("a real candidate email");
  if (!profile?.work_history?.length) problems.push("at least one work-history entry");
  if (!profile?.skills?.length) problems.push("at least one verified skill");
  if (!preferences?.target_titles?.length) problems.push("at least one target title");
  return problems;
}

function showProfileProblems(problems) {
  state.profileIssues = problems;
  const box = $("profile-error");
  if (problems.length) {
    box.textContent = `Review required: ${problems.join(", ")}.`;
    box.classList.remove("hidden");
    box.classList.add("error");
  } else {
    box.classList.add("hidden");
    box.classList.remove("error");
  }
  updateActionButtons();
}

function updateActionButtons() {
  const selected = state.selected;
  const hasSelection = Boolean(selected);
  const approved = selected?.status === "approved";
  const appStatus = selected?.application_status || "";
  const hasApplication = Boolean(selected?.application_id);
  const profileReady = state.profileIssues.length === 0;
  $("approve-btn").disabled = !hasSelection || approved || !profileReady;
  $("tailor-btn").disabled = !hasSelection || !profileReady;
  $("handoff-btn").disabled = !hasSelection || !approved;
  $("apply-btn").disabled = !hasApplication || !approved || !profileReady || ["confirmed", "failed"].includes(appStatus);
  $("timeline-btn").disabled = !hasApplication;
  $("submit-btn").disabled = !hasApplication || appStatus !== "ready_to_submit" || !profileReady;
  $("approve-btn").textContent = approved ? "Job Approved" : "Approve Selected Job";
  $("apply-btn").textContent = appStatus === "ready_to_submit" ? "Rebuild Review" : "Fill Application";
}

function requireSeeker() {
  if (!state.seekerId) throw new Error("Start a new loop and save the interpreted profile first.");
  return state.seekerId;
}

function parseJson(id) {
  const raw = $(id).value.trim();
  const field = $(id);
  try {
    const value = raw ? JSON.parse(raw) : {};
    field.classList.remove("field-error");
    return value;
  } catch (error) {
    field.classList.add("field-error");
    throw new Error(`${id === "profile-json" ? "Candidate facts" : "Search preferences"} contains invalid JSON: ${error.message}`);
  }
}

async function refreshHealth() {
  const data = await api("/healthz");
  state.health = data;
  $("health-dot").className = "ok";
  $("health-status").textContent = data.production_ready ? "Ready" : "Needs configuration";
  $("health-detail").textContent = `${data.llm_mode} LLM · dry_run=${data.dry_run}`;
  $("dry-run").textContent = data.dry_run ? "Dry run on" : "Live submit enabled";
  renderReadiness(data);
  document.querySelectorAll(".demo-only").forEach((el) => {
    el.classList.toggle("hidden", Boolean(data.production_mode));
  });
  if (data.production_mode) $("fixtures-dir").value = "";
  $("greenhouse-orgs").value = (data.configured_greenhouse_orgs || []).join(", ");
  $("lever-orgs").value = (data.configured_lever_orgs || []).join(", ");
}

function renderReadiness(data) {
  $("production-mode").textContent = data.production_mode ? "Production mode" : "Demo mode";
  $("readiness-title").textContent = data.production_ready ? "Operationally ready" : "Configuration required";
  $("readiness-copy").textContent = data.production_mode
    ? "Production mode uses real OpenAI calls and real sources only."
    : "Demo mode allows fixtures and sample data. Enable production mode for customer operation.";
  const checks = [
    ["OpenAI provider", data.llm_mode === "openai" || !data.production_mode],
    ["OpenAI API key", !data.missing_requirements?.includes("AIJAA_OPENAI_API_KEY")],
    ["Real job source", !(data.missing_requirements || []).some((x) => x.startsWith("at least one real source"))],
    ["Playwright apply driver", data.apply_driver === "playwright" || !data.production_mode],
    ["Dry-run supervised launch", data.dry_run],
  ];
  $("readiness-list").innerHTML = checks.map(([label, ok]) => `
    <div class="check-item ${ok ? "" : "missing"}">
      <strong>${ok ? "OK" : "Missing"}</strong>
      <span>${escapeHtml(label)}</span>
    </div>
  `).join("");
}

function interpretCvText(text) {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const fullName = lines[0] || "";
  const email = text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)?.[0] || "";
  const phone = text.match(/(?:\+?\d[\d\s().-]{7,}\d)/)?.[0] || "";
  const links = [...text.matchAll(/https?:\/\/\S+/g)].map((m) => m[0].replace(/[),.]$/, ""));
  const skills = inferSkills(text);
  const roles = inferRoles(text);
  const achievements = lines
    .filter((line) => /^[-•]/.test(line) || /\d/.test(line))
    .slice(0, 6)
    .map((line, index) => ({
      fact_id: `cv_f${index + 1}`,
      text: line.replace(/^[-•]\s*/, ""),
      kind: "achievement",
      quantified: /\d/.test(line),
    }));
  const companyLine = lines.find((line) => /\b(engineer|manager|designer|developer|analyst)\b/i.test(line)) || "";
  const title = roles[0] || "Professional";
  const location = /tel aviv/i.test(text) ? "Tel Aviv, Israel" : "";
  const educationLine = lines.find((line) => /university|college|b\.sc|m\.sc|ba|ma|degree/i.test(line));

  return {
    profile: {
      contact: { full_name: fullName, email, phone, location, links },
      work_history: [
        {
          company: inferCompany(companyLine) || "Most recent company",
          title,
          start: inferStart(companyLine) || "2021-01",
          end: /present/i.test(companyLine + text.slice(0, 500)) ? null : undefined,
          location: location || undefined,
          achievements: achievements.length ? achievements : [{
            fact_id: "cv_f1",
            text: "Candidate CV content needs review before tailoring.",
            kind: "achievement",
            quantified: false,
          }],
        },
      ],
      education: educationLine ? [{ institution: educationLine, degree: "", field: "", year: inferYear(educationLine) }] : [],
      skills: skills.map((skill, index) => ({ fact_id: `cv_s${index + 1}`, text: skill, kind: "skill" })),
      languages: /hebrew/i.test(text) ? ["English", "Hebrew"] : ["English"],
      summary_notes: text.slice(0, 1800),
    },
    prefs: {
      target_titles: roles.length ? roles : [title],
      seniority: /staff|principal/i.test(text) ? "staff" : /senior|lead/i.test(text) ? "senior" : null,
      industries: inferIndustries(text),
      locations: location ? [location, "Remote"] : ["Remote"],
      remote_policy: /remote/i.test(text) ? "remote" : "hybrid",
      min_salary: Number(text.match(/(?:minimum salary|min salary|salary)\D{0,20}(\d{4,6})/i)?.[1] || 0) || null,
      currency: /ils|₪/i.test(text) ? "ILS" : "USD",
      work_authorization: /citizen|authorized|work authorization/i.test(text) ? "Work authorization stated in CV" : null,
      dealbreakers: /gambling/i.test(text) ? ["gambling"] : [],
      resume_languages: /hebrew/i.test(text) ? ["en", "he"] : ["en"],
    },
  };
}

function inferSkills(text) {
  const vocab = ["Python", "FastAPI", "PostgreSQL", "Kubernetes", "AWS", "Docker", "Redis", "React", "TypeScript", "JavaScript", "Node", "SQL", "ETL", "Kafka", "GCP", "Azure", "Figma", "Tableau", "Excel"];
  return vocab.filter((skill) => new RegExp(`\\b${skill.replace("+", "\\+")}\\b`, "i").test(text)).slice(0, 14);
}

function inferRoles(text) {
  const roles = [...text.matchAll(/\b(?:Senior |Staff |Lead |Principal )?(?:Backend|Frontend|Full Stack|Software|Data|Platform|DevOps|Product|UX|UI)?\s?(?:Engineer|Developer|Designer|Manager|Analyst)\b/gi)]
    .map((m) => m[0].replace(/\s+/g, " ").trim())
    .filter((role) => role.length > 4);
  return [...new Set(roles)].slice(0, 4);
}

function inferIndustries(text) {
  if (/saas|cloud/i.test(text)) return ["SaaS", "Cloud"];
  if (/finance|bank|fintech/i.test(text)) return ["Fintech"];
  if (/health|medical/i.test(text)) return ["Healthcare"];
  return [];
}

function inferCompany(line) {
  const parts = line.split(/\s[-–]\s/);
  return parts.length > 1 ? parts[0].trim() : "";
}

function inferStart(line) {
  return line.match(/\b(20\d{2}|19\d{2})(?:[-/](0[1-9]|1[0-2]))?/)?.[0]?.replace("/", "-");
}

function inferYear(line) {
  return line.match(/\b(20\d{2}|19\d{2})\b/)?.[0] || null;
}

async function startNewLoop() {
  setSelected(null);
  state.matches = [];
  state.searchStats = null;
  state.profileIssues = [];
  setSeeker("");
  $("selected-job").textContent = "None";
  $("match-count").textContent = "0";
  $("completeness").textContent = "0%";
  $("selected-card").textContent = "Select a job from the search results.";
  $("match-list").innerHTML = "";
  $("search-summary").classList.add("hidden");
  $("search-summary").textContent = "";
  $("profile-error").classList.add("hidden");
  $("cv-text").value = "";
  $("cv-file").value = "";
  $("cv-file-status").textContent = "No file selected.";
  $("profile-json").value = "";
  $("prefs-json").value = "";
  $("profile-output").textContent = "No interpreted profile yet.";
  $("tailor-output").textContent = "No tailored packet yet.";
  $("timeline-output").textContent = "No application run yet.";
  updateActionButtons();
  toast("New search loop ready.");
}

async function interpretCv() {
  const text = $("cv-text").value.trim();
  if (!text) throw new Error("Drop or paste a CV first.");
  if (!state.health) throw new Error("The API is still connecting. Try again in a moment.");
  if (state.health?.production_mode) {
    let seekerId = state.seekerId;
    if (!seekerId) {
      const created = await api("/v1/seekers", {
        method: "POST",
        body: JSON.stringify({
          external_ref: `search-loop-${Date.now()}`,
          consent_recorded_at: new Date().toISOString(),
        }),
      });
      seekerId = created.seeker_id;
      setSeeker(seekerId);
    }
    await api(`/v1/seekers/${seekerId}/intake/turns`, {
      method: "POST",
      body: JSON.stringify({ free_text: text }),
    });
    const profile = await api(`/v1/seekers/${seekerId}/profile`);
    $("profile-json").value = pretty(profile.profile);
    $("prefs-json").value = pretty(profile.preferences);
    $("completeness").textContent = `${profile.completeness.overall}%`;
    $("profile-output").textContent = pretty(profile);
    location.hash = "#step-profile";
    toast("OpenAI interpreted the CV into an editable profile.");
    return;
  }
  const interpreted = await api("/v1/cv/interpret", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  $("profile-json").value = pretty(interpreted.profile_patch);
  $("prefs-json").value = pretty(interpreted.preferences_patch);
  const warnings = interpreted.warnings || [];
  $("profile-output").textContent = warnings.length
    ? `Draft created. Review before saving.\n\nWarnings:\n- ${warnings.join("\n- ")}`
    : "Draft created. Review and edit before saving.";
  location.hash = "#step-profile";
  toast("CV interpreted into an editable profile draft.");
}

async function saveProfile() {
  const errorBox = $("profile-error");
  errorBox.classList.add("hidden");
  errorBox.classList.remove("error");
  const profilePatch = parseJson("profile-json");
  const preferencesPatch = parseJson("prefs-json");
  const missing = profileProblems(profilePatch, preferencesPatch);
  if (missing.length) {
    showProfileProblems(missing);
    throw new Error(errorBox.textContent);
  }
  let seekerId = state.seekerId;
  if (!seekerId) {
    const created = await api("/v1/seekers", {
      method: "POST",
      body: JSON.stringify({ external_ref: `search-loop-${Date.now()}`, consent_recorded_at: new Date().toISOString() }),
    });
    seekerId = created.seeker_id;
    setSeeker(seekerId);
  }
  const data = await api(`/v1/seekers/${seekerId}/intake/turns`, {
    method: "POST",
    body: JSON.stringify({
      free_text: $("cv-text").value,
      profile_patch: profilePatch,
      preferences_patch: preferencesPatch,
    }),
  });
  $("completeness").textContent = `${data.overall_completeness}%`;
  $("profile-output").textContent = pretty(data);
  showProfileProblems([]);
  toast("Editable profile saved.");
}

async function buildMasterFiles() {
  const seekerId = requireSeeker();
  const prefs = parseJson("prefs-json");
  const langs = prefs.resume_languages?.length ? prefs.resume_languages : ["en"];
  const docs = [];
  for (const language of langs) {
    docs.push(await api(`/v1/seekers/${seekerId}/resume`, {
      method: "POST",
      body: JSON.stringify({ language }),
    }));
  }
  $("profile-output").textContent = pretty(docs);
  toast("Master CV files generated.");
}

async function searchJobs() {
  const seekerId = requireSeeker();
  if (!state.health) throw new Error("The API is still connecting. Try again in a moment.");
  const manualUrl = $("manual-url").value.trim();
  const fixtureDir = state.health.production_mode ? "" : $("fixtures-dir").value.trim();
  const greenhouseOrgs = splitList("greenhouse-orgs");
  const leverOrgs = splitList("lever-orgs");
  if (!fixtureDir && !greenhouseOrgs.length && !leverOrgs.length && !manualUrl) {
    throw new Error("Configure at least one job source: fixture, Greenhouse, Lever, or a manual job URL.");
  }
  if (manualUrl) {
    await api("/v1/jobs/manual", {
      method: "POST",
      body: JSON.stringify({
        url: manualUrl,
        title: $("manual-title").value.trim() || null,
        company: $("manual-company").value.trim() || null,
        location: $("manual-location").value.trim() || null,
        description_text: $("manual-description").value.trim() || null,
      }),
    });
  }
  const discoveryBody = {
    fixtures_dir: fixtureDir || null,
    greenhouse_orgs: greenhouseOrgs,
    lever_orgs: leverOrgs,
  };
  let discoveryStats = null;
  if (discoveryBody.fixtures_dir || discoveryBody.greenhouse_orgs.length || discoveryBody.lever_orgs.length) {
    discoveryStats = await api("/v1/discovery/run", {
      method: "POST",
      body: JSON.stringify(discoveryBody),
    });
  }
  const matchingStats = await api(`/v1/seekers/${seekerId}/match/run`, { method: "POST" });
  state.searchStats = { discovery: discoveryStats, matching: matchingStats };
  renderSearchSummary();
  await refreshMatches();
  location.hash = "#step-search";
  toast("Search complete.");
}

function renderSearchSummary() {
  const host = $("search-summary");
  const discovery = state.searchStats?.discovery;
  const matching = state.searchStats?.matching;
  if (!matching) {
    host.classList.add("hidden");
    return;
  }
  const pieces = [];
  if (discovery) {
    pieces.push(`${discovery.fetched} fetched`);
    pieces.push(`${discovery.stale_dropped} stale`);
    pieces.push(`${discovery.created} new`);
  }
  pieces.push(`${matching.jobs_considered ?? matching.candidates_after_filters} considered`);
  pieces.push(`${matching.hard_filtered ?? 0} filtered`);
  pieces.push(`${matching.candidates_after_filters} eligible`);
  pieces.push(`${matching.matches_created} surfaced`);
  pieces.push(`${matching.withheld_below_floor} below score ${matching.match_floor ?? 70}`);
  let explanation = "Search completed.";
  if (discovery?.fetched && discovery.stale_dropped === discovery.fetched) {
    explanation = "Jobs were found, but all were older than the configured freshness window.";
  } else if (!matching.candidates_after_filters) {
    explanation = "No jobs remained after freshness, location, salary, and dealbreaker filters.";
  } else if (!matching.matches_created && matching.withheld_below_floor) {
    explanation = `Jobs were evaluated, but every score was below the minimum match score of ${matching.match_floor ?? 70}.`;
  }
  host.innerHTML = `<strong>${escapeHtml(explanation)}</strong><br>${escapeHtml(pieces.join(" · "))}`;
  host.classList.remove("hidden");
}

function splitList(id) {
  return $(id).value.split(",").map((x) => x.trim()).filter(Boolean);
}

async function refreshMatches() {
  const seekerId = requireSeeker();
  state.matches = await api(`/v1/seekers/${seekerId}/matches`);
  $("match-count").textContent = String(state.matches.length);
  const remembered = state.matches.find((match) => match.match_id === state.selectedMatchId);
  if (remembered) setSelected(remembered);
  else if (state.selectedMatchId) setSelected(null);
  renderMatches();
  updateActionButtons();
}

async function refreshSelected(matchId) {
  await refreshMatches();
  setSelected(state.matches.find((match) => match.match_id === matchId) || null);
  renderMatches();
  return state.selected;
}

function renderMatches() {
  const host = $("match-list");
  if (!state.matches.length) {
    host.innerHTML = `<p>${state.searchStats ? "No jobs passed the match threshold. See the search summary above." : "No search has been completed yet."}</p>`;
    return;
  }
  host.innerHTML = "";
  for (const match of state.matches) {
    const selected = state.selected?.match_id === match.match_id;
    const risks = (match.risks || []).map((risk) => `<span class="pill">${escapeHtml(risk)}</span>`).join(" ");
    const card = document.createElement("article");
    card.className = `job-card ${selected ? "selected" : ""}`;
    card.innerHTML = `
      <div>
        <div class="job-title">
          <span class="score">${match.score}</span>
          <strong>${escapeHtml(match.posting?.company || "Unknown")}</strong>
          <span>${escapeHtml(match.posting?.title || "Untitled role")}</span>
          <span class="pill">${escapeHtml(match.status)}</span>
          <span class="pill">${escapeHtml(match.application_status || "not started")}</span>
        </div>
        <p>${escapeHtml(match.rationale || "")}</p>
        <div>${risks}</div>
      </div>
      <div class="job-actions">
        <button class="primary" data-action="select" data-id="${match.match_id}">Select Job</button>
      </div>
    `;
    host.appendChild(card);
  }
}

function selectMatch(matchId) {
  const selected = state.matches.find((match) => match.match_id === matchId);
  if (!selected) throw new Error("Could not select job.");
  setSelected(selected);
  renderMatches();
  location.hash = "#step-tailor";
}

async function approveSelected() {
  const selected = requireSelected();
  if (selected.status !== "approved") {
    await api(`/v1/matches/${selected.match_id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision: "approved", decided_by: "candidate-loop" }),
    });
  }
  await refreshSelected(selected.match_id);
  toast("Selected job approved.");
}

async function tailorSelected() {
  const selected = requireSelected();
  if (selected.status !== "approved") await approveSelected();
  const current = state.matches.find((match) => match.match_id === selected.match_id) || selected;
  const app = await api(`/v1/applications/${current.application_id}/tailor`, { method: "POST" });
  $("tailor-output").textContent = pretty(app);
  await refreshSelected(selected.match_id);
  toast("Tailored CV files created.");
}

async function viewHandoff() {
  const selected = requireSelected();
  const packet = await api(`/v1/matches/${selected.match_id}/handoff`);
  $("tailor-output").textContent = pretty(packet);
  toast("Tailored packet loaded.");
}

async function applySelected() {
  const selected = requireSelected();
  try {
    // /run already performs tailor (if needed), analysis, and guarded filling.
    // Calling /preflight first duplicated navigation and failed when local ports changed.
    const app = await api(`/v1/applications/${selected.application_id}/run`, { method: "POST" });
    $("timeline-output").textContent = pretty(app);
    await refreshSelected(selected.match_id);
    await loadTimeline();
    location.hash = "#step-apply";
    toast(`Application status: ${app.status}.`);
  } catch (error) {
    $("timeline-output").textContent = `Application preparation failed:\n${error.message}`;
    location.hash = "#step-apply";
    throw error;
  }
}

async function loadTimeline() {
  const selected = requireSelected();
  const data = await api(`/v1/applications/${selected.application_id}/timeline`);
  $("timeline-output").innerHTML = data.events?.length ? renderTimeline(data.events) : `<pre>${pretty(data)}</pre>`;
}

async function confirmSubmit() {
  const selected = requireSelected();
  const label = `${selected.posting?.title || "job"} at ${selected.posting?.company || "company"}`;
  const dryRunNote = state.health?.dry_run ? "\n\nDRY_RUN is on: no external submit click will occur." : "";
  if (!window.confirm(`Confirm the reviewed application for ${label}?${dryRunNote}`)) return;
  const data = await api(`/v1/applications/${selected.application_id}/confirm-submit`, {
    method: "POST",
    body: JSON.stringify({ confirmed_by: "candidate-loop" }),
  });
  await refreshSelected(selected.match_id);
  await loadTimeline();
  if (state.health?.dry_run) {
    toast(`Dry run recorded. Nothing was submitted; status remains ${data.status}.`);
  } else {
    toast(`Submit gate handled: ${data.status}.`);
  }
}

async function restoreSession() {
  if (!state.seekerId) {
    updateActionButtons();
    return;
  }
  try {
    const data = await api(`/v1/seekers/${state.seekerId}/profile`);
    $("profile-json").value = pretty(data.profile);
    $("prefs-json").value = pretty(data.preferences);
    $("completeness").textContent = `${data.completeness?.overall ?? 0}%`;
    $("profile-output").textContent = "Saved profile restored from the API.";
    showProfileProblems(profileProblems(data.profile, data.preferences));
    await refreshMatches();
  } catch (error) {
    setSelected(null);
    setSeeker("");
    toast(`Saved session could not be restored: ${error.message}`, "error");
  }
}

function requireSelected() {
  if (!state.selected) throw new Error("Select a job first.");
  return state.selected;
}

function renderTimeline(events) {
  return events.map((event) => `
    <div class="timeline-row">
      <div><strong>${escapeHtml(event.kind)}</strong><span>${escapeHtml(event.ts || "")}</span></div>
      <p>${escapeHtml(event.event || event.to || event.evidence_kind || event.reason || "")}</p>
      ${event.value ? `<pre>${escapeHtml(event.value)}</pre>` : ""}
    </div>
  `).join("");
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

function attach(id, fn) {
  $(id).addEventListener("click", async (event) => {
    setBusy(event.currentTarget, true);
    try {
      await fn(event);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setBusy(event.currentTarget, false);
      updateActionButtons();
    }
  });
}

function setupDropzone() {
  const zone = $("dropzone");
  const input = $("cv-file");
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      await loadCvFile(file);
    } catch (error) {
      toast(error.message, "error");
    }
  });
  for (const eventName of ["dragenter", "dragover"]) {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.add("drag");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.remove("drag");
    });
  }
  zone.addEventListener("drop", async (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    input.files = event.dataTransfer.files;
    try {
      await loadCvFile(file);
    } catch (error) {
      toast(error.message, "error");
    }
  });
}

async function loadCvFile(file) {
  $("cv-file-status").textContent = `Reading ${file.name}…`;
  const form = new FormData();
  form.append("file", file);
  const parsed = await upload("/v1/cv/parse", form);
  $("cv-text").value = parsed.text;
  $("cv-file-status").textContent = `${parsed.filename} · ${parsed.characters.toLocaleString()} characters extracted`;
  toast(`Loaded ${parsed.filename}.`);
}

function boot() {
  setSeeker(state.seekerId);
  setupDropzone();
  attach("new-loop-btn", startNewLoop);
  attach("sample-btn", () => {
    $("cv-text").value = sampleCv;
    toast("Sample CV loaded.");
  });
  attach("interpret-btn", interpretCv);
  attach("save-profile-btn", saveProfile);
  attach("build-master-btn", buildMasterFiles);
  attach("search-btn", searchJobs);
  attach("refresh-matches-btn", refreshMatches);
  attach("approve-btn", approveSelected);
  attach("tailor-btn", tailorSelected);
  attach("handoff-btn", viewHandoff);
  attach("apply-btn", applySelected);
  attach("timeline-btn", loadTimeline);
  attach("submit-btn", confirmSubmit);
  $("match-list").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action='select']");
    if (button) selectMatch(button.dataset.id);
  });
  updateActionButtons();
  refreshHealth()
    .then(restoreSession)
    .catch((error) => toast(error.message, "error"));
}

boot();
