/**
 * Shared frontend helpers — calls the real FastAPI backend.
 */

const API_BASE = ""; // same-origin: FastAPI serves both the API and /UI/*

const TEST_SEEKERS = [
  { id: 1, label: "Seeker #1 — Aisha" },
  { id: 2, label: "Seeker #2 — Marcus" },
  { id: 3, label: "Seeker #3 — Priya" },
];

// Mirrors TEST_SEEKERS but for the employer side (job_management,
// employer_applications, applicant_detail). Job.employer_id in the DB
// ranges 1-3 across seeded jobs, so this needs at least that many
// entries or some employers' postings/applications become unreachable
// from the UI no matter who's "acting as" who.
const TEST_EMPLOYERS = [
  { id: 1, label: "Employer #1 — ABC Technologies" },
  { id: 2, label: "Employer #2 — Nova Digital" },
  { id: 3, label: "Employer #3 — Everest Analytics" },
];

// Used to populate the state/region filter dropdown on Browse Jobs.
const MALAYSIA_STATES = [
  "Remote", "Kuala Lumpur", "Selangor", "Penang", "Johor", "Perak",
  "Negeri Sembilan", "Melaka", "Pahang", "Kedah", "Kelantan", "Terengganu",
  "Sabah", "Sarawak", "Perlis", "Putrajaya", "Labuan",
];

const JOB_TYPES = ["Full-time", "Part-time", "Contract", "Internship", "Remote"];

// ---------------------------------------------------------------------------
// Profile form dropdown option lists. These must stay in sync with the
// canonical lists in src/job_portal/schemas.py (EDUCATION_LEVELS /
// FIELDS_OF_STUDY / month abbreviations) — the backend is the source of
// truth for what's actually accepted; these mirror it for the UI.
// ---------------------------------------------------------------------------

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const EDUCATION_LEVELS = [
  "SPM / High School",
  "STPM / A-Level / Foundation",
  "Certificate",
  "Diploma",
  "Bachelor's Degree",
  "Master's Degree",
  "PhD / Doctorate",
  "Professional Certification",
];

const FIELDS_OF_STUDY = [
  "Computer Science", "Information Technology", "Software Engineering",
  "Data Science", "Business Administration", "Accounting", "Finance",
  "Marketing", "Economics", "Mechanical Engineering", "Electrical Engineering",
  "Civil Engineering", "Psychology", "Communications", "Law", "Medicine",
  "Nursing", "Education", "Hospitality & Tourism", "Design", "Architecture",
  "Mathematics", "Other",
];

/** Build <option> markup for a month dropdown, with a blank leading placeholder. */
function monthOptionsHtml(selected = "") {
  const opts = MONTH_NAMES.map(
    (m) => `<option value="${m}" ${m === selected ? "selected" : ""}>${m}</option>`
  ).join("");
  return `<option value="">Month</option>${opts}`;
}

/** Build <option> markup for a year dropdown (descending, most recent first). */
function yearOptionsHtml(selected = "", fromYear = 1970, toYear = new Date().getFullYear() + 1) {
  let opts = "";
  for (let y = toYear; y >= fromYear; y--) {
    opts += `<option value="${y}" ${String(y) === String(selected) ? "selected" : ""}>${y}</option>`;
  }
  return `<option value="">Year</option>${opts}`;
}

/** Build <option> markup for a plain dropdown from a list of allowed values. */
function dropdownOptionsHtml(options, selected = "", placeholder = "Select…") {
  const opts = options.map(
    (o) => `<option value="${o}" ${o === selected ? "selected" : ""}>${o}</option>`
  ).join("");
  return `<option value="">${placeholder}</option>${opts}`;
}

/** Split a "MMM YYYY" or bare "YYYY" date string into { month, year } for populating selects. */
function splitDateString(value) {
  const trimmed = (value || "").trim();
  if (!trimmed) return { month: "", year: "" };
  const parts = trimmed.split(/\s+/);
  if (parts.length === 2 && MONTH_NAMES.includes(parts[0])) {
    return { month: parts[0], year: parts[1] };
  }
  return { month: "", year: trimmed };
}

/** Combine month + year select values back into the canonical date string ("MMM YYYY" or "YYYY", or ""). */
function combineDateSelects(month, year) {
  if (!year) return "";
  return month ? `${month} ${year}` : year;
}

function formatSalary(min, max) {
  if (min == null && max == null) return "Salary not specified";
  const fmt = (n) => `RM${n.toLocaleString()}`;
  if (min != null && max != null) return `${fmt(min)} – ${fmt(max)} / month`;
  if (min != null) return `From ${fmt(min)} / month`;
  return `Up to ${fmt(max)} / month`;
}

function getCurrentSeekerId() {
  return Number(localStorage.getItem("currentSeekerId") || TEST_SEEKERS[0].id);
}

function setCurrentSeekerId(id) {
  localStorage.setItem("currentSeekerId", id);
}

function renderDevUserBar(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const current = getCurrentSeekerId();
  const options = TEST_SEEKERS.map(
    (s) => `<option value="${s.id}" ${s.id === current ? "selected" : ""}>${s.label}</option>`
  ).join("");

  container.innerHTML = `
    Acting as:
    <select id="devUserSelect">${options}</select>
    <span style="opacity:0.75">(Sprint 1 stand-in for login — real auth arrives Sprint 3)</span>
  `;

  document.getElementById("devUserSelect").addEventListener("change", (e) => {
    setCurrentSeekerId(e.target.value);
    location.reload();
  });
}

function getCurrentEmployerId() {
  return Number(localStorage.getItem("currentEmployerId") || TEST_EMPLOYERS[0].id);
}

function setCurrentEmployerId(id) {
  localStorage.setItem("currentEmployerId", id);
}

// Employer-side equivalent of renderDevUserBar. Use this instead on
// employer-facing pages (job_management, employer_applications,
// applicant_detail) so "acting as" actually changes which employer_id
// is queried, instead of every page being stuck on a hardcoded id.
function renderDevEmployerBar(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const current = getCurrentEmployerId();
  const options = TEST_EMPLOYERS.map(
    (e) => `<option value="${e.id}" ${e.id === current ? "selected" : ""}>${e.label}</option>`
  ).join("");

  container.innerHTML = `
    Acting as:
    <select id="devEmployerSelect">${options}</select>
    <span style="opacity:0.75">(Sprint 1 stand-in for login — real auth arrives Sprint 3)</span>
  `;

  document.getElementById("devEmployerSelect").addEventListener("change", (e) => {
    setCurrentEmployerId(e.target.value);
    location.reload();
  });
}

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body.detail) {
        // FastAPI returns a plain string for HTTPException, but a LIST of
        // {msg, loc, ...} objects for pydantic validation errors (422s).
        // Handle both so callers always get a readable string, never
        // "[object Object]".
        detail = Array.isArray(body.detail)
          ? body.detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
          : body.detail;
      }
    } catch (_) {}
    throw new Error(detail);
  }
  // DELETE endpoints (like employer job deletion) return 204 No Content —
  // res.json() would throw on the empty body, so short-circuit here.
  if (res.status === 204) return null;
  return res.json();
}

function fetchJobs({ keyword = "", location = "", state = "", jobType = "", salaryMin = "", salaryMax = "" } = {}) {
  const params = new URLSearchParams();
  if (keyword) params.set("keyword", keyword);
  if (location) params.set("location", location);
  if (state) params.set("state", state);
  if (jobType) params.set("job_type", jobType);
  if (salaryMin) params.set("salary_min", salaryMin);
  if (salaryMax) params.set("salary_max", salaryMax);
  const query = params.toString();
  return apiFetch(`/api/jobs${query ? `?${query}` : ""}`);
}

function fetchRecommendedJobs(seekerId) {
  return apiFetch(`/api/jobs/recommended?seeker_id=${seekerId}`);
}

function fetchJob(jobId) {
  return apiFetch(`/api/jobs/${jobId}`);
}

function fetchSeekerProfile(seekerId) {
  return apiFetch(`/api/seekers/${seekerId}`);
}

function updateProfileInfo(seekerId, info) {
  return apiFetch(`/api/seekers/${seekerId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(info),
  });
}

function updateSeekerSkills(seekerId, skills) {
  return apiFetch(`/api/seekers/${seekerId}/skills`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skills }),
  });
}

function addExperience(seekerId, entry) {
  return apiFetch(`/api/seekers/${seekerId}/experience`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  });
}

function deleteExperience(seekerId, experienceId) {
  return apiFetch(`/api/seekers/${seekerId}/experience/${experienceId}`, { method: "DELETE" });
}

function addEducation(seekerId, entry) {
  return apiFetch(`/api/seekers/${seekerId}/education`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  });
}

function deleteEducation(seekerId, educationId) {
  return apiFetch(`/api/seekers/${seekerId}/education/${educationId}`, { method: "DELETE" });
}

async function uploadResume(seekerId, file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/seekers/${seekerId}/resume`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = Array.isArray(body.detail)
      ? body.detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
      : body.detail;
    throw new Error(detail || "Upload failed");
  }
  return res.json();
}

function scanResume(seekerId) {
  return apiFetch(`/api/seekers/${seekerId}/resume/parse`);
}

// ---------------------------------------------------------------------------
// Employer job management (job_management.html)
// ---------------------------------------------------------------------------

function fetchEmployerJobs(employerId, { keyword = "", status = "" } = {}) {
  const params = new URLSearchParams({ employer_id: employerId });
  if (keyword) params.set("keyword", keyword);
  if (status && status !== "all") params.set("status", status);
  return apiFetch(`/api/employer/jobs?${params.toString()}`);
}

function createEmployerJob(employerId, payload) {
  return apiFetch(`/api/employer/jobs?employer_id=${employerId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function updateEmployerJob(employerId, jobId, payload) {
  return apiFetch(`/api/employer/jobs/${jobId}?employer_id=${employerId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function publishEmployerJob(employerId, jobId) {
  return apiFetch(`/api/employer/jobs/${jobId}/publish?employer_id=${employerId}`, {
    method: "POST",
  });
}

function closeEmployerJob(employerId, jobId) {
  return apiFetch(`/api/employer/jobs/${jobId}/close?employer_id=${employerId}`, {
    method: "POST",
  });
}

function deleteEmployerJob(employerId, jobId) {
  return apiFetch(`/api/employer/jobs/${jobId}?employer_id=${employerId}`, {
    method: "DELETE",
  });
}

function trustSealHtml(score) {
  const safeScore = score == null ? "—" : score;
  const lowClass = score != null && score < 50 ? "low" : "";
  return `
    <div class="trust-seal ${lowClass}" title="Credibility score">
      <div class="score">${safeScore}</div>
      <div class="label">Trust</div>
    </div>
  `;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}