const state = {
  seekerId: "",
  selected: null,
  matches: [],
  health: null,
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
  $("active-seeker").textContent = id ? `${id.slice(0, 8)}…` : "None";
}

function requireSeeker() {
  if (!state.seekerId) throw new Error("Start a new loop and save the interpreted profile first.");
  return state.seekerId;
}

function parseJson(id) {
  const raw = $(id).value.trim();
  return raw ? JSON.parse(raw) : {};
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
  state.selected = null;
  state.matches = [];
  setSeeker("");
  $("selected-job").textContent = "None";
  $("match-count").textContent = "0";
  $("completeness").textContent = "0%";
  $("selected-card").textContent = "Select a job from the search results.";
  $("match-list").innerHTML = "";
  $("profile-output").textContent = "No interpreted profile yet.";
  $("tailor-output").textContent = "No tailored packet yet.";
  $("timeline-output").textContent = "No application run yet.";
  toast("New search loop ready.");
}

async function interpretCv() {
  const text = $("cv-text").value.trim();
  if (!text) throw new Error("Drop or paste a CV first.");
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
  const interpreted = interpretCvText(text);
  $("profile-json").value = pretty(interpreted.profile);
  $("prefs-json").value = pretty(interpreted.prefs);
  $("profile-output").textContent = "AI-interpreted draft created. Review and edit before saving.";
  location.hash = "#step-profile";
  toast("CV interpreted into editable profile.");
}

async function saveProfile() {
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
      profile_patch: parseJson("profile-json"),
      preferences_patch: parseJson("prefs-json"),
    }),
  });
  $("completeness").textContent = `${data.overall_completeness}%`;
  $("profile-output").textContent = pretty(data);
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
  const manualUrl = $("manual-url").value.trim();
  if (manualUrl) {
    await api("/v1/jobs/manual", {
      method: "POST",
      body: JSON.stringify({
        url: manualUrl,
        description_text: $("manual-description").value.trim() || null,
      }),
    });
  }
  const discoveryBody = {
    fixtures_dir: state.health?.production_mode ? null : $("fixtures-dir").value.trim() || null,
    greenhouse_orgs: splitList("greenhouse-orgs"),
    lever_orgs: splitList("lever-orgs"),
  };
  if (discoveryBody.fixtures_dir || discoveryBody.greenhouse_orgs.length || discoveryBody.lever_orgs.length) {
    await api("/v1/discovery/run", {
      method: "POST",
      body: JSON.stringify(discoveryBody),
    });
  }
  await api(`/v1/seekers/${seekerId}/match/run`, { method: "POST" });
  await refreshMatches();
  location.hash = "#step-search";
  toast("Search complete.");
}

function splitList(id) {
  return $(id).value.split(",").map((x) => x.trim()).filter(Boolean);
}

async function refreshMatches() {
  const seekerId = requireSeeker();
  state.matches = await api(`/v1/seekers/${seekerId}/matches`);
  $("match-count").textContent = String(state.matches.length);
  renderMatches();
}

function renderMatches() {
  const host = $("match-list");
  if (!state.matches.length) {
    host.innerHTML = "<p>No surfaced jobs yet.</p>";
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
  state.selected = state.matches.find((match) => match.match_id === matchId);
  if (!state.selected) throw new Error("Could not select job.");
  $("selected-job").textContent = `${state.selected.posting.company}`;
  $("selected-card").textContent = pretty(state.selected);
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
  await refreshMatches();
  state.selected = state.matches.find((match) => match.match_id === selected.match_id);
  $("selected-card").textContent = pretty(state.selected);
  toast("Selected job approved.");
}

async function tailorSelected() {
  const selected = requireSelected();
  if (selected.status !== "approved") await approveSelected();
  const current = state.matches.find((match) => match.match_id === selected.match_id) || selected;
  const app = await api(`/v1/applications/${current.application_id}/tailor`, { method: "POST" });
  $("tailor-output").textContent = pretty(app);
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
  await api(`/v1/applications/${selected.application_id}/preflight`, { method: "POST" });
  const app = await api(`/v1/applications/${selected.application_id}/run`, { method: "POST" });
  $("timeline-output").textContent = pretty(app);
  await loadTimeline();
  location.hash = "#step-apply";
  toast(`Application status: ${app.status}.`);
}

async function loadTimeline() {
  const selected = requireSelected();
  const data = await api(`/v1/applications/${selected.application_id}/timeline`);
  $("timeline-output").innerHTML = data.events?.length ? renderTimeline(data.events) : `<pre>${pretty(data)}</pre>`;
}

async function confirmSubmit() {
  const selected = requireSelected();
  const data = await api(`/v1/applications/${selected.application_id}/confirm-submit`, {
    method: "POST",
    body: JSON.stringify({ confirmed_by: "candidate-loop" }),
  });
  $("timeline-output").textContent = pretty(data);
  toast(`Submit gate handled: ${data.status}.`);
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
  refreshHealth().catch((error) => toast(error.message, "error"));
}

boot();
