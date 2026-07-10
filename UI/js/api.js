/**
 * Shared frontend helpers — calls the real FastAPI backend.
 *
 * Sprint 1 has no login yet, so we simulate "who's logged in" with a
 * simple dropdown. The chosen seeker ID is kept in localStorage so it
 * persists across pages. Swap this out for real auth in Sprint 3.
 */

const API_BASE = ""; // same-origin: FastAPI serves both the API and /UI/*

const TEST_SEEKERS = [
  { id: 1, label: "Seeker #1 — Aisha" },
  { id: 2, label: "Seeker #2 — Marcus" },
  { id: 3, label: "Seeker #3 — Priya" },
];

// Used to populate the state/region filter dropdown on Browse Jobs.
const MALAYSIA_STATES = [
  "Remote", "Kuala Lumpur", "Selangor", "Penang", "Johor", "Perak",
  "Negeri Sembilan", "Melaka", "Pahang", "Kedah", "Kelantan", "Terengganu",
  "Sabah", "Sarawak", "Perlis", "Putrajaya", "Labuan",
];

const JOB_TYPES = ["Full-time", "Part-time", "Contract", "Internship", "Remote"];

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

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
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
    throw new Error(body.detail || "Upload failed");
  }
  return res.json();
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
