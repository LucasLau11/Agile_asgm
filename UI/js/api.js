/**
 * Shared frontend helpers — calls the real FastAPI backend.
 */

const API_BASE = ""; // same-origin: FastAPI serves both the API and /UI/*
const DEFAULT_PROFILE_IMAGE_URL = "/UI/assets/default-profile.png";

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
  const res = await fetch(`${API_BASE}${path}`, { credentials: "include", ...options });
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

function fetchJobs({ keyword = "", location = "", state = "", jobType = "", salaryMin = "", seekerId = "", sortBy = "" } = {}) {
  const params = new URLSearchParams();
  if (keyword) params.set("keyword", keyword);
  if (location) params.set("location", location);
  if (state) params.set("state", state);
  if (jobType) params.set("job_type", jobType);
  if (salaryMin) params.set("salary_min", salaryMin);
  if (seekerId) params.set("seeker_id", seekerId);
  if (sortBy) params.set("sort_by", sortBy);
  const query = params.toString();
  return apiFetch(`/api/jobs${query ? `?${query}` : ""}`);
}

function fetchRecommendedJobs(seekerId) {
  return apiFetch(`/api/jobs/recommended?seeker_id=${seekerId}`);
}

function fetchJob(jobId, seekerId) {
  const query = seekerId ? `?seeker_id=${seekerId}` : "";
  return apiFetch(`/api/jobs/${jobId}${query}`);
}

function fetchCompanyDetail(employerId) {
  return apiFetch(`/api/companies/${employerId}`);
}

function fetchSeekerProfile() {
  return apiFetch(`/api/seekers/me`);
}

function updateProfileInfo(info) {
  return apiFetch(`/api/seekers/me`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(info),
  });
}

function updateSeekerSkills(skills) {
  return apiFetch(`/api/seekers/me/skills`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skills }),
  });
}

function addExperience(entry) {
  return apiFetch(`/api/seekers/me/experience`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  });
}

function deleteExperience(experienceId) {
  return apiFetch(`/api/seekers/me/experience/${experienceId}`, { method: "DELETE" });
}

function addEducation(entry) {
  return apiFetch(`/api/seekers/me/education`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  });
}

function deleteEducation(educationId) {
  return apiFetch(`/api/seekers/me/education/${educationId}`, { method: "DELETE" });
}

async function uploadResume(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/seekers/me/resume`, {
    method: "POST",
    credentials: "include",
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

async function uploadProfilePicture(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/seekers/me/profile-picture`, {
    method: "POST",
    credentials: "include",
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

function scanResume() {
  return apiFetch(`/api/seekers/me/resume/parse`);
}

// ---------------------------------------------------------------------------
// Employer company profile (employer_profile.html) — US-05
// ---------------------------------------------------------------------------

function fetchEmployerProfile() {
  return apiFetch(`/api/employers/me`);
}

function updateEmployerProfile(info) {
  return apiFetch(`/api/employers/me`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(info),
  });
}

// ---------------------------------------------------------------------------
// Admin moderation (admin_dashboard.html) — US-07/08/09
// ---------------------------------------------------------------------------

function fetchAdminSeekers() {
  return apiFetch(`/api/admin/seekers`);
}

function fetchAdminEmployers(search = "", verificationStatus = "") {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (verificationStatus) params.set("verification_status", verificationStatus);
  const query = params.toString();
  return apiFetch(`/api/admin/employers${query ? `?${query}` : ""}`);
}

function fetchAdminStatistics() { return apiFetch(`/api/admin/statistics`); }
function fetchPendingEmployerVerifications() { return apiFetch(`/api/admin/employers/pending`); }
function fetchAdminEmployerDetail(id) { return apiFetch(`/api/admin/employers/${id}`); }
function approveEmployerVerification(id) {
  return apiFetch(`/api/admin/employers/${id}/approve`, { method: "POST" });
}
function rejectEmployerVerification(id, reason) {
  return apiFetch(`/api/admin/employers/${id}/reject`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }),
  });
}
function employerVerificationDocumentUrl(id) {
  return `/api/admin/employers/${id}/verification-document`;
}

async function submitEmployerVerificationDocument(registrationNumber, file) {
  const form = new FormData();
  form.append("registration_number", registrationNumber);
  form.append("file", file);
  const res = await fetch(`/api/employers/me/verification-document`, {
    method: "POST", credentials: "include", body: form,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Document upload failed");
  }
  return res.json();
}

function deleteSeekerAccount(seekerId) {
  return apiFetch(`/api/admin/seekers/${seekerId}`, { method: "DELETE" });
}

function deleteEmployerAccount(employerId) {
  return apiFetch(`/api/admin/employers/${employerId}`, { method: "DELETE" });
}

function suspendSeekerAccount(seekerId) {
  return apiFetch(`/api/admin/seekers/${seekerId}/suspend`, { method: "POST" });
}

function unsuspendSeekerAccount(seekerId) {
  return apiFetch(`/api/admin/seekers/${seekerId}/unsuspend`, { method: "POST" });
}

function suspendEmployerAccount(employerId) {
  return apiFetch(`/api/admin/employers/${employerId}/suspend`, { method: "POST" });
}

function unsuspendEmployerAccount(employerId) {
  return apiFetch(`/api/admin/employers/${employerId}/unsuspend`, { method: "POST" });
}

function fetchUserApplications() {
  return apiFetch(`/api/applications`);
}

// ---------------------------------------------------------------------------
// Employer job management (job_management.html)
// ---------------------------------------------------------------------------

function fetchEmployerJobs({ keyword = "", status = "" } = {}) {
  const params = new URLSearchParams();
  if (keyword) params.set("keyword", keyword);
  if (status && status !== "all") params.set("status", status);
  const query = params.toString();
  return apiFetch(`/api/employer/jobs${query ? `?${query}` : ""}`);
}

function createEmployerJob(payload) {
  return apiFetch(`/api/employer/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function updateEmployerJob(jobId, payload) {
  return apiFetch(`/api/employer/jobs/${jobId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function publishEmployerJob(jobId) {
  return apiFetch(`/api/employer/jobs/${jobId}/publish`, {
    method: "POST",
  });
}

function closeEmployerJob(jobId) {
  return apiFetch(`/api/employer/jobs/${jobId}/close`, {
    method: "POST",
  });
}

function deleteEmployerJob(jobId) {
  return apiFetch(`/api/employer/jobs/${jobId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Employer applicant management (employer_applications.html, applicant_detail.html)
// ---------------------------------------------------------------------------

function fetchEmployerApplications() {
  return apiFetch(`/api/employer/applications`);
}

function fetchApplicantDetail(applicantId) {
  return apiFetch(`/api/employer/applicant/${applicantId}`);
}

function updateApplicantStage(applicantId, payload) {
  return apiFetch(`/api/employer/applicant/${applicantId}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Notifications (notifications.html, employer_notifications.html)
// ---------------------------------------------------------------------------

function fetchNotifications() {
  return apiFetch(`/api/notifications`);
}

function deleteNotification(notificationId) {
  return apiFetch(`/api/notifications/${notificationId}`, {
    method: "DELETE",
  });
}

function clearAllNotifications() {
  return apiFetch(`/api/notifications`, {
    method: "DELETE",
  });
}

function trustSealHtml(score, reasons) {
  const safeScore = score == null ? "—" : score;
  const lowClass = score != null && score < 50 ? "low" : "";
  const tooltip =
    reasons && reasons.length > 0
      ? `Credibility score. Lowered by: ${reasons.join("; ")}`
      : score != null
      ? "Credibility score. No issues found with this posting."
      : "Credibility score";
  return `
    <div class="trust-seal ${lowClass}" title="${escapeHtml(tooltip)}">
      <div class="score">${safeScore}</div>
      <div class="label">Trust</div>
    </div>
  `;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ---------------------------------------------------------------------------
// Real accounts / sessions (US-01/US-02/US-04/US-06). Cookie-based —
// `credentials: "include"` is required on every call so the session cookie
// travels with the request. Not yet wired into the rest of the app: the
// dev-user-bar / localStorage identity used everywhere else is untouched
// until a later sub-project retrofits it.
// ---------------------------------------------------------------------------

async function _authFetch(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
      : data.detail;
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

function registerSeeker(fullName, email, password) {
  return _authFetch("/api/auth/register/seeker", { full_name: fullName, email, password });
}

function registerEmployer(companyName, email, password) {
  return _authFetch("/api/auth/register/employer", { company_name: companyName, email, password });
}

function loginAccount(email, password) {
  return _authFetch("/api/auth/login", { email, password });
}

function requestPasswordReset(email) {
  return _authFetch("/api/auth/forgot-password", { email });
}

function resetPassword(token, newPassword) {
  return _authFetch("/api/auth/reset-password", { token, new_password: newPassword });
}

function confirmEmailToken(token) {
  return _authFetch("/api/auth/confirm-email", { token });
}

function changePassword(currentPassword, newPassword) {
  return apiFetch("/api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

function deleteMyAccount(password) {
  return apiFetch("/api/auth/me", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
}

async function logoutAccount() {
  const res = await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  if (!res.ok) throw new Error("Logout failed");
  return res.json();
}

async function getCurrentAccount() {
  const res = await fetch("/api/auth/me", { credentials: "include" });
  if (!res.ok) return null;
  return res.json();
}

/** Call at the top of any page that requires being logged in as a specific
 * role. Redirects to login.html and resolves null if not logged in (or
 * logged in as the wrong role) — callers should `return` immediately when
 * they get null back, letting the redirect happen. */
async function requireLogin(role) {
  const account = await getCurrentAccount();
  if (!account || account.role !== role) {
    window.location.href = "/UI/html/login.html";
    return null;
  }
  return account;
}

/** Like requireLogin(role), but for pages usable by EITHER seeker or
 * employer (currently only messages.html, the one page in this app that
 * intentionally serves both roles from a single file). */
async function requireLoginAnyRole(roles) {
  const account = await getCurrentAccount();
  if (!account || !roles.includes(account.role)) {
    window.location.href = "/UI/html/login.html";
    return null;
  }
  return account;
}

/** Populates the given container (typically the existing .dev-user-bar div)
 * with the account's display name and a working Log out button. Takes the
 * already-fetched account object (from the page's own requireLogin() call)
 * rather than re-fetching it — every protected page calls requireLogin()
 * first, which already guarantees the account is valid and the right role,
 * so re-checking here would be redundant, not protective. */
async function renderAccountBar(containerId, account) {
  const container = document.getElementById(containerId);
  if (!container || !account) return;

  container.innerHTML = `
    Logged in as: <strong>${escapeHtml(account.display_name)}</strong>
    <button type="button" class="btn-link" id="logoutBtn" style="margin-left:12px;">Log out</button>
  `;
  document.getElementById("logoutBtn").addEventListener("click", async () => {
    await logoutAccount();
    window.location.href = "/UI/html/login.html";
  });
}

/** Toggles a submit button's disabled state and swaps its label to a
 * "busy" message while an async action is in flight, restoring the
 * original label afterwards. Call setButtonBusy(btn, true, "Saving…")
 * before the request and setButtonBusy(btn, false) in a finally block. */
function setButtonBusy(button, busy, busyLabel) {
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = busyLabel || "Working…";
    button.disabled = true;
  } else {
    if (button.dataset.originalLabel) button.textContent = button.dataset.originalLabel;
    button.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Messaging (messages.html, plus "Message Employer" / "Message Seeker"
// buttons on job_detail.html / applicant_detail.html). US-40 to US-43.
// ---------------------------------------------------------------------------

function fetchConversations() {
  return apiFetch(`/api/conversations`);
}

function fetchMessageContacts(search = "") {
  const query = search ? `?search=${encodeURIComponent(search)}` : "";
  return apiFetch(`/api/messages/contacts${query}`);
}

function fetchConversationMessages(conversationId) {
  return apiFetch(`/api/conversations/${conversationId}/messages`);
}

function sendMessage({ recipientId, body, jobId = null }) {
  const payload = { recipient_id: recipientId, body };
  if (jobId != null) payload.job_id = jobId;
  return apiFetch(`/api/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Sends a message with an image/file attachment (US messaging enhancement).
 * Caption is optional — a bare attachment is a valid message. */
async function sendMessageWithAttachment({ recipientId, body = "", jobId = null, file }) {
  const form = new FormData();
  form.append("recipient_id", recipientId);
  form.append("body", body);
  if (jobId != null) form.append("job_id", jobId);
  form.append("file", file);

  const res = await fetch(`/api/messages/attachment`, { method: "POST", credentials: "include", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

/** Edit a message's text — sender-only, time-limited window (enforced server-side). */
function editMessage(messageId, body) {
  return apiFetch(`/api/messages/${messageId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
}

/** Delete a message. scope="me" hides it just for the requester;
 * scope="everyone" is sender-only and replaces it with a placeholder for both. */
function deleteMessage(messageId, scope) {
  return apiFetch(`/api/messages/${messageId}?scope=${scope}`, {
    method: "DELETE",
  });
}

/** Used by the contextual "Message Employer" / "Message Seeker" buttons. */
function findOrCreateConversation(otherId) {
  return apiFetch(`/api/conversations/find-or-create?other_id=${otherId}`, { method: "POST" });
}

/** Hides a whole thread from the requester's own inbox (like WhatsApp's
 * "Delete chat") — the other party's copy is unaffected, and the thread
 * reappears for both if there's new activity afterwards. */
function deleteConversation(conversationId) {
  return apiFetch(`/api/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

// ---- US-46/47: interview invitations ----

/** US-46: employer sends a structured interview invite (date/time,
 * duration, mode, location/link, notes) instead of a plain text message.
 * details = { scheduled_at (ISO string), duration_minutes, mode, location_or_link, notes } */
function sendInterviewInvite(seekerId, jobId, details) {
  const params = new URLSearchParams({ seeker_id: seekerId });
  if (jobId != null) params.set("job_id", jobId);
  return apiFetch(`/api/messages/interview-invite?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(details),
  });
}

/** US-47: seeker accepts or declines. response must be "accepted" or "declined". */
function respondToInterview(messageId, response) {
  return apiFetch(`/api/messages/${messageId}/interview-response`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ response }),
  });
}

/** US-XX: employer reschedules an interview they sent — same shape as
 * sendInterviewInvite's details. Resets status to "pending" server-side. */
function rescheduleInterview(messageId, details) {
  return apiFetch(`/api/messages/${messageId}/interview-reschedule`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(details),
  });
}

/** US-XX: employer cancels an interview they sent. */
function cancelInterview(messageId) {
  return apiFetch(`/api/messages/${messageId}/interview-cancel`, {
    method: "POST",
  });
}

/** Rough "x minutes/hours ago" formatting — used in the conversation list preview. */
function timeAgo(isoString) {
  if (!isoString) return "";
  const then = new Date(isoString.endsWith("Z") ? isoString : isoString + "Z");
  const seconds = Math.floor((Date.now() - then.getTime()) / 1000);
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  const days = Math.floor(seconds / 86400);
  return days === 1 ? "Yesterday" : `${days}d ago`;
}

/** Absolute sent-date formatting for chat bubbles (e.g. "9:14 AM" for
 * today, "21 Jul, 9:14 AM" otherwise) — chat apps show clock time inside
 * a thread and reserve relative "x ago" phrasing for the inbox list. */
function formatMessageDateTime(isoString) {
  if (!isoString) return "";
  const then = new Date(isoString.endsWith("Z") ? isoString : isoString + "Z");
  const now = new Date();
  const timePart = then.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const isToday = then.toDateString() === now.toDateString();
  if (isToday) return timePart;
  const datePart = then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return `${datePart}, ${timePart}`;
}

// ---------------------------------------------------------------------------
// Unread-messages nav badge. api.js is loaded on every page, so this runs
// everywhere automatically — no per-page wiring needed. It finds whichever
// "Messages" nav link is on the current page (seeker or employer topbar)
// and keeps an unread-count pill on it current via polling.
// ---------------------------------------------------------------------------

const MESSAGES_BADGE_POLL_MS = 20000;

async function _refreshMessagesNavBadge() {
  const link = document.querySelector('a[href*="messages.html"]');
  if (!link) return; // this page has no Messages nav link (yet, or at all)

  const isEmployer = link.getAttribute("href").includes("role=employer");
  const role = isEmployer ? "employer" : "seeker";
  const userId = isEmployer ? getCurrentEmployerId() : getCurrentSeekerId();

  try {
    const conversations = await fetchConversations(role, userId);
    const total = conversations.reduce((sum, c) => sum + (c.unread_count || 0), 0);

    let badge = link.querySelector(".nav-badge");
    if (total > 0) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "nav-badge";
        link.appendChild(badge);
      }
      badge.textContent = total > 99 ? "99+" : String(total);
    } else if (badge) {
      badge.remove();
    }
  } catch (_) {
    // A badge failing to load shouldn't break the rest of the page.
  }
}

function _startMessagesNavBadgePolling() {
  // Some pages (messages.html itself, employer pages) build their topbar
  // via JS rather than static HTML — give that a moment to run first.
  setTimeout(_refreshMessagesNavBadge, 300);
  setInterval(_refreshMessagesNavBadge, MESSAGES_BADGE_POLL_MS);
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", _startMessagesNavBadgePolling);
}

// Show the seeker's uploaded picture beside the Profile navigation label.
// Kept here because api.js is shared by every seeker page.
function setSeekerNavAvatar(profile) {
  const link = document.querySelector('header .topbar-right a[href="/UI/html/profile.html"]');
  if (!link) return;

  link.classList.add("profile-nav-link");
  let avatar = link.querySelector(".profile-nav-avatar");

  if (!avatar) {
    avatar = document.createElement("img");
    avatar.className = "profile-nav-avatar";
    avatar.alt = "Your profile picture";
    link.prepend(avatar);
  }
  avatar.src = profile?.profile_picture_url || DEFAULT_PROFILE_IMAGE_URL;
}

async function _loadSeekerNavAvatar() {
  const profileLink = document.querySelector('header a[href="/UI/html/profile.html"]');
  if (!profileLink) return;

  setSeekerNavAvatar(null);
  try {
    setSeekerNavAvatar(await fetchSeekerProfile());
  } catch (_) {
    // Navigation remains usable if the profile request fails or expires.
  }
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => setTimeout(_loadSeekerNavAvatar, 300));
}

/** Blocks the other participant. Blocking is enforced by the API for both
 * directions, so it also applies to messages sent from contextual pages. */
function blockConversation(conversationId) {
  return apiFetch(`/api/conversations/${conversationId}/block`, {
    method: "POST",
  });
}

function unblockConversation(conversationId) {
  return apiFetch(`/api/conversations/${conversationId}/block`, {
    method: "DELETE",
  });
}
