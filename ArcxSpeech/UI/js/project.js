// ================= Backend API layer =================
// Same-origin relative paths -- the FastAPI backend (api/routes.py)
// serves this UI itself via StaticFiles, so no base URL/CORS setup is
// needed here.

async function apiFetch(url, options = {}) {
    const opts = { ...options };
    // A JSON string body needs the content-type header; FormData (file
    // uploads) sets its own multipart boundary header automatically, so
    // leave that case alone.
    if (opts.body && typeof opts.body === "string") {
        opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    }

    const res = await fetch(url, opts);

    if (!res.ok) {
        let detail = res.statusText;
        try {
            const data = await res.json();
            const d = data && data.detail;
            detail = (d && typeof d === "object" ? d.detail : d) || detail;
        } catch (_) { /* response body wasn't JSON */ }
        const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        err.status = res.status;
        throw err;
    }

    if (res.status === 204) return null;
    return res.json();
}

const api = {
    getSubjects: () => apiFetch("/api/subjects"),
    createSubject: (payload) => apiFetch("/api/subjects", { method: "POST", body: JSON.stringify(payload) }),
    deleteSubject: (subjectId) => apiFetch(`/api/subjects/${encodeURIComponent(subjectId)}`, { method: "DELETE" }),
    getSubjectSummary: (subjectId) => apiFetch(`/api/subjects/${encodeURIComponent(subjectId)}/summary`),

    getSessions: (subjectId) => apiFetch(`/api/subjects/${encodeURIComponent(subjectId)}/sessions`),
    createSession: (subjectId, payload) => apiFetch(`/api/subjects/${encodeURIComponent(subjectId)}/sessions`, { method: "POST", body: JSON.stringify(payload) }),
    getSessionDetail: (sessionId) => apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}`),
    deleteSession: (sessionId) => apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),

    getRecordings: (sessionId) => apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/recordings`),
    getRecordingSpectrogram: (sessionId, recordingId) => apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/recordings/${encodeURIComponent(recordingId)}/spectrogram`),
    // Warms up the serial connection (the ~2s device settle time) ahead
    // of the timed capture, so that settling happens during the visible
    // pre-record countdown instead of after the recording request lands
    // -- see runPreRecordCountdown/startTaskRecording below.
    prepareRecording: () => apiFetch("/api/recording/prepare", { method: "POST" }),
    releaseRecordingPrepare: (token) => apiFetch(`/api/recording/prepare/${encodeURIComponent(token)}`, { method: "DELETE" }),
    addLiveRecording: (sessionId, task, duration, prepareToken) => apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/recordings`, {
        method: "POST",
        body: JSON.stringify({ task, duration, prepare_token: prepareToken || null }),
    }),
    uploadRecordings: (sessionId, task, files) => {
        const formData = new FormData();
        formData.append("task", task);
        Array.from(files).forEach(file => formData.append("files", file));
        return apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/recordings/upload`, {
            method: "POST",
            body: formData,
        });
    },
    deleteRecording: (sessionId, recordingId) => apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/recordings/${encodeURIComponent(recordingId)}`, { method: "DELETE" }),
    extractSessionFeatures: (sessionId) => apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/recordings/extract`, { method: "POST" }),
};

// ================= Data (populated from the backend) =================

let SUBJECTS = [];
const SESSIONS = {};   // subjectId -> array of mapped session rows
const RECORDINGS = {}; // sessionId -> array of mapped recording rows

// ---- Row mapping: backend JSON -> the shape the UI already renders ----

function formatMeanSd(mean, sd) {
    if (typeof mean !== "number") return "\u2014";
    const meanStr = mean.toFixed(3);
    return typeof sd === "number" ? `${meanStr} \u00B1 ${sd.toFixed(3)}` : meanStr;
}

function formatRawValue(v) {
    if (v === null || v === undefined) return "\u2014";
    if (typeof v === "boolean") return v ? "Yes" : "No";
    return String(v);
}

function mapSubject(s) {
    return {
        id: s.id,
        name: s.name,
        age: s.age === "" || s.age === undefined || s.age === null ? "" : (Number(s.age) || s.age),
        sex: s.sex || "",
        group: s.group || "Unassigned",
        added: (s.createdAt || "").slice(0, 10),
        _raw: s,
        _summary: null,
        _summaryLoading: false,
    };
}

function mapSession(sess) {
    const created = sess.created_at ? new Date(sess.created_at) : null;
    return {
        id: sess.session_id,
        subjectId: sess.subject_id,
        name: sess.name,
        date: created && !Number.isNaN(created.getTime()) ? formatSessionDate(created) : "",
        _raw: sess,
        _summary: null,
        _summaryLoading: false,
    };
}

const RECORDING_TASK_DISPLAY_NAME = {
    "Sustained Vowel": "Sustained Vowel /a/",
    "DDK": "DDK /pa-ta-ka/",
};

function mapRecording(row) {
    const created = row.created_at ? new Date(row.created_at) : null;
    return {
        id: row.recording_id,
        sessionId: row.session_id,
        name: RECORDING_TASK_DISPLAY_NAME[row.task] || row.task,
        time: created && !Number.isNaN(created.getTime()) ? formatRecordingTime(created) : "",
        type: row.source === "uploaded" ? "uploaded" : "built-in",
        task: row.task,
        _raw: row,
    };
}

// ---- Loaders (fetch + cache) ----

async function loadSubjects() {
    try {
        const rows = await api.getSubjects();
        SUBJECTS = rows.map(mapSubject);
    } catch (err) {
        console.error(err);
        showToast("Couldn't load subjects.");
        SUBJECTS = [];
    }
    renderSubjects();
}

async function loadSessionsForSubject(subject, { force = false } = {}) {
    if (!subject) return;
    if (!force && SESSIONS[subject.id]) return;
    try {
        const rows = await api.getSessions(subject.id);
        SESSIONS[subject.id] = rows.map(mapSession);
    } catch (err) {
        console.error(err);
        showToast("Couldn't load sessions.");
        SESSIONS[subject.id] = SESSIONS[subject.id] || [];
    }
}

async function loadRecordingsForSession(session, { force = false } = {}) {
    if (!session) return;
    if (!force && RECORDINGS[session.id]) return;
    try {
        const rows = await api.getRecordings(session.id);
        RECORDINGS[session.id] = rows.map(mapRecording);
    } catch (err) {
        console.error(err);
        showToast("Couldn't load recordings.");
        RECORDINGS[session.id] = RECORDINGS[session.id] || [];
    }
}

// Lazily fetches the mean/SD summary behind a subject/session analysis
// target (see setAnalysisTarget below), caching it on the ref itself so
// re-picking the same target doesn't refetch. Values widgets read
// straight from ref._summary once it lands -- see getWidgetValuesSync
// inside the pinboard IIFE further down.
async function ensureAnalysisSummary(type, ref) {
    if (!ref || ref._summary || ref._summaryLoading) return;
    ref._summaryLoading = true;
    try {
        ref._summary = type === "subject"
            ? await api.getSubjectSummary(ref.id)
            : await api.getSessionDetail(ref.id);
    } catch (err) {
        console.error(err);
        showToast("Couldn't load analysis summary.");
    } finally {
        ref._summaryLoading = false;
        if (typeof window.refreshAllWidgetValues === "function") window.refreshAllWidgetValues();
    }
}

// Clears the cached mean/SD summary (see ensureAnalysisSummary above) for
// a session whose recordings just changed (added, uploaded, or deleted),
// and for the subject that owns it -- a subject's summary is aggregated
// across every one of its sessions, so it's stale too whenever any of
// them changes. If the session or its owning subject is the currently
// active analysis target, immediately re-fetches so open Values widgets
// pick up the new numbers without the user having to reselect anything.
function invalidateSessionAnalysisCache(sessionId) {
    let ownerSubjectId = null;
    for (const subjectId in SESSIONS) {
        const sessionRef = (SESSIONS[subjectId] || []).find((s) => s.id === sessionId);
        if (sessionRef) {
            sessionRef._summary = null;
            ownerSubjectId = subjectId;
            break;
        }
    }
    if (ownerSubjectId) {
        const subjectRef = SUBJECTS.find((s) => s.id === ownerSubjectId);
        if (subjectRef) subjectRef._summary = null;
    }
    if (analysisTargetRef && !analysisTargetRef._summary &&
        (analysisTargetType === "session" || analysisTargetType === "subject")) {
        ensureAnalysisSummary(analysisTargetType, analysisTargetRef);
    }
}

// ================= Toast (small inline message, replaces window.alert
// for validation-style errors) =================

const toastEl = document.getElementById("toast");
let toastTimer = null;

function showToast(message) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toastEl.classList.remove("visible");
    }, 2200);
}

// ================= State =================

let currentSort = "name";
let currentLevel = "subjects"; // "subjects" | "sessions" | "recordings"
let selectedSubject = null;
let selectedSession = null;
let selectedRecording = null;

// What the pinboard is currently analyzing — set whenever the user picks
// "Analyze Subject" / "Analyze Session" from a row flyout, or clicks a
// recording in the recordings list. Quality widgets only make sense for a
// single recording (they surface per-take signal-quality metrics), so the
// Quality button is hidden unless a recording is the active analysis target.
let analysisTargetType = null; // "subject" | "session" | "recording" | null

// The actual subject/session/recording object behind analysisTargetType —
// tracked separately so re-picking the exact same target (e.g. reopening
// the select-recording dropdown and clicking the same recording again)
// can be detected and treated as a no-op instead of re-clearing the board.
let analysisTargetRef = null;

function setAnalysisTarget(type, ref) {
    // Re-selecting the same subject/session/recording that's already the
    // active analysis target shouldn't do anything — in particular it
    // shouldn't blow away widgets the user has open.
    if (type === analysisTargetType && ref === analysisTargetRef) return;

    analysisTargetType = type;
    analysisTargetRef = ref;
    updateWidgetButtonsAvailability();
    // Refresh the highlight in all three lists — whichever one is on
    // screen (or gets navigated back to later) should show the new
    // target, not wherever the user last clicked to browse.
    renderSubjects();
    renderSessions();
    renderRecordings();
    if (typeof window.clearPinboardWidgets === "function") {
        window.clearPinboardWidgets();
    }
    const noTargetMsg = document.getElementById("pinboard-no-target-msg");
    if (noTargetMsg) noTargetMsg.classList.toggle("is-hidden", !!type);
    if (!type) {
        selectRecordingLabel.textContent = "Select Recording";
    }
    // Subject/session targets show a live-computed mean±SD summary
    // pulled from the backend on demand -- kick that fetch off now so
    // it's usually already cached by the time the user clicks "Values".
    if (type === "subject" || type === "session") {
        ensureAnalysisSummary(type, ref);
    }
}

// When a single recording is the analysis target, its task type (sustained
// vowel vs. DDK) is already known, so the Values dropdown is unnecessary —
// clicking "Values" just drops that one widget straight onto the board. For
// a subject or session target (or a custom/uploaded recording whose task
// type isn't one of the two built-ins), the dropdown is still needed so the
// user can pick.
function getDirectRecordingValueType() {
    if (analysisTargetType !== "recording" || !selectedRecording) return null;
    const name = selectedRecording.name || "";
    if (/sustained/i.test(name)) return "Sustained";
    if (/ddk/i.test(name)) return "DDK";
    return null;
}

// ---- Task-type filtering for graphs/widgets ----
//
// IMPORTANT FOR FUTURE AI: every graph widget (see GRAPH_RENDERERS
// further down, in the pinboard IIFE) and every metric widget type
// (see WIDGET_METRICS) belongs to a task type — "Sustained", "DDK",
// or "Both" (task-agnostic, e.g. a widget that compares the two, or
// one like recording Quality/SNR that isn't specific to either task).
// Any NEW graph or widget added later MUST be tagged with its
// taskType and included in this filtering (here, in
// updateWidgetButtonsAvailability() below, and in the Values dropdown
// filtering there too) — otherwise it will keep showing up (or stay
// hidden) no matter which task type is actually being analyzed, which
// defeats the point of this filtering. Rule of thumb: if a widget
// only reads Sustained-vowel features (F0/F1/F2/HNR/Jitter) or only
// DDK features, tag it with that task type; if it reads both, or
// reads task-agnostic data (recording-level quality/SNR, raw
// waveform/spectrogram), tag it "Both".
//
// Determines which task type(s) are actually available for the
// current analysis target, so task-specific graphs/widgets can be
// hidden instead of showing empty or misleading data:
//   - a single recording only ever has one task type
//   - a session/subject may have Sustained recordings, DDK
//     recordings, or both — in which case everything shows
function getAvailableTaskTypesForTarget() {
    if (analysisTargetType === "recording") {
        if (!selectedRecording) return new Set();
        const direct = getDirectRecordingValueType();
        return direct ? new Set([direct]) : new Set(["Sustained", "DDK"]);
    }

    if (analysisTargetType === "session" || analysisTargetType === "subject") {
        const summary = analysisTargetRef && analysisTargetRef._summary;
        // Summary not loaded yet -- don't hide anything while we wait,
        // to avoid a flash of missing buttons; ensureAnalysisSummary()
        // re-runs updateWidgetButtonsAvailability (via
        // refreshAllWidgetValues) once it resolves.
        if (!summary) return new Set(["Sustained", "DDK"]);
        const types = new Set();
        if (summary.vowel_trials && summary.vowel_trials.length) types.add("Sustained");
        if (summary.ddk_trials && summary.ddk_trials.length) types.add("DDK");
        return types;
    }

    return new Set();
}

// A graph/widget with taskType "Both" is always shown once there's any
// target at all; otherwise it's shown only if its task type is among
// the ones actually available for the current target (see above).
function isTaskTypeVisible(taskType) {
    if (taskType === "Both") return analysisTargetType !== null;
    return getAvailableTaskTypesForTarget().has(taskType);
}

function updateWidgetButtonsAvailability() {
    const valuesWrap = document.getElementById("values-type-wrap");
    const qualityWrap = document.getElementById("quality-type-wrap");
    const valuesChevron = document.getElementById("add-values-chevron");

    // Nothing to add widgets for until a subject, session, or recording
    // has actually been chosen as the analysis target.
    const hasTarget = analysisTargetType !== null;

    // Graph buttons are additionally filtered by task type (see
    // getAvailableTaskTypesForTarget()/isTaskTypeVisible() above) --
    // e.g. Formants only makes sense for Sustained Vowel data, so it
    // stays hidden while a DDK-only recording/session/subject is being
    // analyzed. window.GRAPH_TASK_TYPES is populated by the pinboard
    // IIFE from GRAPH_RENDERERS, the single source of truth for each
    // graph's taskType -- see the note there before adding a new graph.
    const graphTaskTypes = window.GRAPH_TASK_TYPES || {};
    const GRAPH_BUTTON_TITLES = {
        "add-formants-btn": "Formants",
        "add-voice-quality-btn": "Voice Quality",
        "add-spectrogram-btn": "Spectrogram",
        "add-voice-metrics-btn": "Voice Metrics",
        "add-pitch-waveform-btn": "Pitch Waveform",
        "add-ddk-waveform-btn": "DDK Waveform",
    };
    Object.entries(GRAPH_BUTTON_TITLES).forEach(([id, title]) => {
        const btn = document.getElementById(id);
        if (!btn) return;
        const taskType = graphTaskTypes[title] || "Both";
        btn.style.display = hasTarget && isTaskTypeVisible(taskType) ? "" : "none";
    });

    // DDK Waveform, Pitch Waveform, and Spectrogram additionally only
    // make sense against a single recording -- each renders one real
    // audio clip's waveform/STFT, which has no coherent meaning
    // aggregated across a session/subject's several trials (unlike e.g.
    // Voice Metrics, which is fine averaging scalar stats). Restrict
    // them the same way Quality/the playback bar are restricted above.
    ["add-ddk-waveform-btn", "add-pitch-waveform-btn", "add-spectrogram-btn"].forEach((id) => {
        const btn = document.getElementById(id);
        if (btn && analysisTargetType !== "recording") btn.style.display = "none";
    });

    if (valuesWrap) valuesWrap.style.display = hasTarget ? "" : "none";

    // Filter the Values dropdown's Sustained/DDK options the same way --
    // only offer picking a task type that's actually present for a
    // session/subject target (a single recording never shows this
    // dropdown at all, see getDirectRecordingValueType()/valuesChevron
    // below).
    if (hasTarget) {
        const availableTypes = getAvailableTaskTypesForTarget();
        document.querySelectorAll('#values-type-dropdown [data-value-type]').forEach(btn => {
            const vt = btn.dataset.valueType;
            btn.style.display = availableTypes.has(vt) ? "" : "none";
        });
    }

    // Quality and the playback bar additionally only make sense for a
    // single recording -- and only one actually captured through the app
    // (an ambient channel alongside the patient channel is what the
    // quality analysis is computed from). Uploaded recordings don't have
    // that second channel, so there's no quality rating to show for them.
    const qualityAllowed = analysisTargetType === "recording" &&
        selectedRecording && selectedRecording.type !== "uploaded";
    if (qualityWrap) qualityWrap.style.display = qualityAllowed ? "" : "none";

    // Hide the Values chevron when clicking it won't open a dropdown.
    if (valuesChevron) valuesChevron.style.display = getDirectRecordingValueType() ? "none" : "";
}

// The subjects/sessions/recordings lists double as a drill-down browser
// (selectedSubject/selectedSession/selectedRecording just track where the
// user has navigated to, e.g. to peek at another session's recordings)
// and as the picker for the active analysis target. The "selected"
// highlight must reflect the latter, not wherever browsing left off —
// otherwise clicking into a session/recording to look around and then
// going back leaves the wrong row highlighted. Compare by reference
// (not id) since session ids repeat across subjects.
function isAnalysisTarget(type, obj) {
    return analysisTargetType === type && analysisTargetRef === obj;
}

const subjectsListEl = document.getElementById("subjects-list");
const sessionsListEl = document.getElementById("sessions-list");
const recordingsListEl = document.getElementById("recordings-list");

const listTitleEl = document.getElementById("list-title");
const listBackBtn = document.getElementById("list-back-btn");
const sortTriggerWrap = document.getElementById("sort-trigger-wrap");
const addSubjectBtn = document.getElementById("add-subject-btn");
const addSessionBtn = document.getElementById("add-session-btn");
const addRecordingWrap = document.getElementById("add-recording-wrap");
const addRecordingBtn = document.getElementById("add-recording-btn");

function initials(name) {
    const parts = name.split(" ").filter(Boolean);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return parts.map(p => p[0]).join("").slice(0, 2).toUpperCase();
}

function sortedSubjects() {
    let list = SUBJECTS.slice();
    if (currentSort === "name") list.sort((a, b) => a.name.localeCompare(b.name));
    if (currentSort === "date") list.sort((a, b) => new Date(b.added) - new Date(a.added));
    if (currentSort === "age") list.sort((a, b) => a.age - b.age);
    return list;
}

function renderLevelChrome() {
    const atSubjects = currentLevel === "subjects";
    const atSessions = currentLevel === "sessions";
    const atRecordings = currentLevel === "recordings";

    subjectsListEl.style.display = atSubjects ? "" : "none";
    sessionsListEl.style.display = atSessions ? "" : "none";
    recordingsListEl.style.display = atRecordings ? "" : "none";

    listBackBtn.style.display = atSubjects ? "none" : "flex";
    sortTriggerWrap.style.display = atSubjects ? "flex" : "none";
    addSubjectBtn.style.display = atSubjects ? "flex" : "none";
    addSessionBtn.style.display = atSessions ? "flex" : "none";
    addRecordingWrap.style.display = atRecordings ? "flex" : "none";
    if (!atRecordings) closeAddRecordingFlyout();

    if (atSubjects) {
        listTitleEl.textContent = "Subjects";
    } else if (atSessions) {
        listTitleEl.textContent = "Sessions" + (selectedSubject ? " \u2014 " + selectedSubject.name : "");
    } else {
        listTitleEl.textContent = "Recordings" + (selectedSession ? " \u2014 " + selectedSession.name : "");
    }
}

listBackBtn.addEventListener("click", () => {
    if (currentLevel === "recordings") {
        currentLevel = "sessions";
        selectedRecording = null;
    } else if (currentLevel === "sessions") {
        currentLevel = "subjects";
    }
    renderLevelChrome();
    renderSessions();
    renderRecordings();
});

// ================= Row options flyout (ellipsis button on subject/session
// rows) -- opens a small menu to the side of the button, mirroring the
// add-recording flyout's sideways-panel style but built dynamically since
// there's one row per subject/session rather than a single static trigger. =================

let rowFlyoutEl = null;

function closeRowFlyout() {
    if (rowFlyoutEl) {
        rowFlyoutEl.remove();
        rowFlyoutEl = null;
    }
}

function openRowFlyout(anchorBtn, items) {
    closeRowFlyout();

    const menu = document.createElement("div");
    menu.className = "row-flyout";
    menu.innerHTML = items.map((item, i) =>
        `<button type="button" class="flyout-item${item.danger ? " flyout-item--danger" : ""}" data-idx="${i}">${item.label}</button>`
    ).join("");
    document.body.appendChild(menu);

    const anchorRect = anchorBtn.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    let left = anchorRect.right + 8;
    if (left + menuRect.width > window.innerWidth - 8) {
        left = anchorRect.left - menuRect.width - 8;
    }
    let top = anchorRect.top + anchorRect.height / 2 - menuRect.height / 2;
    top = Math.min(Math.max(top, 8), window.innerHeight - menuRect.height - 8);
    menu.style.left = left + "px";
    menu.style.top = top + "px";

    menu.querySelectorAll(".flyout-item").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            closeRowFlyout();
            items[Number(btn.dataset.idx)].onClick();
        });
    });

    rowFlyoutEl = menu;
}

// Capture phase so this still fires even though the recording-select
// dropdown (and other panels) call stopPropagation() on bubbling clicks.
document.addEventListener("click", (e) => {
    if (rowFlyoutEl && rowFlyoutEl.contains(e.target)) return;
    closeRowFlyout();
}, true);
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeRowFlyout();
});

// ================= Delete-confirmation modal (shared by subject and
// session row deletion) =================

const confirmDeleteOverlay = document.getElementById("confirmDeleteOverlay");
const confirmDeleteTitleEl = document.getElementById("confirmDeleteTitle");
const confirmDeleteMessageEl = document.getElementById("confirmDeleteMessage");
const confirmDeleteCancelBtn = document.getElementById("confirmDeleteCancel");
const confirmDeleteConfirmBtn = document.getElementById("confirmDeleteConfirm");
let pendingDeleteAction = null;

function openConfirmDelete(title, message, onConfirm) {
    if (!confirmDeleteOverlay) return;
    confirmDeleteTitleEl.textContent = title;
    confirmDeleteMessageEl.textContent = message;
    pendingDeleteAction = onConfirm;
    confirmDeleteOverlay.classList.add("visible");
}

function closeConfirmDelete() {
    if (!confirmDeleteOverlay) return;
    confirmDeleteOverlay.classList.remove("visible");
    pendingDeleteAction = null;
}

confirmDeleteCancelBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeConfirmDelete();
});

confirmDeleteConfirmBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    const action = pendingDeleteAction;
    closeConfirmDelete();
    if (action) action();
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && confirmDeleteOverlay && confirmDeleteOverlay.classList.contains("visible")) {
        closeConfirmDelete();
    }
});

function renderSubjects() {
    const list = sortedSubjects();
    subjectsListEl.innerHTML = "";
    list.forEach(s => {
        const el = document.createElement("div");
        el.className = "subject-item" + (isAnalysisTarget("subject", s) ? " selected" : "");
        el.innerHTML = `
            <div class="subject-avatar">${initials(s.name)}</div>
            <div class="subject-info">
                <div class="subject-name">${s.name}</div>
                <div class="subject-sub">${s.id} &middot; ${s.group}</div>
            </div>
            <button type="button" class="row-ellipsis-btn" title="More options" aria-label="More options">
                <svg width="3" height="15" viewBox="0 0 3 15" fill="currentColor">
                    <circle cx="1.5" cy="1.5" r="1.5"/>
                    <circle cx="1.5" cy="7.5" r="1.5"/>
                    <circle cx="1.5" cy="13.5" r="1.5"/>
                </svg>
            </button>
        `;
        el.addEventListener("click", () => selectSubject(s));
        el.querySelector(".row-ellipsis-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            openRowFlyout(e.currentTarget, [
                { label: "Analyze Subject", onClick: () => {
                    closeRecordingSelectDropdown();
                    selectRecordingLabel.textContent = s.name;
                    setAnalysisTarget("subject", s);
                } },
                { label: "Delete Subject", danger: true, onClick: () => {
                    openConfirmDelete(
                        "Delete Subject",
                        `This will permanently delete "${s.name}" and all of their sessions and recordings. This can't be undone.`,
                        () => deleteSubject(s)
                    );
                } },
            ]);
        });
        subjectsListEl.appendChild(el);
    });
}

async function deleteSubject(s) {
    try {
        await api.deleteSubject(s.id);
    } catch (err) {
        console.error(err);
        showToast(err.message || "Couldn't delete subject.");
        return;
    }

    const idx = SUBJECTS.findIndex(x => x.id === s.id);
    if (idx !== -1) SUBJECTS.splice(idx, 1);
    delete SESSIONS[s.id];

    if (selectedSubject && selectedSubject.id === s.id) {
        selectedSubject = null;
        selectedSession = null;
        selectedRecording = null;
        currentLevel = "subjects";
        renderLevelChrome();
    }
    if (analysisTargetType === "subject" && analysisTargetRef === s) {
        setAnalysisTarget(null, null);
    }

    renderSubjects();
    renderSessions();
    renderRecordings();
    showToast(`Deleted ${s.name}.`);
}

async function selectSubject(s) {
    selectedSubject = s;
    selectedSession = null;
    selectedRecording = null;
    currentLevel = "sessions";
    renderSubjects();
    renderLevelChrome();
    if (!SESSIONS[s.id]) {
        sessionsListEl.innerHTML = `<div class="box-empty"><div class="empty-title">Loading&hellip;</div></div>`;
    }
    renderRecordings();
    await loadSessionsForSubject(s);
    // The user may have navigated elsewhere while this was in flight.
    if (selectedSubject === s) renderSessions();
}

function renderSessions() {
    const sessions = selectedSubject ? (SESSIONS[selectedSubject.id] || []) : [];
    sessionsListEl.innerHTML = "";

    if (!selectedSubject) {
        sessionsListEl.innerHTML = `<div class="box-empty">
            <div class="empty-title">No subject selected</div>
            <div class="empty-desc">Pick a subject to see their sessions.</div>
        </div>`;
        return;
    }

    sessions.forEach(sess => {
        const el = document.createElement("div");
        el.className = "session-item" + (isAnalysisTarget("session", sess) ? " selected" : "");
        el.innerHTML = `
            <div class="session-info">
                <div class="session-name">${sess.name}</div>
                <div class="session-date">${sess.date}</div>
            </div>
            <button type="button" class="row-ellipsis-btn" title="More options" aria-label="More options">
                <svg width="3" height="15" viewBox="0 0 3 15" fill="currentColor">
                    <circle cx="1.5" cy="1.5" r="1.5"/>
                    <circle cx="1.5" cy="7.5" r="1.5"/>
                    <circle cx="1.5" cy="13.5" r="1.5"/>
                </svg>
            </button>
        `;
        el.addEventListener("click", () => selectSession(sess));
        el.querySelector(".row-ellipsis-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            openRowFlyout(e.currentTarget, [
                { label: "Analyze Session", onClick: () => {
                    closeRecordingSelectDropdown();
                    selectRecordingLabel.textContent = sess.name;
                    setAnalysisTarget("session", sess);
                } },
                { label: "Delete Session", danger: true, onClick: () => {
                    openConfirmDelete(
                        "Delete Session",
                        `This will permanently delete "${sess.name}" and all of its recordings. This can't be undone.`,
                        () => deleteSession(sess)
                    );
                } },
            ]);
        });
        sessionsListEl.appendChild(el);
    });
}

async function deleteSession(sess) {
    if (!selectedSubject) return;
    try {
        await api.deleteSession(sess.id);
    } catch (err) {
        console.error(err);
        showToast(err.message || "Couldn't delete session.");
        return;
    }

    const list = SESSIONS[selectedSubject.id] || [];
    const idx = list.findIndex(x => x.id === sess.id);
    if (idx !== -1) list.splice(idx, 1);
    delete RECORDINGS[sess.id];

    if (selectedSession && selectedSession.id === sess.id) {
        selectedSession = null;
        selectedRecording = null;
        currentLevel = "sessions";
        renderLevelChrome();
    }
    if (analysisTargetType === "session" && analysisTargetRef === sess) {
        setAnalysisTarget(null, null);
    } else if (analysisTargetType === "recording" && analysisTargetRef && analysisTargetRef.sessionId === sess.id) {
        setAnalysisTarget(null, null);
    }

    renderSessions();
    renderRecordings();
    showToast(`Deleted ${sess.name}.`);
}

async function selectSession(sess) {
    selectedSession = sess;
    selectedRecording = null;
    currentLevel = "recordings";
    renderLevelChrome();
    renderSessions();
    if (!RECORDINGS[sess.id]) {
        recordingsListEl.innerHTML = `<div class="box-empty"><div class="empty-title">Loading&hellip;</div></div>`;
    }
    await loadRecordingsForSession(sess);
    // The user may have navigated elsewhere while this was in flight.
    if (selectedSession === sess) renderRecordings();
}

function renderRecordings() {
    const recs = selectedSession ? (RECORDINGS[selectedSession.id] || []) : [];
    recordingsListEl.innerHTML = "";

    if (!selectedSession) {
        recordingsListEl.innerHTML = `<div class="box-empty">
            <div class="empty-title">No session selected</div>
            <div class="empty-desc">Pick a session to see its recordings.</div>
        </div>`;
        return;
    }

    recs.forEach(rec => {
        const row = document.createElement("div");
        row.className = "recording-row";
        row.innerHTML = `
            <div class="recording-item${isAnalysisTarget("recording", rec) ? " selected" : ""}">
                <div class="recording-icon">
                    ${rec.type === 'uploaded' ? `
                    <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                        <path d="M7 9.5V1.5M7 1.5L4 4.5M7 1.5L10 4.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="M1.5 9.5V11a1.5 1.5 0 0 0 1.5 1.5h8a1.5 1.5 0 0 0 1.5-1.5V9.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    ` : `
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                        <path d="M12 1a4 4 0 0 0-4 4v6a4 4 0 0 0 8 0V5a4 4 0 0 0-4-4Z" stroke="currentColor" stroke-width="1.6"/>
                        <path d="M5 11a7 7 0 0 0 14 0M12 18v4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                    </svg>
                    `}
                </div>
                <div class="recording-info">
                    <div class="recording-name">${rec.name}</div>
                    <div class="recording-time">${rec.time}</div>
                </div>
                <div class="recording-chip ${rec.type === 'custom' ? 'custom' : rec.type === 'uploaded' ? 'uploaded' : ''}">${rec.type === 'custom' ? 'User-defined' : rec.type === 'uploaded' ? 'Uploaded' : 'Validated'}</div>
            </div>
        `;
        row.querySelector(".recording-item").addEventListener("click", () => {
            selectedRecording = rec;
            renderRecordings();
            selectRecordingLabel.textContent = rec.name;
            setAnalysisTarget("recording", rec);
            closeRecordingSelectDropdown();
        });
        recordingsListEl.appendChild(row);
    });
}

// ================= Sort (cycles through orders on click, no dropdown) =================

const SORT_ORDER = ["name", "date", "age"];
const SORT_LABELS = { name: "Name", date: "Date Added", age: "Age" };

const sortTrigger = document.getElementById("sort-trigger");
const sortCurrentLabel = document.getElementById("sort-current-label");

function updateSortLabel() {
    const label = SORT_LABELS[currentSort];
    sortCurrentLabel.textContent = label;
    sortTrigger.title = "Sort: " + label + " (click to change)";
}

sortTrigger.addEventListener("click", () => {
    const idx = SORT_ORDER.indexOf(currentSort);
    currentSort = SORT_ORDER[(idx + 1) % SORT_ORDER.length];
    updateSortLabel();
    renderSubjects();
});

// ---------------------------------------------------------------------
// Add-subject modal (same pattern as the existing Add Patient modal)
// ---------------------------------------------------------------------

const subjectModalOverlay = document.getElementById("addSubjectOverlay");
const subjectModalForm = document.getElementById("addSubjectForm");
const subjectModalNameInput = document.getElementById("subjectNameInput");
const subjectModalIdInput = document.getElementById("subjectIdInput");
const subjectModalSexInput = document.getElementById("subjectSexInput");
const subjectModalAgeInput = document.getElementById("subjectAgeInput");
const subjectModalGroupInput = document.getElementById("subjectGroupInput");

function openAddSubjectModal() {
    if (subjectModalForm) subjectModalForm.reset();
    if (subjectModalOverlay) subjectModalOverlay.classList.add("visible");
    if (subjectModalNameInput) subjectModalNameInput.focus();
}

function closeAddSubjectModal() {
    if (subjectModalOverlay) subjectModalOverlay.classList.remove("visible");
}

if (subjectModalForm) {
    subjectModalForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const name = subjectModalNameInput.value.trim();
        if (!name) {
            subjectModalNameInput.focus();
            return;
        }

        const payload = {
            id: subjectModalIdInput.value.trim() || null,
            name,
            age: subjectModalAgeInput.value || "",
            sex: subjectModalSexInput.value,
            group: subjectModalGroupInput.value.trim(),
        };

        let created;
        try {
            created = await api.createSubject(payload);
        } catch (err) {
            console.error(err);
            showToast(err.message || "Couldn't add subject.");
            return;
        }

        const newSubject = mapSubject(created);
        SUBJECTS.push(newSubject);

        closeAddSubjectModal();
        renderSubjects();
    });
}

document.getElementById("addSubjectCancel")?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeAddSubjectModal();
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && subjectModalOverlay && subjectModalOverlay.classList.contains("visible")) {
        closeAddSubjectModal();
    }
});

document.getElementById("add-subject-btn").addEventListener("click", openAddSubjectModal);

// ---------------------------------------------------------------------
// Add-session modal (same modal pattern; name is the only editable
// field -- date and session numbering are fixed/auto-generated)
// ---------------------------------------------------------------------

const sessionModalOverlay = document.getElementById("addSessionOverlay");
const sessionModalForm = document.getElementById("addSessionForm");
const sessionModalNameInput = document.getElementById("sessionNameInput");

function openAddSessionModal() {
    if (!selectedSubject) {
        showToast("Select a subject first.");
        return;
    }
    if (sessionModalForm) sessionModalForm.reset();
    if (sessionModalOverlay) sessionModalOverlay.classList.add("visible");
    if (sessionModalNameInput) sessionModalNameInput.focus();
}

function closeAddSessionModal() {
    if (sessionModalOverlay) sessionModalOverlay.classList.remove("visible");
}

function formatSessionDate(date) {
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

if (sessionModalForm) {
    sessionModalForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!selectedSubject) return;

        const subjectId = selectedSubject.id;
        const customName = sessionModalNameInput.value.trim();

        let created;
        try {
            created = await api.createSession(subjectId, { name: customName || null });
        } catch (err) {
            console.error(err);
            showToast(err.message || "Couldn't add session.");
            return;
        }

        const newSession = mapSession(created);
        if (!SESSIONS[subjectId]) SESSIONS[subjectId] = [];
        SESSIONS[subjectId].push(newSession);

        closeAddSessionModal();
        renderSessions();
    });
}

document.getElementById("addSessionCancel")?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeAddSessionModal();
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && sessionModalOverlay && sessionModalOverlay.classList.contains("visible")) {
        closeAddSessionModal();
    }
});

document.getElementById("add-session-btn").addEventListener("click", openAddSessionModal);

// ---------------------------------------------------------------------
// Add-recording modal (same pattern; task picker with a custom-name
// field that appears when "Custom Task..." is selected)
// ---------------------------------------------------------------------

const recordingModalOverlay = document.getElementById("addRecordingOverlay");
const recordingModalForm = document.getElementById("addRecordingForm");
const recordingTaskSelect = document.getElementById("recordingTaskInput");
const recordingCustomNameField = document.getElementById("recordingCustomNameField");
const recordingCustomNameInput = document.getElementById("recordingCustomNameInput");

function updateRecordingCustomFieldVisibility() {
    if (!recordingTaskSelect || !recordingCustomNameField) return;
    const isCustom = recordingTaskSelect.value === "__custom__";
    recordingCustomNameField.style.display = isCustom ? "flex" : "none";
}

recordingTaskSelect?.addEventListener("change", updateRecordingCustomFieldVisibility);

// ---- Task type toggle (Sustained vowel / DDK) in the new-recording modal ----

const taskTypeToggle = document.getElementById("taskTypeToggle");
const taskPromptLabel = document.getElementById("taskPromptLabel");
const taskPromptSound = document.getElementById("taskPromptSound");
const taskDurationValue = document.getElementById("taskDurationValue");
const taskDurationMinus = document.getElementById("taskDurationMinus");
const taskDurationPlus = document.getElementById("taskDurationPlus");
const taskDurationGroup = document.querySelector(".task-duration");

const TASK_TYPE_LABELS = {
    Sustained: "Sustained Vowel /a/",
    DDK: "DDK /pa-ta-ka/",
};

// Short task labels used on the post-recording quality review card
// (distinct from TASK_TYPE_LABELS, which include the phoneme prompt).
const QUALITY_REVIEW_TASK_LABELS = {
    Sustained: "Sustained Vowel",
    DDK: "DDK Task",
};

const TASK_PROMPTS = {
    Sustained: { label: "Hold", sound: "/a/" },
    DDK: { label: "Repeat", sound: "/pa-ta-ka/" },
};

const TASK_DEFAULT_DURATIONS = {
    Sustained: 5,
    DDK: 10,
};

const DURATION_MIN = 1;
const DURATION_MAX = 60;
const DURATION_STEP = 1;

let selectedRecordingTaskType = "Sustained";
let selectedRecordingDuration = TASK_DEFAULT_DURATIONS.Sustained;

function updateDurationDisplay() {
    if (taskDurationValue) taskDurationValue.textContent = selectedRecordingDuration + "s";
    if (taskDurationMinus) taskDurationMinus.disabled = selectedRecordingDuration <= DURATION_MIN;
    if (taskDurationPlus) taskDurationPlus.disabled = selectedRecordingDuration >= DURATION_MAX;
}

function setRecordingDuration(seconds) {
    selectedRecordingDuration = Math.min(DURATION_MAX, Math.max(DURATION_MIN, seconds));
    updateDurationDisplay();
}

function setRecordingTaskType(taskType) {
    if (!TASK_TYPE_LABELS[taskType]) return;
    selectedRecordingTaskType = taskType;

    taskTypeToggle?.querySelectorAll(".task-type-option").forEach((btn) => {
        const isActive = btn.dataset.taskType === taskType;
        btn.classList.toggle("is-active", isActive);
        btn.setAttribute("aria-selected", isActive ? "true" : "false");
    });

    const prompt = TASK_PROMPTS[taskType];
    if (taskPromptLabel) taskPromptLabel.textContent = prompt.label;
    if (taskPromptSound) taskPromptSound.textContent = prompt.sound;

    setRecordingDuration(TASK_DEFAULT_DURATIONS[taskType]);
}

taskTypeToggle?.addEventListener("click", (e) => {
    const btn = e.target.closest(".task-type-option");
    if (!btn) return;
    setRecordingTaskType(btn.dataset.taskType);
});

taskDurationMinus?.addEventListener("click", () => {
    setRecordingDuration(selectedRecordingDuration - DURATION_STEP);
});

taskDurationPlus?.addEventListener("click", () => {
    setRecordingDuration(selectedRecordingDuration + DURATION_STEP);
});

// ---- Record button: recording status line + dotted meter + progress bar ----
// No real audio/backend yet — this simulates what recording will look like
// once wired up: a "Recording · <Task> Task" status line with an elapsed
// timer, a row of level ticks that fill in over time, and a progress bar
// that fills up to the chosen duration.

const taskRecordBtn = document.getElementById("taskRecordBtn");
const taskRecordSlot = document.getElementById("taskRecordSlot");
const taskPrompt = document.getElementById("taskPrompt");
const recordingStatusLine = document.getElementById("recordingStatusLine");
const recordingStatusTaskLabel = document.getElementById("recordingStatusTaskLabel");
const recordingStatusTimer = document.getElementById("recordingStatusTimer");
const recordingMeter = document.getElementById("recordingMeter");
const recordingDottedRow = document.getElementById("recordingDottedRow");
const recordingProgressFill = document.getElementById("recordingProgressFill");

const RECORDING_STATUS_LABELS = {
    Sustained: "Sustained",
    DDK: "DDK",
};

const DOT_COUNT = 48;

let isRecordingActive = false;
let recordingRafId = null;
let recordingStartTs = 0;
let dotTickEls = [];

// Placeholder waveform heights (0-1). Not derived from real audio yet —
// this just gives the meter a waveform-like silhouette until live level
// data is wired up. Swap buildDotTicks() for real amplitude data later.
function placeholderWaveformHeights(count) {
    return Array.from({ length: count }, (_, i) => {
        const t = i / (count - 1);
        const envelope = 0.25 + 0.55 * Math.sin(Math.PI * t) ** 0.6;
        const wobble =
            0.5 +
            0.5 * Math.sin(i * 1.7) * Math.sin(i * 0.35 + 1) +
            0.15 * Math.sin(i * 5.1);
        return Math.min(1, Math.max(0.08, envelope * wobble));
    });
}

function buildDotTicks() {
    if (!recordingDottedRow) return;
    recordingDottedRow.innerHTML = "";
    const heights = placeholderWaveformHeights(DOT_COUNT);
    dotTickEls = heights.map((h) => {
        const el = document.createElement("span");
        el.className = "recording-dot-tick";
        el.style.setProperty("--bar-h", h.toFixed(3));
        recordingDottedRow.appendChild(el);
        return el;
    });
}
buildDotTicks();

function formatElapsed(ms) {
    const totalSeconds = Math.floor(ms / 1000);
    const m = Math.floor(totalSeconds / 60);
    const s = totalSeconds % 60;
    return m + ":" + String(s).padStart(2, "0");
}

function setRecordingControlsDisabled(disabled) {
    taskTypeToggle?.querySelectorAll(".task-type-option").forEach((btn) => { btn.disabled = disabled; });
    if (taskDurationMinus) taskDurationMinus.disabled = disabled || selectedRecordingDuration <= DURATION_MIN;
    if (taskDurationPlus) taskDurationPlus.disabled = disabled || selectedRecordingDuration >= DURATION_MAX;
    taskDurationGroup?.classList.toggle("is-disabled", disabled);
}

// The live-recording backend call (POST /api/sessions/{id}/recordings)
// actually captures audio for `duration` seconds server-side, which lines
// up with the local countdown/progress-bar animation below running for
// the same duration -- so the request is fired the moment the visual
// recording starts, and its result is awaited once the animation finishes.
let pendingLiveRecording = null;

function startTaskRecording(prepareToken) {
    if (!taskRecordBtn || isRecordingActive) return;

    isRecordingActive = true;
    recordingStartTs = performance.now();

    const taskLabel = selectedRecordingTaskType === "DDK" ? "DDK" : "Sustained Vowel";
    pendingLiveRecording = selectedSession
        ? api.addLiveRecording(selectedSession.id, taskLabel, selectedRecordingDuration, prepareToken)
        : Promise.reject(new Error("Select a session first."));
    // Swallowed here so an unhandled-rejection warning can't fire before
    // finishTaskRecording gets a chance to inspect the real result below.
    pendingLiveRecording.catch(() => {});

    if (recordingStatusTaskLabel) recordingStatusTaskLabel.textContent = RECORDING_STATUS_LABELS[selectedRecordingTaskType];
    if (recordingStatusTimer) recordingStatusTimer.textContent = formatElapsed(selectedRecordingDuration * 1000);
    if (recordingProgressFill) recordingProgressFill.style.width = "0%";
    dotTickEls.forEach((el) => el.classList.remove("is-filled"));

    taskRecordBtn.classList.add("is-recording");
    taskRecordBtn.title = "Tap to stop recording";
    recordingStatusLine?.classList.add("is-active");
    recordingMeter?.classList.add("is-active");
    setRecordingControlsDisabled(true);
    // Nothing is shown in the record slot while actively recording (the
    // button hides via .is-recording, no countdown/done circle is active),
    // so collapse the slot itself rather than leaving an empty gap.
    if (taskRecordSlot) taskRecordSlot.style.display = "none";

    const totalMs = selectedRecordingDuration * 1000;

    function tick(now) {
        const elapsed = now - recordingStartTs;
        const progress = Math.min(1, elapsed / totalMs);

        if (recordingStatusTimer) recordingStatusTimer.textContent = formatElapsed(totalMs - Math.min(elapsed, totalMs));
        if (recordingProgressFill) recordingProgressFill.style.width = (progress * 100) + "%";

        const filledCount = Math.round(progress * DOT_COUNT);
        dotTickEls.forEach((el, i) => el.classList.toggle("is-filled", i < filledCount));

        if (progress < 1) {
            recordingRafId = requestAnimationFrame(tick);
        } else {
            finishTaskRecording(false);
        }
    }
    recordingRafId = requestAnimationFrame(tick);
}

async function finishTaskRecording(cancelled) {
    if (!isRecordingActive) return;
    isRecordingActive = false;

    if (recordingRafId) cancelAnimationFrame(recordingRafId);
    recordingRafId = null;

    const requestPromise = pendingLiveRecording;
    const sessionAtStart = selectedSession;
    pendingLiveRecording = null;

    if (taskRecordBtn) {
        taskRecordBtn.classList.remove("is-recording");
        taskRecordBtn.title = "Tap to start recording";
    }
    if (taskRecordSlot) taskRecordSlot.style.display = "";
    recordingStatusLine?.classList.remove("is-active");
    recordingMeter?.classList.remove("is-active");
    setRecordingControlsDisabled(false);
    updateDurationDisplay();

    if (cancelled) {
        showToast("Recording cancelled");
        // The hardware capture (if it actually started) can't be aborted
        // mid-flight -- it keeps recording server-side for the full
        // duration regardless of the button tap. Let that request land in
        // the background and just delete whatever it logged, so a
        // cancelled take never shows up in the recordings list.
        if (requestPromise && sessionAtStart) {
            requestPromise
                .then((row) => api.deleteRecording(sessionAtStart.id, row.recording_id))
                .catch(() => {});
        }
        return;
    }

    // Hide the record button/prompt while the take is under review
    // (either the quality-check flow below, or — if there's no session
    // to log against — the plain "done" confirmation).
    if (taskRecordBtn) taskRecordBtn.style.display = "none";
    taskPrompt?.classList.add("is-hidden");

    if (!sessionAtStart) {
        showToast("Select a session first.");
        showRecordingCompleteTick();
        return;
    }

    showQualityCheckLoading();

    let row;
    try {
        row = await requestPromise;
    } catch (err) {
        console.error(err);
        hideQualityCheck();
        if (taskRecordBtn) taskRecordBtn.style.display = "";
        taskPrompt?.classList.remove("is-hidden");
        showToast(err.message || "Recording failed.");
        return;
    }

    const newRecording = mapRecording(row);
    const sessionId = sessionAtStart.id;
    if (!RECORDINGS[sessionId]) RECORDINGS[sessionId] = [];
    RECORDINGS[sessionId].push(newRecording);
    if (selectedSession && selectedSession.id === sessionId) {
        selectedRecording = newRecording;
        renderRecordings();
    }
    invalidateSessionAnalysisCache(sessionId);
    addRecordingLogEntry(newRecording);

    showQualityCheckResult(newRecording);
}

// ---------- Post-recording quality check (chain-of-custody + signal
// quality) ----------
//
// Runs right after a take finishes and before the "Recording complete"
// confirmation: a loading stage while the backend's analysis result is
// awaited, then a review card (real per-recording rating + environment
// copy from quality_classification) where the user keeps (Complete) or
// discards (Re-record) the take.
const qualityCheckOverlay = document.getElementById("qualityCheckOverlay");
const qualityReviewTaskLabel = document.getElementById("qualityReviewTaskLabel");
const qualityReviewStars = document.getElementById("qualityReviewStars");
const qualityReviewEnvTitle = document.getElementById("qualityReviewEnvTitle");
const qualityReviewEnvDesc = document.getElementById("qualityReviewEnvDesc");
const qualityReviewRerecordBtn = document.getElementById("qualityReviewRerecordBtn");
const qualityReviewCompleteBtn = document.getElementById("qualityReviewCompleteBtn");

function renderQualityStars(rating, max) {
    let html = "";
    for (let i = 1; i <= max; i++) {
        html += `<span class="${i <= rating ? "star-filled" : "star-empty"}">${i <= rating ? "\u2605" : "\u2606"}</span>`;
    }
    return html;
}

// Recording Quality Rating comes back from the backend as a star string,
// e.g. "★★★★☆" -- counting the filled glyph gives the 0-5 rating.
function starCountFromRatingString(ratingStr) {
    if (typeof ratingStr !== "string") return 0;
    return (ratingStr.match(/\u2605/g) || []).length;
}

function showQualityCheckLoading() {
    if (!qualityCheckOverlay) return;
    if (qualityReviewTaskLabel) {
        qualityReviewTaskLabel.textContent = QUALITY_REVIEW_TASK_LABELS[selectedRecordingTaskType];
    }
    qualityCheckOverlay.classList.remove("stage-review");
    qualityCheckOverlay.classList.add("is-active", "stage-loading");
}

function showQualityCheckResult(recording) {
    if (!qualityCheckOverlay) {
        showRecordingCompleteTick();
        return;
    }

    const qc = recording._raw && recording._raw.quality_classification;
    if (!qc) {
        // No ambient channel / the quality analysis step failed silently
        // server-side for this take (see api/routes.py) -- skip the
        // review card and fall straight to the plain confirmation.
        hideQualityCheck();
        showRecordingCompleteTick();
        return;
    }

    const rating = starCountFromRatingString(qc["Recording Quality Rating"]);
    if (qualityReviewStars) qualityReviewStars.innerHTML = renderQualityStars(rating, 5);
    if (qualityReviewEnvTitle) qualityReviewEnvTitle.textContent = qc["Environment"] || "";
    if (qualityReviewEnvDesc) qualityReviewEnvDesc.textContent = qc["Recommendation"] || "";

    qualityCheckOverlay.classList.remove("stage-loading");
    qualityCheckOverlay.classList.add("stage-review");
}

function hideQualityCheck() {
    qualityCheckOverlay?.classList.remove("is-active", "stage-loading", "stage-review");
}

// Shows the brief green-check "Recording complete" confirmation in the
// record button's spot, then reveals the button and prompt again.
function showRecordingCompleteTick() {
    if (taskRecordBtn) taskRecordBtn.style.display = "none";
    taskPrompt?.classList.add("is-hidden");
    taskDoneCircle?.classList.add("is-active");
    taskDoneLabel?.classList.add("is-active");
    showToast("Recording captured & logged");
    clearTimeout(doneOverlayTimeoutId);
    doneOverlayTimeoutId = setTimeout(() => {
        taskDoneCircle?.classList.remove("is-active");
        taskDoneLabel?.classList.remove("is-active");
        if (taskRecordBtn) taskRecordBtn.style.display = "";
        taskPrompt?.classList.remove("is-hidden");
    }, 1400);
}

// Discards the take just logged (user chose Re-record on the quality
// review card): deletes it from the backend too, so it doesn't linger in
// storage or count toward the session's mean/SD, then returns the panel
// to its ready-to-record state.
async function discardLastRecordingAndReset() {
    if (selectedSession) {
        const sessionId = selectedSession.id;
        const list = RECORDINGS[sessionId];
        if (list && list.length) {
            const removed = list.pop();
            try {
                await api.deleteRecording(sessionId, removed.id);
            } catch (err) {
                console.error(err);
            }
            selectedRecording = list.length ? list[list.length - 1] : null;
            if (analysisTargetType === "recording" && analysisTargetRef === removed) {
                setAnalysisTarget(null, null);
            }
            if (selectedSession && selectedSession.id === sessionId) renderRecordings();
            invalidateSessionAnalysisCache(sessionId);
            removeLastRecordingLogEntry();
        }
    }
    if (taskRecordBtn) taskRecordBtn.style.display = "";
    taskPrompt?.classList.remove("is-hidden");
    showToast("Recording discarded — try again");
}

qualityReviewCompleteBtn?.addEventListener("click", () => {
    hideQualityCheck();
    showRecordingCompleteTick();
});

qualityReviewRerecordBtn?.addEventListener("click", () => {
    hideQualityCheck();
    discardLastRecordingAndReset();
});

const taskCountdownCircle = document.getElementById("taskCountdownCircle");
const taskCountdownNumber = document.getElementById("taskCountdownNumber");
const taskCountdownLabel = document.getElementById("taskCountdownLabel");
const taskDoneCircle = document.getElementById("taskDoneCircle");
const taskDoneLabel = document.getElementById("taskDoneLabel");
let doneOverlayTimeoutId = null;

let countdownTimeoutId = null;
let isCountingDown = false;

// Holds the in-flight (or resolved) api.prepareRecording() promise for
// the countdown currently running, so cancelPreRecordCountdown can
// release it if the user backs out before it's consumed.
let pendingPrepareToken = null;
let pendingPreparePromise = null;

function runPreRecordCountdown(onDone) {
    // If the warm-up below fails (e.g. the serial port won't open
    // because the device isn't connected), we abort the countdown
    // and report it right away instead of letting the countdown +
    // recording animation play out for several more seconds only to
    // fail at the very end.
    let aborted = false;

    // Kick the serial warm-up off immediately, in parallel with the
    // visible countdown, instead of waiting until the countdown ends
    // to open+settle the connection. The device's ~2s settle time
    // then happens *during* the countdown the user is already looking
    // at, rather than as an invisible delay after it -- which is what
    // previously made real recording start (and, since a fixed
    // duration's worth of samples gets read, end) run late relative
    // to the on-screen countdown/progress bar. It also means a
    // hardware failure is caught right here, up front.
    pendingPrepareToken = null;
    pendingPreparePromise = api.prepareRecording()
        .then((res) => { pendingPrepareToken = res && res.token; return pendingPrepareToken; })
        .catch((err) => {
            aborted = true;
            pendingPreparePromise = null;
            pendingPrepareToken = null;
            cancelPreRecordCountdown();
            showToast(err.message || "Recording hardware not available.");
            return null;
        });

    if (!taskCountdownCircle || !taskCountdownNumber) {
        pendingPreparePromise.then((token) => { if (!aborted) onDone(token); });
        return;
    }

    isCountingDown = true;
    let count = 3;

    clearTimeout(doneOverlayTimeoutId);
    taskDoneCircle?.classList.remove("is-active");
    taskDoneLabel?.classList.remove("is-active");
    if (taskRecordBtn) taskRecordBtn.style.display = "none";
    setRecordingControlsDisabled(true);
    taskCountdownNumber.textContent = String(count);
    taskCountdownCircle.classList.add("is-active");
    taskCountdownLabel?.classList.add("is-active");

    function step() {
        if (aborted) return;
        count -= 1;
        if (count > 0) {
            taskCountdownNumber.textContent = String(count);
            // restart the pop animation on each tick
            taskCountdownNumber.style.animation = "none";
            void taskCountdownNumber.offsetWidth;
            taskCountdownNumber.style.animation = "";
            countdownTimeoutId = setTimeout(step, 1000);
        } else {
            taskCountdownCircle.classList.remove("is-active");
            taskCountdownLabel?.classList.remove("is-active");
            if (taskRecordBtn) taskRecordBtn.style.display = "";
            isCountingDown = false;
            countdownTimeoutId = null;
            // The countdown's own 3s normally comfortably outlasts the
            // ~2s warm-up, so this resolves immediately in practice --
            // it only actually waits if the warm-up is unusually slow,
            // which is the correct tradeoff: better to hold the
            // "recording" state a beat than to start it before the mic
            // is really ready.
            const preparePromise = pendingPreparePromise;
            pendingPreparePromise = null;
            if (!preparePromise) return; // already aborted above
            preparePromise.then((token) => {
                pendingPrepareToken = null;
                if (!aborted) onDone(token);
            });
        }
    }
    countdownTimeoutId = setTimeout(step, 1000);
}

function cancelPreRecordCountdown() {
    if (pendingPreparePromise) {
        pendingPreparePromise.then((token) => {
            if (token) api.releaseRecordingPrepare(token).catch(() => {});
        });
        pendingPreparePromise = null;
    } else if (pendingPrepareToken) {
        api.releaseRecordingPrepare(pendingPrepareToken).catch(() => {});
    }
    pendingPrepareToken = null;

    if (!isCountingDown) return;
    isCountingDown = false;
    if (countdownTimeoutId) clearTimeout(countdownTimeoutId);
    countdownTimeoutId = null;
    taskCountdownCircle?.classList.remove("is-active");
    taskCountdownLabel?.classList.remove("is-active");
    if (taskRecordBtn) taskRecordBtn.style.display = "";
    setRecordingControlsDisabled(false);
}

taskRecordBtn?.addEventListener("click", () => {
    if (isRecordingActive || isCountingDown) {
        finishTaskRecording(true);
        cancelPreRecordCountdown();
    } else {
        runPreRecordCountdown(startTaskRecording);
    }
});

// The record button is hidden while recording (see .task-record-btn.is-recording),
// so the status line itself becomes the tap target to stop.
recordingStatusLine?.addEventListener("click", () => {
    if (isRecordingActive) finishTaskRecording(true);
});

function openAddRecordingModal() {
    if (!selectedSession) {
        showToast("Select a session first.");
        return;
    }
    if (recordingModalForm) recordingModalForm.reset();
    updateRecordingCustomFieldVisibility();
    setRecordingTaskType("Sustained");
    clearRecordingLog();
    if (recordingModalOverlay) recordingModalOverlay.classList.add("visible");
    if (recordingTaskSelect) recordingTaskSelect.focus();
}

function closeAddRecordingModal() {
    finishTaskRecording(true);
    if (recordingModalOverlay) recordingModalOverlay.classList.remove("visible");
}

function formatRecordingTime(date) {
    return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

// ---- Live recording log (top-left box in the New Recording modal) ----
// Shows the takes captured during this modal session, newest first.
// Populated as each recording lands (finishTaskRecording), trimmed if the
// user discards a take on the quality review card (discardLastRecordingAndReset).
const recordingLogBox = document.getElementById("recordingLogBox");
const recordingLogList = document.getElementById("recordingLogList");
const CHECK_ICON_SVG = '<svg viewBox="0 0 24 24" fill="none"><path d="M5 12.5l4.5 4.5L19 7" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const TRASH_ICON_SVG = '<svg viewBox="0 0 24 24" fill="none"><path d="M4 7h16M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2m2 0v13a2 2 0 01-2 2H9a2 2 0 01-2-2V7h10zM10 11v6M14 11v6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function updateRecordingLogEmptyState() {
    if (!recordingLogBox || !recordingLogList) return;
    recordingLogBox.classList.toggle("is-empty", recordingLogList.children.length === 0);
}

function addRecordingLogEntry(recording) {
    if (!recordingLogList) return;
    const li = document.createElement("li");
    li.className = "recording-log-item";
    const label = recording.name || TASK_TYPE_LABELS[selectedRecordingTaskType] || "Recording";
    const time = recording.time || formatRecordingTime(new Date());
    li.innerHTML = `
        <div class="recording-log-item-main">
            <span class="recording-log-item-check">${CHECK_ICON_SVG}</span>
            <span class="recording-log-item-name">${label}</span>
        </div>
        <div class="recording-log-item-right">
            <span class="recording-log-item-time">${time}</span>
            <button type="button" class="recording-log-item-delete" title="Delete recording" aria-label="Delete recording">${TRASH_ICON_SVG}</button>
        </div>
    `;
    li.querySelector(".recording-log-item-delete")?.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteRecordingLogEntry(recording, li);
    });
    // column-reverse list, so prepending in DOM order puts the newest at
    // the bottom of the source but the top of the rendered list.
    recordingLogList.appendChild(li);
    updateRecordingLogEmptyState();
}

function removeLastRecordingLogEntry() {
    if (!recordingLogList || !recordingLogList.lastElementChild) return;
    recordingLogList.lastElementChild.remove();
    updateRecordingLogEmptyState();
}

// Deletes a single logged recording via its own trash button (as opposed
// to removeLastRecordingLogEntry, which only ever trims the most recent
// take from the Re-record flow). Mirrors discardLastRecordingAndReset's
// cleanup — backend delete, RECORDINGS/selection/analysis-cache upkeep —
// but works for any entry in the log, not just the last one.
async function deleteRecordingLogEntry(recording, li) {
    if (!recording || !recording.id) return;
    const sessionId = recording.sessionId;
    try {
        await api.deleteRecording(sessionId, recording.id);
    } catch (err) {
        console.error(err);
        showToast(err.message || "Couldn't delete recording.");
        return;
    }
    const list = RECORDINGS[sessionId];
    if (list) {
        const idx = list.indexOf(recording);
        if (idx !== -1) list.splice(idx, 1);
    }
    if (selectedRecording === recording) {
        selectedRecording = list && list.length ? list[list.length - 1] : null;
    }
    if (analysisTargetType === "recording" && analysisTargetRef === recording) {
        setAnalysisTarget(null, null);
    }
    if (selectedSession && selectedSession.id === sessionId) renderRecordings();
    invalidateSessionAnalysisCache(sessionId);
    li.remove();
    updateRecordingLogEmptyState();
    showToast("Recording deleted");
}

function clearRecordingLog() {
    if (!recordingLogList) return;
    recordingLogList.innerHTML = "";
    updateRecordingLogEmptyState();
}

if (recordingModalForm) {
    recordingModalForm.addEventListener("submit", (e) => {
        e.preventDefault();
        if (!selectedSession) return;

        const isCustom = recordingTaskSelect.value === "__custom__";
        const name = isCustom
            ? recordingCustomNameInput.value.trim()
            : (recordingTaskSelect.value || TASK_TYPE_LABELS[selectedRecordingTaskType]);

        if (!name) {
            recordingCustomNameInput.focus();
            return;
        }

        const newRecording = {
            name,
            time: formatRecordingTime(new Date()),
            type: isCustom ? "custom" : "built-in",
            duration: selectedRecordingDuration,
        };

        const sessionId = selectedSession.id;
        if (!RECORDINGS[sessionId]) RECORDINGS[sessionId] = [];
        RECORDINGS[sessionId].push(newRecording);

        closeAddRecordingModal();
        selectedRecording = newRecording;
        renderRecordings();
    });
}

document.getElementById("recordingModalBack")?.addEventListener("click", closeAddRecordingModal);

// "Extract Features" button (top-right of the recording modal, same row
// as Back) -- batch-runs preprocessing + feature extraction over every
// recording logged so far this session that's still pending it. Takes
// are logged with features={} the instant they're quality-confirmed
// (see add_live_recording in api/routes.py), so this is what actually
// gets them analyzed and reflected in the main Sustained/DDK views.
const recordingModalExtractBtn = document.getElementById("recordingModalExtractBtn");
const recordingModalExtractBtnLabel = document.getElementById("recordingModalExtractBtnLabel");

recordingModalExtractBtn?.addEventListener("click", async () => {
    if (!selectedSession || recordingModalExtractBtn.disabled) return;
    const sessionId = selectedSession.id;

    recordingModalExtractBtn.disabled = true;
    recordingModalExtractBtn.classList.add("is-extracting");
    if (recordingModalExtractBtnLabel) recordingModalExtractBtnLabel.textContent = "Extracting…";

    try {
        const result = await api.extractSessionFeatures(sessionId);
        const updatedCount = result?.updated?.length || 0;
        const errorCount = result?.errors?.length || 0;

        if (updatedCount > 0) {
            await loadRecordingsForSession(selectedSession, { force: true });
            if (selectedSession && selectedSession.id === sessionId) renderRecordings();
            invalidateSessionAnalysisCache(sessionId);
        }

        if (errorCount > 0) {
            showToast(updatedCount > 0
                ? `Extracted ${updatedCount} recording${updatedCount === 1 ? "" : "s"}, ${errorCount} failed`
                : "Feature extraction failed for all pending recordings");
        } else if (updatedCount > 0) {
            showToast(`Extracted ${updatedCount} recording${updatedCount === 1 ? "" : "s"}`);
        } else {
            showToast("No recordings pending extraction");
        }

        // Extraction ran to completion (whether or not every recording
        // succeeded) -- close the recording window now that the user's
        // been told the outcome. A thrown/network error skips this and
        // leaves the modal open so they can retry.
        closeAddRecordingModal();
    } catch (err) {
        console.error(err);
        showToast(err.message || "Couldn't extract features.");
    } finally {
        recordingModalExtractBtn.disabled = false;
        recordingModalExtractBtn.classList.remove("is-extracting");
        if (recordingModalExtractBtnLabel) recordingModalExtractBtnLabel.textContent = "Extract Features";
    }
});


document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && recordingModalOverlay && recordingModalOverlay.classList.contains("visible")) {
        closeAddRecordingModal();
    }
});

// ---- New-recording flyout: + button opens a sideways menu with
// "Live Recording" (existing modal flow) and "Upload" (UI only, not
// wired up yet). ----

const addRecordingFlyout = document.getElementById("add-recording-flyout");

function openAddRecordingFlyout() {
    addRecordingFlyout.classList.add("open");
}

function closeAddRecordingFlyout() {
    addRecordingFlyout.classList.remove("open");
}

addRecordingBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!selectedSession) {
        showToast("Select a session first.");
        return;
    }
    if (addRecordingFlyout.classList.contains("open")) {
        closeAddRecordingFlyout();
    } else {
        openAddRecordingFlyout();
    }
});

document.getElementById("add-recording-live-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    closeAddRecordingFlyout();
    openAddRecordingModal();
});

document.getElementById("add-recording-upload-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    closeAddRecordingFlyout();
    openUploadTaskModal();
});

// ---------------------------------------------------------------------
// Upload flow: task-type picker modal -> native file picker -> POST to
// the upload endpoint. All files picked in one go share the same task
// type (the backend's upload endpoint takes one `task` per call).
// ---------------------------------------------------------------------

const uploadTaskOverlay = document.getElementById("uploadTaskOverlay");
const uploadTaskTypeToggle = document.getElementById("uploadTaskTypeToggle");
const uploadTaskCancelBtn = document.getElementById("uploadTaskCancel");
const uploadTaskContinueBtn = document.getElementById("uploadTaskContinue");
const uploadRecordingInput = document.getElementById("uploadRecordingInput");

let uploadTaskType = "Sustained";

function setUploadTaskType(taskType) {
    uploadTaskType = taskType;
    uploadTaskTypeToggle?.querySelectorAll(".task-type-option").forEach((btn) => {
        const isActive = btn.dataset.taskType === taskType;
        btn.classList.toggle("is-active", isActive);
        btn.setAttribute("aria-selected", isActive ? "true" : "false");
    });
}

uploadTaskTypeToggle?.addEventListener("click", (e) => {
    const btn = e.target.closest(".task-type-option");
    if (!btn) return;
    setUploadTaskType(btn.dataset.taskType);
});

function openUploadTaskModal() {
    if (!selectedSession) {
        showToast("Select a session first.");
        return;
    }
    setUploadTaskType("Sustained");
    uploadTaskOverlay?.classList.add("visible");
}

function closeUploadTaskModal() {
    uploadTaskOverlay?.classList.remove("visible");
}

uploadTaskCancelBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeUploadTaskModal();
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && uploadTaskOverlay && uploadTaskOverlay.classList.contains("visible")) {
        closeUploadTaskModal();
    }
});

uploadTaskOverlay?.addEventListener("click", (e) => e.stopPropagation());

uploadTaskContinueBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeUploadTaskModal();
    uploadRecordingInput.value = "";
    uploadRecordingInput.click();
});

uploadRecordingInput?.addEventListener("change", async () => {
    const files = uploadRecordingInput.files;
    if (!files || !files.length || !selectedSession) return;

    const sessionId = selectedSession.id;
    const taskLabel = uploadTaskType === "DDK" ? "DDK" : "Sustained Vowel";
    showToast(`Uploading ${files.length} recording${files.length > 1 ? "s" : ""}\u2026`);

    let created;
    try {
        created = await api.uploadRecordings(sessionId, taskLabel, files);
    } catch (err) {
        console.error(err);
        showToast(err.message || "Upload failed.");
        return;
    }

    const newRecordings = created.map(mapRecording);
    if (!RECORDINGS[sessionId]) RECORDINGS[sessionId] = [];
    RECORDINGS[sessionId].push(...newRecordings);
    if (selectedSession && selectedSession.id === sessionId) renderRecordings();
    invalidateSessionAnalysisCache(sessionId);
    showToast(`${newRecordings.length} recording${newRecordings.length > 1 ? "s" : ""} uploaded & logged`);
});

addRecordingFlyout.addEventListener("click", (e) => e.stopPropagation());

document.addEventListener("click", () => {
    closeAddRecordingFlyout();
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAddRecordingFlyout();
});

// ================= Recording-select dropdown (Subjects -> Sessions ->
// Recordings drill-down, opened from the menubar) =================

const selectRecordingBtn = document.getElementById("select-recording-btn");
const selectRecordingLabel = document.getElementById("select-recording-label");
const recordingSelectDropdown = document.getElementById("recording-select-dropdown");

updateWidgetButtonsAvailability();

function openRecordingSelectDropdown() {
    document.querySelectorAll(".menubar-menu.open").forEach(m => m.classList.remove("open"));
    if (typeof window.closeAllTypeDropdowns === "function") window.closeAllTypeDropdowns();
    recordingSelectDropdown.classList.add("open");
}

function closeRecordingSelectDropdown() {
    recordingSelectDropdown.classList.remove("open");
}
window.closeRecordingSelectDropdown = closeRecordingSelectDropdown;

selectRecordingBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = recordingSelectDropdown.classList.contains("open");
    if (isOpen) {
        closeRecordingSelectDropdown();
    } else {
        openRecordingSelectDropdown();
    }
});

recordingSelectDropdown.addEventListener("click", (e) => e.stopPropagation());

function isInsideOpenModal(target) {
    if (!target.closest) return false;
    const overlay = target.closest(".subject-modal-overlay");
    return !!(overlay && overlay.classList.contains("visible"));
}

document.addEventListener("click", (e) => {
    // Any click inside an open modal (backdrop or panel) shouldn't do
    // anything else — in particular it shouldn't close the
    // recording-select dropdown.
    if (isInsideOpenModal(e.target)) return;
    closeRecordingSelectDropdown();
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeRecordingSelectDropdown();
});

// ================= Menubar dropdowns (File / Edit / View / Help / Developer) =================

document.querySelectorAll(".menubar-menu").forEach(menu => {
    const trigger = menu.querySelector(".menubar-item, #profile-btn");
    trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        const isOpen = menu.classList.contains("open");
        document.querySelectorAll(".menubar-menu.open").forEach(m => m.classList.remove("open"));
        if (!isOpen) menu.classList.add("open");
        closeRecordingSelectDropdown();
    });
    menu.querySelectorAll(".menubar-dropdown-item").forEach(item => {
        item.addEventListener("click", () => {
            menu.classList.remove("open");
        });
    });
});

document.addEventListener("click", () => {
    document.querySelectorAll(".menubar-menu.open").forEach(m => m.classList.remove("open"));
});

// ================= Developer menu: Custom Script / Upload Custom Script =================
// (Dropdown closing itself is already handled by the generic
// ".menubar-dropdown-item" click listener registered above.)

const customScriptBtn = document.getElementById("custom-script-btn");
if (customScriptBtn) {
    customScriptBtn.addEventListener("click", () => {
        if (typeof window.arcAddTab === "function") {
            window.arcAddTab("Custom Script");
        }
    });
}

const uploadCustomScriptBtn = document.getElementById("upload-custom-script-btn");
if (uploadCustomScriptBtn) {
    // Intentionally a no-op for now.
    uploadCustomScriptBtn.addEventListener("click", () => {});
}

// ================= Hamburger menu accordion (File / Edit / View / Help /
// Developer / Pinboard, nested inside the hamburger dropdown) =================

const hamburgerMenu = document.getElementById("hamburger-menu");
if (hamburgerMenu) {
    const hamburgerBtn = document.getElementById("hamburger-btn");

    // Keep aria-expanded in sync with the shared open/close logic above.
    const hamburgerObserver = new MutationObserver(() => {
        hamburgerBtn.setAttribute("aria-expanded", hamburgerMenu.classList.contains("open") ? "true" : "false");
        if (!hamburgerMenu.classList.contains("open")) {
            hamburgerMenu.querySelectorAll(".menubar-group.open").forEach(g => g.classList.remove("open"));
        }
    });
    hamburgerObserver.observe(hamburgerMenu, { attributes: true, attributeFilter: ["class"] });

    hamburgerMenu.querySelectorAll(".menubar-group-header").forEach(header => {
        header.addEventListener("click", (e) => {
            e.stopPropagation();
            const group = header.closest(".menubar-group");
            const isOpen = group.classList.contains("open");
            hamburgerMenu.querySelectorAll(".menubar-group.open").forEach(g => g.classList.remove("open"));
            if (!isOpen) group.classList.add("open");
        });
    });
}

// ================= Theme toggle (in the profile dropdown) =================

const themeToggleBtn = document.getElementById("theme-toggle-btn");
const themeToggleLabel = themeToggleBtn.querySelector(".theme-toggle-label");

themeToggleBtn.addEventListener("click", () => {
    document.body.classList.toggle("theme-light");
    themeToggleLabel.textContent = document.body.classList.contains("theme-light") ? "Light Mode" : "Dark Mode";
});

// ================= Export =================

document.getElementById("export-btn").addEventListener("click", () => {
    alert("Export flow goes here (CSV / study bundle export).");
});

document.getElementById("minimize-btn").addEventListener("click", () => {
    window.pywebview?.api?.minimize();
});

document.getElementById("maximize-btn").addEventListener("click", () => {
    window.pywebview?.api?.maximize();
});

document.getElementById("window-close-btn").addEventListener("click", () => {
    window.pywebview?.api?.close();
});


// ================= Pinboard: draggable / resizable / pinnable widgets =================
// Widgets (Values, Quality, Graph) are dropped onto the pinboard (#nav-strip)
// via their respective buttons. Each widget can be dragged around, resized
// from its bottom-right corner, and pinned in place.

(function () {
    const board = document.getElementById("nav-strip");
    if (!board) return;
    // Widgets are parented to this pannable/zoomable layer instead of the
    // board itself (see the pan/zoom IIFE below), so they move and scale
    // along with the camera. Falls back to the board for safety if the
    // layer is somehow missing from the page.
    const canvas = document.getElementById("pinboard-canvas") || board;

    // Exposed so the analysis-target logic (subject/session/recording
    // selection) can clear the board whenever what's being analyzed
    // changes — every widget (Values, Quality, and Graph alike) is scoped
    // to whatever subject/session/recording is currently selected, so none
    // of them should linger once the user picks a different target.
    window.clearPinboardWidgets = function () {
        board.querySelectorAll(".pinboard-widget").forEach(w => w.remove());
    };

    const WIDGET_W = 220;
    const WIDGET_H = 160;
    const MIN_W = 200;
    const MIN_H = 140;

    // Values/Quality widgets are sized to their content's natural
    // (max-content) width, which packs the label/value columns too
    // tightly. This adds extra breathing room on top of that natural
    // width — applied everywhere a metric-type widget's width gets
    // measured, so wider content still ends up proportionally wider.
    const METRIC_WIDTH_BUFFER = 60;

    let widgetCount = 0;
    let zCounter = 1;

    // Widgets always spawn at a fixed starting spot on the board — no
    // memory of where the previous widget landed. The user can drag each
    // one wherever they like after it appears.
    const SPAWN_LEFT = 16;
    const SPAWN_TOP = 16;

    // Metric rows shown inside each Values/Quality widget type. Labels only
    // for now — actual figures get wired up once the backend is connected.
    //
    // Values' two keys ARE its task types (Sustained/DDK) -- this is
    // already filtered by getAvailableTaskTypesForTarget() up top (see
    // the Values dropdown filtering in updateWidgetButtonsAvailability
    // and the direct-select bypass in getDirectRecordingValueType()).
    // Quality's four keys (Overall/SNR/RMS/Ambient) are all task-
    // agnostic ("Both") -- recording quality isn't Sustained- or
    // DDK-specific, so none of them need that filtering.
    const WIDGET_METRICS = {
        Values: {
            Sustained: ["F0 Mean", "F0 Min", "F0 Max", "F1 Mean", "F2 Mean", "HNR", "Jitter Local"],
            DDK: ["DDK Repetition Count", "DDK Repetition Rate", "DDK Interval Mean", "DDK Regularity", "Speech Rate", "Pause/Speech Ratio", "DDK Interval Std"],
        },
        Quality: {
            "Overall": ["Recording Quality Rating", "Recording Quality Score", "Environment", "Recommendation", "Confidence"],
            "SNR/Signal": ["Cross-Channel SNR (dB)", "WADA SNR (dB)", "Mean Segmental SNR (dB)", "Minimum Segmental SNR (dB)", "Low-SNR Frame Percentage"],
            "RMS/Noise/Clipping": ["Patient RMS", "Ambient RMS", "Noise Floor (linear)", "Noise Floor (dB)", "Patient Clipping (%)", "Ambient Clipping (%)", "Clipping Detected", "Silence Percentage", "Silence Detected"],
            "Ambient/Spectral": ["Ambient RMS", "Ambient Peak", "Noise Floor", "Spectral Centroid", "Spectral Flatness"],
        },
    };

    function clamp(val, min, max) {
        return Math.max(min, Math.min(max, val));
    }

    // Computes the metric values a Values/Quality widget should show right
    // now, based on the current analysis target (subject/session/recording
    // — see setAnalysisTarget/analysisTargetRef above). "recording" targets
    // read straight from the recording row's own data (already fetched with
    // the recordings list); "subject"/"session" targets read from the
    // lazily-fetched ref._summary (see ensureAnalysisSummary) and may not be
    // populated yet, in which case rows just fall back to the em-dash.
    function getWidgetValuesSync(widgetTitle, valueType) {
        if (!analysisTargetType || !analysisTargetRef) return {};

        if (widgetTitle === "Values") {
            const metrics = (WIDGET_METRICS.Values[valueType] || []);
            const values = {};

            if (analysisTargetType === "recording") {
                const features = (analysisTargetRef._raw && analysisTargetRef._raw.features) || {};
                metrics.forEach(key => { values[key] = formatRawValue(features[key]); });
                return values;
            }

            // subject or session — mean ± SD summary
            const summary = analysisTargetRef._summary;
            if (!summary) return values;
            const meanKey = valueType === "DDK" ? "ddk_mean" : "vowel_mean";
            const sdKey = valueType === "DDK" ? "ddk_sd" : "vowel_sd";
            const mean = summary[meanKey] || {};
            const sd = summary[sdKey] || {};
            metrics.forEach(key => { values[key] = formatMeanSd(mean[key], sd[key]); });
            return values;
        }

        if (widgetTitle === "Quality") {
            // Quality is only ever shown for a single-recording target (the
            // "Quality" pinboard button itself is hidden otherwise).
            if (analysisTargetType !== "recording") return {};
            const raw = analysisTargetRef._raw || {};
            const values = {};
            let source = {};
            let metrics = [];
            if (valueType === "Overall") {
                source = raw.quality_classification || {};
                metrics = WIDGET_METRICS.Quality.Overall;
            } else if (valueType === "SNR/Signal" || valueType === "RMS/Noise/Clipping") {
                source = raw.quality_metrics || {};
                metrics = WIDGET_METRICS.Quality[valueType];
            } else if (valueType === "Ambient/Spectral") {
                source = raw.ambient_metrics || {};
                metrics = WIDGET_METRICS.Quality["Ambient/Spectral"];
            }
            metrics.forEach(key => { values[key] = formatRawValue(source[key]); });
            return values;
        }

        return {};
    }

    // ---- Live data accessors for graph widgets ----
    //
    // Every graph used to render from two hardcoded stand-in objects
    // regardless of what was actually being analyzed. These accessors
    // replace that: they read the SAME underlying values (features on
    // _raw for a single recording, vowel_mean/ddk_mean on _summary for
    // a session/subject) already used by getWidgetValuesSync() above,
    // so a graph and the matching Values widget can never disagree —
    // and because _summary is a live mean/SD rollup across every
    // recording in the session/subject (recomputed on every fetch, see
    // compute_session_summary()/compute_subject_summary() in
    // app/recording_store.py), a graph on a session/subject target
    // automatically reflects newly added/removed recordings the next
    // time it re-renders (see refreshAllWidgetValues() below, which
    // now re-renders open graph widgets too, not just Values/Quality).
    //
    // Return null when there's nothing to plot yet (no target picked,
    // or the relevant features/summary aren't loaded/present) —
    // callers must handle that by showing an empty state (see
    // graphEmptyStateHTML) rather than rendering stale or fake numbers.
    function getSustainedValuesForTarget() {
        if (!analysisTargetType || !analysisTargetRef) return null;
        const source = analysisTargetType === "recording"
            ? (analysisTargetRef._raw && analysisTargetRef._raw.features)
            : (analysisTargetRef._summary && analysisTargetRef._summary.vowel_mean);
        if (!source || Object.keys(source).length === 0) return null;
        return {
            f0Mean: source["F0 Mean"], f0Min: source["F0 Min"], f0Max: source["F0 Max"],
            f1Mean: source["F1 Mean"], f2Mean: source["F2 Mean"],
            hnr: source["HNR"], jitterLocal: source["Jitter Local"],
        };
    }

    function getDdkValuesForTarget() {
        if (!analysisTargetType || !analysisTargetRef) return null;
        const source = analysisTargetType === "recording"
            ? (analysisTargetRef._raw && analysisTargetRef._raw.features)
            : (analysisTargetRef._summary && analysisTargetRef._summary.ddk_mean);
        if (!source || Object.keys(source).length === 0) return null;
        return {
            ddkRepetitionCount: source["DDK Repetition Count"], ddkRepetitionRate: source["DDK Repetition Rate"],
            ddkIntervalMean: source["DDK Interval Mean"], ddkRegularity: source["DDK Regularity"],
            speechRate: source["Speech Rate"], pauseSpeechRatio: source["Pause/Speech Ratio"],
            ddkIntervalStd: source["DDK Interval Std"],
        };
    }

    // Reuses the same empty-state look as the Values/Quality metric
    // widgets (see buildWidgetMarkup's emptyText/pinboard-widget-empty).
    function graphEmptyStateHTML(label) {
        return `<div class="pinboard-widget-empty">No ${label} data yet</div>`;
    }

    const SPECTRO_STOPS = [
        [0.00, [4, 8, 20]], [0.15, [10, 40, 95]], [0.35, [20, 110, 165]], [0.50, [35, 170, 150]],
        [0.65, [140, 205, 90]], [0.80, [240, 205, 60]], [0.90, [245, 140, 40]], [1.00, [230, 60, 50]],
    ];

    function spectroColor(t) {
        t = Math.max(0, Math.min(1, t));
        for (let i = 0; i < SPECTRO_STOPS.length - 1; i++) {
            const [t0, c0] = SPECTRO_STOPS[i];
            const [t1, c1] = SPECTRO_STOPS[i + 1];
            if (t >= t0 && t <= t1) {
                const f = (t - t0) / (t1 - t0 || 1);
                return [
                    Math.round(c0[0] + (c1[0] - c0[0]) * f),
                    Math.round(c0[1] + (c1[1] - c0[1]) * f),
                    Math.round(c0[2] + (c1[2] - c0[2]) * f),
                ];
            }
        }
        return SPECTRO_STOPS[SPECTRO_STOPS.length - 1][1];
    }

    // Synthesizes a plausible harmonic spectrogram from the sustained-vowel
    // stats (F0/F1/F2/HNR) — a visual stand-in built from scalar features,
    // not a real STFT of the waveform. Used as the fallback when there's no
    // single recording to run a real STFT on (a session/subject aggregate
    // target has no one waveform), or if the real fetch below fails. See
    // renderRealSpectrogram for the real compute_spectrogram() output.
    function synthesizeSpectrogram(timeSteps, freqBins, maxFreq, vals) {
        const grid = new Float32Array(timeSteps * freqBins);
        const f0 = vals.f0Mean, f1 = vals.f1Mean, f2 = vals.f2Mean;
        const hnrNorm = Math.max(0, Math.min(1, vals.hnr / 25));
        const numHarmonics = Math.floor(maxFreq / f0);
        for (let t = 0; t < timeSteps; t++) {
            const time = t / timeSteps;
            const envelope = 0.75 + 0.25 * Math.sin(time * Math.PI * 6 + Math.sin(time * 17) * 0.5);
            for (let hIdx = 1; hIdx <= numHarmonics; hIdx++) {
                const freq = hIdx * f0;
                const freqRow = Math.round((freq / maxFreq) * (freqBins - 1));
                if (freqRow < 0 || freqRow >= freqBins) continue;
                let amp = 1 / Math.sqrt(hIdx);
                const distF1 = freq - f1, distF2 = freq - f2;
                amp *= 1 + 2.2 * Math.exp(-(distF1 * distF1) / (2 * 70 * 70));
                amp *= 1 + 1.6 * Math.exp(-(distF2 * distF2) / (2 * 90 * 90));
                amp *= envelope;
                for (let dr = -1; dr <= 1; dr++) {
                    const row = freqRow + dr;
                    if (row < 0 || row >= freqBins) continue;
                    const spread = dr === 0 ? 1 : 0.4;
                    const idx = t * freqBins + row;
                    grid[idx] = Math.max(grid[idx], amp * spread);
                }
            }
            const noiseAmt = (1 - hnrNorm) * 0.18;
            for (let r = 0; r < freqBins; r++) {
                const idx = t * freqBins + r;
                grid[idx] += noiseAmt * Math.random() * (1 - (r / freqBins) * 0.4);
            }
        }
        let maxV = 0;
        for (let i = 0; i < grid.length; i++) maxV = Math.max(maxV, grid[i]);
        if (maxV <= 0) maxV = 1;
        for (let i = 0; i < grid.length; i++) grid[i] = Math.min(1, grid[i] / maxV);
        return grid;
    }

    function drawSpectrogram(canvas, vals) {
        const timeSteps = 220, freqBins = 100, maxFreq = 4000;
        const grid = synthesizeSpectrogram(timeSteps, freqBins, maxFreq, vals);
        const off = document.createElement("canvas");
        off.width = timeSteps; off.height = freqBins;
        const octx = off.getContext("2d");
        const imgData = octx.createImageData(timeSteps, freqBins);
        for (let t = 0; t < timeSteps; t++) {
            for (let r = 0; r < freqBins; r++) {
                const v = grid[t * freqBins + r];
                const [cr, cg, cb] = spectroColor(v);
                const y = freqBins - 1 - r; // low frequency at the bottom
                const idx = (y * timeSteps + t) * 4;
                imgData.data[idx] = cr; imgData.data[idx + 1] = cg; imgData.data[idx + 2] = cb; imgData.data[idx + 3] = 255;
            }
        }
        octx.putImageData(imgData, 0, 0);
        const wrap = canvas.parentElement;
        const dpr = window.devicePixelRatio || 1;
        const cssW = wrap.clientWidth || 640, cssH = wrap.clientHeight || 288;
        canvas.width = cssW * dpr; canvas.height = cssH * dpr;
        const ctx = canvas.getContext("2d");
        ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
        ctx.drawImage(off, 0, 0, canvas.width, canvas.height);
    }

    // Paints a REAL freq/time/magnitude-dB grid (from
    // GET /api/sessions/{id}/recordings/{id}/spectrogram, i.e. actual
    // compute_spectrogram() STFT output) instead of a synthesized one.
    // magnitudeDb is [freq_bins][time_bins], low frequency first (see
    // the route's docstring). Colored relative to a fixed 60dB dynamic
    // range below the grid's own peak -- a typical display range for a
    // speech spectrogram, and self-normalizing per recording so a quiet
    // vs. loud take both render with usable contrast.
    const SPECTROGRAM_DISPLAY_RANGE_DB = 60;

    function drawSpectrogramGrid(canvas, freqs, times, magnitudeDb) {
        const freqBins = magnitudeDb.length;
        const timeSteps = freqBins > 0 ? magnitudeDb[0].length : 0;
        if (freqBins === 0 || timeSteps === 0) return;

        let maxDb = -Infinity;
        for (let r = 0; r < freqBins; r++) {
            const row = magnitudeDb[r];
            for (let t = 0; t < timeSteps; t++) {
                if (row[t] > maxDb) maxDb = row[t];
            }
        }
        const dbFloor = maxDb - SPECTROGRAM_DISPLAY_RANGE_DB;
        const dbRange = maxDb - dbFloor || 1;

        const off = document.createElement("canvas");
        off.width = timeSteps; off.height = freqBins;
        const octx = off.getContext("2d");
        const imgData = octx.createImageData(timeSteps, freqBins);
        for (let t = 0; t < timeSteps; t++) {
            for (let r = 0; r < freqBins; r++) {
                const norm = Math.max(0, Math.min(1, (magnitudeDb[r][t] - dbFloor) / dbRange));
                const [cr, cg, cb] = spectroColor(norm);
                const y = freqBins - 1 - r; // low frequency at the bottom
                const idx = (y * timeSteps + t) * 4;
                imgData.data[idx] = cr; imgData.data[idx + 1] = cg; imgData.data[idx + 2] = cb; imgData.data[idx + 3] = 255;
            }
        }
        octx.putImageData(imgData, 0, 0);
        const wrap = canvas.parentElement;
        const dpr = window.devicePixelRatio || 1;
        const cssW = wrap.clientWidth || 640, cssH = wrap.clientHeight || 288;
        canvas.width = cssW * dpr; canvas.height = cssH * dpr;
        const ctx = canvas.getContext("2d");
        ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
        ctx.drawImage(off, 0, 0, canvas.width, canvas.height);
    }

    function formatFreqAxisLabel(hz) {
        if (hz <= 0) return "0";
        if (hz >= 1000) {
            const k = hz / 1000;
            return (Math.round(k * 10) / 10).toString().replace(/\.0$/, "") + "k";
        }
        return String(Math.round(hz));
    }

    function spectroMarkup(rangeLabel, yLabels, xLabels) {
        return `
            <div class="spectro-root">
                <div class="spectro-header">
                    <div>
                        <div class="spectro-title">Spectrogram</div>
                        <div class="spectro-sub">Voice energy across time and frequency</div>
                    </div>
                    <div class="spectro-range-pill">
                        ${rangeLabel}
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                    </div>
                </div>
                <div class="spectro-body">
                    <div class="spectro-yaxis">${yLabels.map((l) => `<span>${l}</span>`).join("")}</div>
                    <div class="spectro-canvas-wrap">
                        <canvas class="spectro-canvas"></canvas>
                        <div class="spectro-gridlines"></div>
                    </div>
                </div>
                <div class="spectro-xaxis-row">
                    <div class="spectro-xaxis-spacer"></div>
                    <div class="spectro-xaxis">${xLabels.map((l) => `<span>${l}</span>`).join("")}</div>
                </div>
                <div class="spectro-legend">
                    <span class="spectro-legend-label">LOW</span>
                    <div class="spectro-legend-bar"></div>
                    <span class="spectro-legend-label">HIGH</span>
                </div>
            </div>`;
    }

    function renderSynthesizedSpectrogram(container, vals) {
        const maxFreq = 4000, duration = 3.0;
        container.innerHTML = spectroMarkup(
            "0\u20134 kHz",
            ["4k", "3k", "2k", "1k", "0"],
            ["0.0s", "0.75s", "1.5s", "2.25s", "3.0s"],
        );
        const canvas = container.querySelector(".spectro-canvas");
        drawSpectrogram(canvas, vals);
        if (window.ResizeObserver) {
            const ro = new ResizeObserver(() => drawSpectrogram(canvas, vals));
            ro.observe(canvas.parentElement);
        }
    }

    // Loads the real STFT grid for a single recording and paints it in
    // place of the synthesized stand-in. `token` guards against a stale
    // response landing after the user has switched targets or the
    // widget has re-rendered again in the meantime -- same pattern as
    // renderRealAudioWaveform above.
    let _rtSpectrogramTokenCounter = 0;

    function renderRealSpectrogram(container, opts) {
        const token = String(++_rtSpectrogramTokenCounter);
        container.dataset.rtSpectrogramToken = token;
        container.innerHTML = `<div class="pinboard-widget-empty">Loading spectrogram\u2026</div>`;

        api.getRecordingSpectrogram(opts.sessionId, opts.recordingId).then((data) => {
            if (container.dataset.rtSpectrogramToken !== token) return; // stale — target/widget moved on
            const freqs = data.freqs || [];
            const times = data.times || [];
            const magnitudeDb = data.magnitude_db || [];
            if (!freqs.length || !times.length || !magnitudeDb.length) {
                if (opts.fallback) opts.fallback();
                else container.innerHTML = graphEmptyStateHTML("Spectrogram");
                return;
            }

            const freqMax = freqs[freqs.length - 1];
            const duration = times[times.length - 1];
            const yLabels = [1, 0.75, 0.5, 0.25, 0].map((f) => formatFreqAxisLabel(freqMax * f));
            const xLabels = [0, 0.25, 0.5, 0.75, 1].map((f) => (duration * f).toFixed(2) + "s");
            container.innerHTML = spectroMarkup(
                `0\u2013${formatFreqAxisLabel(freqMax)} Hz`,
                yLabels,
                xLabels,
            );
            const canvas = container.querySelector(".spectro-canvas");
            drawSpectrogramGrid(canvas, freqs, times, magnitudeDb);
            if (window.ResizeObserver) {
                const ro = new ResizeObserver(() => drawSpectrogramGrid(canvas, freqs, times, magnitudeDb));
                ro.observe(canvas.parentElement);
            }
        }).catch((err) => {
            if (container.dataset.rtSpectrogramToken !== token) return;
            console.error(err);
            if (opts.fallback) opts.fallback();
            else container.innerHTML = graphEmptyStateHTML("Spectrogram");
        });
    }

    // Entry point for the Spectrogram widget. A single recording has a
    // real WAV file behind it, so try the real STFT first, falling
    // back to the synthesized harmonic stand-in only if that specific
    // recording's fetch fails. A session/subject aggregate target has
    // no single waveform a spectrogram can be computed from -- there's
    // no meaningful way to average multiple STFT grids -- so it shows
    // the empty state rather than a synthesized stand-in that could be
    // mistaken for real data.
    function renderSpectrogram(container) {
        if (analysisTargetType === "recording" && analysisTargetRef) {
            const sessionId = analysisTargetRef.sessionId
                || (analysisTargetRef._raw && analysisTargetRef._raw.session_id);
            const recordingId = analysisTargetRef.id
                || (analysisTargetRef._raw && analysisTargetRef._raw.recording_id);
            if (sessionId && recordingId) {
                const vals = getSustainedValuesForTarget();
                renderRealSpectrogram(container, {
                    sessionId,
                    recordingId,
                    fallback: () => {
                        if (vals) renderSynthesizedSpectrogram(container, vals);
                        else container.innerHTML = graphEmptyStateHTML("Spectrogram");
                    },
                });
                return;
            }
        }

        container.innerHTML = graphEmptyStateHTML("Spectrogram");
    }

    // ---- Formants graph content ----
    function fmt(v, d) {
        return Number(v).toFixed(d === undefined ? 1 : d);
    }

    function svgWrap(title, inner, filterIds, w, h) {
        w = w || 320; h = h || 200;
        const defs = filterIds.map((id) => `
            <filter id="${id}" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="2.2" result="blur"/>
                <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>`).join("");
        return `
            <svg viewBox="0 0 ${w} ${h}" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">
                <defs>${defs}</defs>
                <text x="14" y="22" fill="#8a8a8a" font-size="11" letter-spacing="1">${title.toUpperCase()}</text>
                ${inner}
            </svg>`;
    }

    function barChartSVG(id, title, bars) {
        const W = 320, H = 200, top = 46, baseline = 168, maxH = baseline - top;
        const n = bars.length, gap = 22, barW = (W - gap * (n + 1)) / n;
        let body = `<line x1="${gap - 8}" y1="${baseline}" x2="${W - gap + 8}" y2="${baseline}" stroke="#3a3a3a"/>`;
        bars.forEach((b, i) => {
            const frac = Math.max(0, Math.min(1, b.value / b.max));
            const bh = frac * maxH;
            const x = gap + i * (barW + gap);
            const y = baseline - bh;
            body += `
                <rect x="${x}" y="${y}" width="${barW}" height="${bh}" rx="2" fill="#ffffff" opacity="0.92" filter="url(#glow-${id})"/>
                <text x="${x + barW / 2}" y="${y - 8}" text-anchor="middle" fill="#ffffff" font-size="12" font-weight="700">${fmt(b.value)}${b.unit}</text>
                <text x="${x + barW / 2}" y="${baseline + 18}" text-anchor="middle" fill="#8a8a8a" font-size="9" letter-spacing="0.5">${b.label.toUpperCase()}</text>`;
        });
        return svgWrap(title, body, [`glow-${id}`], W, H);
    }

    function renderFormants(container) {
        const vals = getSustainedValuesForTarget();
        if (!vals) { container.innerHTML = graphEmptyStateHTML("Formants"); return; }
        container.innerHTML = barChartSVG("formants", "Formant Means", [
            { label: "F0", value: vals.f0Mean, max: 1100, unit: "Hz" },
            { label: "F1", value: vals.f1Mean, max: 1100, unit: "Hz" },
            { label: "F2", value: vals.f2Mean, max: 1100, unit: "Hz" },
        ]);
    }

    function ringGaugeSVG(id, title, a, b) {
        const W = 320, H = 200, r = 40, c = 2 * Math.PI * r, cy = 96;
        const cxA = 92, cxB = 228;
        function ring(cx, frac, fid) {
            const dash = c * Math.max(0, Math.min(1, frac));
            return `
                <circle cx="${cx}" cy="${cy}" r="${r}" stroke="#2a2a2a" stroke-width="8" fill="none"/>
                <circle cx="${cx}" cy="${cy}" r="${r}" stroke="#ffffff" stroke-width="8" fill="none"
                    stroke-dasharray="${dash} ${c}" stroke-linecap="round"
                    transform="rotate(-90 ${cx} ${cy})" filter="url(#${fid})"/>`;
        }
        const body = `
            ${ring(cxA, a.value / a.max, `glow-${id}-a`)}
            ${ring(cxB, b.value / b.max, `glow-${id}-b`)}
            <text x="${cxA}" y="${cy - 2}" text-anchor="middle" fill="#ffffff" font-size="16" font-weight="700">${fmt(a.value, 2)}</text>
            <text x="${cxA}" y="${cy + 14}" text-anchor="middle" fill="#8a8a8a" font-size="9">${a.unit}</text>
            <text x="${cxA}" y="${cy + 56}" text-anchor="middle" fill="#8a8a8a" font-size="9" letter-spacing="0.5">${a.label.toUpperCase()}</text>
            <text x="${cxB}" y="${cy - 2}" text-anchor="middle" fill="#ffffff" font-size="16" font-weight="700">${fmt(b.value, 2)}</text>
            <text x="${cxB}" y="${cy + 14}" text-anchor="middle" fill="#8a8a8a" font-size="9">${b.unit}</text>
            <text x="${cxB}" y="${cy + 56}" text-anchor="middle" fill="#8a8a8a" font-size="9" letter-spacing="0.5">${b.label.toUpperCase()}</text>`;
        return svgWrap(title, body, [`glow-${id}-a`, `glow-${id}-b`], W, H);
    }

    function renderVoiceQuality(container) {
        const vals = getSustainedValuesForTarget();
        if (!vals) { container.innerHTML = graphEmptyStateHTML("Voice Quality"); return; }
        container.innerHTML = ringGaugeSVG("voice-quality", "Voice Quality",
            { label: "HNR", value: vals.hnr, max: 30, unit: "dB" },
            { label: "Jitter", value: vals.jitterLocal, max: 1, unit: "%" });
    }

    // ---- Voice Metrics graph content ----
    //
    // Two profiles built from live sustained/ddk data (see
    // getSustainedValuesForTarget/getDdkValuesForTarget above), each
    // normalized to a % of its own peak so both series share one 0-100
    // axis despite different units. Voice Metrics is a "Both" (task-
    // agnostic) graph -- if one task type has no data for the current
    // target, that series falls back to a flat zero line rather than
    // hiding the whole chart, since the other series may still be
    // meaningful on its own.
    function buildVoiceMetricsSeries() {
        const sustainedVals = getSustainedValuesForTarget();
        const ddkVals = getDdkValuesForTarget();
        const sustainedArr = sustainedVals
            ? [sustainedVals.f0Min, sustainedVals.f0Mean, sustainedVals.f0Max, sustainedVals.f1Mean, sustainedVals.f2Mean, sustainedVals.hnr, sustainedVals.jitterLocal]
            : [0, 0, 0, 0, 0, 0, 0];
        const ddkArr = ddkVals
            ? [ddkVals.ddkRepetitionCount, ddkVals.ddkRepetitionRate, ddkVals.ddkIntervalMean, ddkVals.ddkRegularity, ddkVals.speechRate, ddkVals.pauseSpeechRatio, ddkVals.ddkIntervalStd]
            : [0, 0, 0, 0, 0, 0, 0];
        const normalize = (vals) => {
            const lo = Math.min(...vals), hi = Math.max(...vals);
            const span = (hi - lo) || 1;
            return vals.map((v) => ((v - lo) / span) * 100);
        };
        return {
            sustainedPct: normalize(sustainedArr), ddkPct: normalize(ddkArr),
            hasSustained: !!sustainedVals, hasDdk: !!ddkVals,
        };
    }

    function smoothPath(points) {
        if (points.length < 2) return "";
        let d = `M ${points[0][0]},${points[0][1]}`;
        for (let i = 0; i < points.length - 1; i++) {
            const [x0, y0] = points[i], [x1, y1] = points[i + 1];
            const mx = (x0 + x1) / 2;
            d += ` Q ${x0},${y0} ${mx},${(y0 + y1) / 2}`;
        }
        const last = points[points.length - 1];
        d += ` T ${last[0]},${last[1]}`;
        return d;
    }

    function areaChartSVG(sustainedPct, ddkPct, maxValue) {
        const W = 700, H = 260, padTop = 10, padBottom = 10;
        const usableH = H - padTop - padBottom;
        const n = sustainedPct.length;
        const xAt = (i) => (i / (n - 1)) * W;
        const yAt = (v) => padTop + usableH - (v / maxValue) * usableH;
        const sPts = sustainedPct.map((v, i) => [xAt(i), yAt(v)]);
        const dPts = ddkPct.map((v, i) => [xAt(i), yAt(v)]);
        const sLine = smoothPath(sPts), dLine = smoothPath(dPts);
        const sArea = `${sLine} L ${W},${H} L 0,${H} Z`;
        const dArea = `${dLine} L ${W},${H} L 0,${H} Z`;
        let grid = "";
        for (let g = 0; g <= 4; g++) {
            const gy = padTop + (usableH / 4) * g;
            grid += `<line x1="0" y1="${gy}" x2="${W}" y2="${gy}" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>`;
        }
        return `
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
                <defs>
                    <linearGradient id="area-desktop-fill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#8b8b93" stop-opacity="0.35"/>
                        <stop offset="100%" stop-color="#8b8b93" stop-opacity="0.02"/>
                    </linearGradient>
                    <linearGradient id="area-mobile-fill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#6ea8fe" stop-opacity="0.55"/>
                        <stop offset="100%" stop-color="#6ea8fe" stop-opacity="0.03"/>
                    </linearGradient>
                </defs>
                ${grid}
                <path d="${sArea}" fill="url(#area-desktop-fill)"/>
                <path d="${sLine}" fill="none" stroke="#8b8b93" stroke-width="1.5"/>
                <path d="${dArea}" fill="url(#area-mobile-fill)"/>
                <path d="${dLine}" fill="none" stroke="#6ea8fe" stroke-width="1.5"/>
            </svg>`;
    }

    function renderAreaChart(container) {
        const { sustainedPct, ddkPct, hasSustained, hasDdk } = buildVoiceMetricsSeries();
        if (!hasSustained && !hasDdk) { container.innerHTML = graphEmptyStateHTML("Voice Metrics"); return; }
        const ticks = [100, 75, 50, 25, 0];
        const metricLabels = ["1", "2", "3", "4", "5", "6", "7"];
        container.innerHTML = `
            <div class="area-root">
                <div class="area-header">
                    <div>
                        <div class="area-title">Voice Metrics</div>
                        <div class="area-sub">Sustained vowel vs. DDK rhythm, each scaled to its own min&ndash;max range</div>
                    </div>
                    <div class="area-range-pill">
                        min&ndash;max
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                    </div>
                </div>
                <div class="area-body">
                    <div class="area-yaxis">${ticks.map((t) => `<span>${t}</span>`).join("")}</div>
                    <div class="area-chart-wrap">${areaChartSVG(sustainedPct, ddkPct, 100)}</div>
                </div>
                <div class="area-xaxis-row">
                    <div class="area-xaxis-spacer"></div>
                    <div class="area-xaxis">${metricLabels.map((l) => `<span>${l}</span>`).join("")}</div>
                </div>
                <div class="area-legend">
                    <div class="area-legend-item"${hasSustained ? "" : ' style="opacity:0.4"'}><span class="area-legend-dot" style="background:#8b8b93"></span>Sustained Vowel${hasSustained ? "" : " (no data)"}</div>
                    <div class="area-legend-item"${hasDdk ? "" : ' style="opacity:0.4"'}><span class="area-legend-dot" style="background:#6ea8fe"></span>DDK Rhythm${hasDdk ? "" : " (no data)"}</div>
                </div>
            </div>`;
    }

    // ---- Pitch Waveform graph content ----
    //
    // A mirrored bar "audio waveform" — the classic audio-player look —
    // but driven by pitch (F0 in Hz) instead of amplitude. Real per-frame
    // pitch data isn't served by the backend yet (see
    // getPitchTraceForTarget() below), so the trace is synthesized from
    // the same scalar sustained-vowel stats (f0Mean/f0Min/f0Max/
    // jitterLocal) the Formants/Voice Quality widgets already read: a
    // ~5Hz vibrato sine + a ~0.35Hz slow drift sine + a seeded jitter
    // walk, scaled by the vowel's own F0 range. The seed is fixed (not
    // time-based), so the trace is stable across re-renders/resizes
    // instead of jittering into a new random shape every time.
    //
    // Everything downstream of the trace array (bar heights, the
    // oscillator sonification in wirePitchWaveformPlayback) only cares
    // that it's an array of Hz values — once a real per-frame contour is
    // available from the backend (e.g. an extract_pitch_contour()
    // endpoint), swap it in inside getPitchTraceForTarget() and nothing
    // else here needs to change.

    // ==========================================================
    // Real-audio waveform + playback (used by both Pitch Waveform
    // and DDK Waveform when the analysis target is a single
    // recording — a real WAV file, not an aggregated session/subject
    // rollup). Falls back to the synthesized trace above/below when
    // there's no single recording to point at, or if the audio fails
    // to load, so the widgets never break — they just degrade to the
    // stand-in look they already had.
    //
    // The backend already serves the raw file at
    // GET /api/recordings/audio?path=<patient_filepath> (see
    // api/routes.py get_recording_audio) — it was wired up for an
    // <audio> tag and had no frontend caller yet. This is that
    // caller: fetch the WAV, decode it once with the Web Audio API to
    // get the real per-sample PCM (for the bar heights) and the real
    // duration, then drive an actual <audio> element for playback so
    // the sound and the playhead are both genuinely real-time instead
    // of a fixed-length oscillator sweep.
    const AUDIO_DECODE_CACHE = new Map(); // patient_filepath -> Promise<AudioBuffer>
    let _sharedAudioCtx = null;

    function getSharedAudioCtx() {
        if (!_sharedAudioCtx) _sharedAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        return _sharedAudioCtx;
    }

    // Decodes are cached per file so re-rendering (refreshAllWidgetValues,
    // switching widgets back and forth) doesn't refetch/redecode the same
    // WAV every time — only the first render per recording pays for it.
    function decodeRecordingAudio(filepath) {
        if (!filepath) return Promise.reject(new Error("No audio file for this target."));
        if (AUDIO_DECODE_CACHE.has(filepath)) return AUDIO_DECODE_CACHE.get(filepath);
        const promise = fetch(`/api/recordings/audio?path=${encodeURIComponent(filepath)}`)
            .then((res) => {
                if (!res.ok) throw new Error("Couldn't load the recording's audio.");
                return res.arrayBuffer();
            })
            .then((arrayBuf) => getSharedAudioCtx().decodeAudioData(arrayBuf))
            .catch((err) => {
                AUDIO_DECODE_CACHE.delete(filepath); // don't cache a failed decode
                throw err;
            });
        AUDIO_DECODE_CACHE.set(filepath, promise);
        return promise;
    }

    // Real peak-amplitude envelope, bucketed to `n` bars — the actual
    // waveform of the recording, not a synthesized stand-in. Peak (not
    // average) per bucket so short bursts/transients still read in a
    // 96-bar-wide view instead of getting smoothed away.
    function computePeakEnvelope(audioBuffer, n) {
        const data = audioBuffer.getChannelData(0);
        const total = data.length;
        const blockSize = Math.max(1, Math.floor(total / n));
        const trace = new Array(n).fill(0);
        for (let i = 0; i < n; i++) {
            const start = i * blockSize;
            const end = i === n - 1 ? total : Math.min(total, start + blockSize);
            let peak = 0;
            for (let j = start; j < end; j++) {
                const a = Math.abs(data[j]);
                if (a > peak) peak = a;
            }
            trace[i] = peak;
        }
        return trace;
    }

    // Mirrored-bar SVG for a real amplitude envelope — same played/
    // unplayed clip-path trick as the synthesized versions below, just
    // bars sized by actual peak amplitude (0..maxAmp) instead of
    // deviation from a synthesized mean.
    function realWaveformSVG(id, trace, color) {
        const W = 700, H = 200, midY = H / 2;
        const n = trace.length;
        const maxAmp = Math.max(0.0005, ...trace);
        const barGap = 2;
        const barW = Math.max(1.5, W / n - barGap);
        let bars = "";
        for (let i = 0; i < n; i++) {
            const frac = Math.min(1, trace[i] / maxAmp);
            const halfH = Math.max(1, frac * (midY - 4));
            const x = (i / n) * W;
            bars += `<rect x="${x.toFixed(2)}" y="${(midY - halfH).toFixed(2)}" width="${barW.toFixed(2)}" height="${(halfH * 2).toFixed(2)}" rx="1"/>`;
        }
        return `
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="pitch-wave-svg">
                <defs>
                    <clipPath id="rt-waveform-clip-${id}">
                        <rect id="rt-waveform-clip-rect-${id}" x="0" y="0" width="0" height="${H}"/>
                    </clipPath>
                </defs>
                <line x1="0" y1="${midY}" x2="${W}" y2="${midY}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
                <g fill="#4b4b52">${bars}</g>
                <g fill="${color}" clip-path="url(#rt-waveform-clip-${id})">${bars}</g>
                <line id="rt-waveform-playhead-${id}" x1="0" y1="0" x2="0" y2="${H}" stroke="${color}" stroke-width="1.5"/>
            </svg>`;
    }

    // Wires real playback for one real-audio waveform instance with an
    // actual <audio> element — play/pause, click-and-drag seeking, and
    // a playhead driven by the element's own currentTime via rAF, so
    // both the sound and the visual are genuinely in sync with real
    // playback instead of a projected/oscillator timeline.
    function wireRealAudioPlayback(container, id, filepath, duration) {
        const playBtn = container.querySelector(".pitch-play-btn");
        const playIcon = container.querySelector(".pitch-play-icon");
        const pauseIcon = container.querySelector(".pitch-pause-icon");
        const timeReadout = container.querySelector(".pitch-time-readout");
        const clipRect = container.querySelector(`#rt-waveform-clip-rect-${id}`);
        const playhead = container.querySelector(`#rt-waveform-playhead-${id}`);
        const seekOverlay = container.querySelector(".pitch-seek-overlay");
        const W = 700;

        const audioEl = new Audio(`/api/recordings/audio?path=${encodeURIComponent(filepath)}`);
        audioEl.preload = "auto";
        let rafId = null;

        function paint(t) {
            const frac = duration > 0 ? Math.min(1, Math.max(0, t / duration)) : 0;
            const x = frac * W;
            if (clipRect) clipRect.setAttribute("width", x.toFixed(2));
            if (playhead) { playhead.setAttribute("x1", x.toFixed(2)); playhead.setAttribute("x2", x.toFixed(2)); }
            if (timeReadout) timeReadout.textContent = `${formatClockTime(t)} / ${formatClockTime(duration)}`;
        }

        function tick() {
            paint(audioEl.currentTime);
            if (!audioEl.paused && !audioEl.ended) rafId = requestAnimationFrame(tick);
        }

        function setPlayingUI(isPlaying) {
            if (playIcon) playIcon.style.display = isPlaying ? "none" : "";
            if (pauseIcon) pauseIcon.style.display = isPlaying ? "" : "none";
        }

        function togglePlay() {
            if (audioEl.paused) {
                if (audioEl.ended) audioEl.currentTime = 0;
                audioEl.play().catch((err) => { console.error(err); showToast("Couldn't play this recording's audio."); });
            } else {
                audioEl.pause();
            }
        }

        audioEl.addEventListener("play", () => { setPlayingUI(true); if (rafId) cancelAnimationFrame(rafId); rafId = requestAnimationFrame(tick); });
        audioEl.addEventListener("pause", () => { setPlayingUI(false); if (rafId) cancelAnimationFrame(rafId); rafId = null; });
        audioEl.addEventListener("ended", () => { setPlayingUI(false); paint(0); });

        // Same drag-start guard as the synthesized widgets — the card's
        // dragSurface skips ".graph-interactive", but stop propagation
        // here too as defense in depth.
        if (playBtn) {
            playBtn.addEventListener("mousedown", (e) => e.stopPropagation());
            playBtn.addEventListener("click", (e) => { e.stopPropagation(); togglePlay(); });
        }

        if (seekOverlay) {
            const seekTo = (clientX) => {
                const rect = seekOverlay.getBoundingClientRect();
                if (!rect.width) return;
                const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
                // Clamp just short of the true end: setting currentTime to
                // exactly `duration` fires the native "ended" event even
                // while paused, which snaps playback back to 0. With the
                // mouse held outside the widget, mousemove keeps re-firing
                // seekTo(), so that reset-to-0 immediately gets overwritten
                // by another jump to the end, then reset again — producing
                // a fast 0/end flicker for as long as the drag stays past
                // the edge.
                const target = Math.min(frac * duration, Math.max(0, duration - 0.05));
                audioEl.currentTime = target;
                paint(audioEl.currentTime);
            };
            seekOverlay.addEventListener("mousedown", (e) => {
                e.stopPropagation();
                e.preventDefault();
                seekTo(e.clientX);
                function onMove(ev) { seekTo(ev.clientX); }
                function onUp() {
                    window.removeEventListener("mousemove", onMove);
                    window.removeEventListener("mouseup", onUp);
                }
                window.addEventListener("mousemove", onMove);
                window.addEventListener("mouseup", onUp);
            });
        }

        paint(0);
        container._realWaveformState = {
            cleanup() {
                try { audioEl.pause(); } catch (e) { /* not playing */ }
                audioEl.src = "";
                if (rafId) cancelAnimationFrame(rafId);
            },
        };

        const widget = container.closest(".pinboard-widget");
        const closeBtn = widget && widget.querySelector(".pinboard-widget-close-btn, .pinboard-close-btn");
        if (closeBtn && !closeBtn.dataset.realWaveformCleanupBound) {
            closeBtn.dataset.realWaveformCleanupBound = "1";
            closeBtn.addEventListener("click", () => {
                if (container._realWaveformState) container._realWaveformState.cleanup();
            });
        }
    }

    // Loads + decodes the real recording, then renders the real
    // waveform + real playback controls in place of the synthesized
    // stand-in. `token` guards against a stale response landing after
    // the user has switched targets or the widget has re-rendered again
    // in the meantime (decodeRecordingAudio is async and can resolve
    // after the container has moved on).
    let _rtWaveformTokenCounter = 0;
    let _rtWaveformInstanceCount = 0;

    function renderRealAudioWaveform(container, opts) {
        const token = String(++_rtWaveformTokenCounter);
        container.dataset.rtWaveformToken = token;
        container.innerHTML = `<div class="pinboard-widget-empty">Loading audio\u2026</div>`;

        decodeRecordingAudio(opts.filepath).then((audioBuffer) => {
            if (container.dataset.rtWaveformToken !== token) return; // stale — target/widget moved on
            const trace = computePeakEnvelope(audioBuffer, 96);
            const duration = audioBuffer.duration;
            const id = ++_rtWaveformInstanceCount;
            const svg = realWaveformSVG(id, trace, opts.color);
            const xTicks = [0, 1, 2, 3, 4].map((i) => ((duration / 4) * i).toFixed(1) + "s");

            container.innerHTML = `
                <div class="area-root">
                    <div class="area-header">
                        <div>
                            <div class="area-title">${opts.title}</div>
                            <div class="area-sub">${opts.subtitle}</div>
                        </div>
                        <div class="pitch-controls-pill">
                            <button type="button" class="pitch-play-btn graph-interactive" title="Play" aria-label="Play">
                                <svg class="pitch-play-icon" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                                <svg class="pitch-pause-icon" viewBox="0 0 24 24" fill="currentColor" style="display:none"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>
                            </button>
                            <span class="pitch-time-readout">0:00 / ${formatClockTime(duration)}</span>
                        </div>
                    </div>
                    <div class="area-body">
                        <div class="area-yaxis"><span>+</span><span>0</span><span>&minus;</span></div>
                        <div class="area-chart-wrap pitch-chart-wrap">
                            ${svg}
                            <div class="pitch-seek-overlay graph-interactive"></div>
                        </div>
                    </div>
                    <div class="area-xaxis-row">
                        <div class="area-xaxis-spacer"></div>
                        <div class="area-xaxis">${xTicks.map((t) => `<span>${t}</span>`).join("")}</div>
                    </div>
                </div>`;

            wireRealAudioPlayback(container, id, opts.filepath, duration);
        }).catch((err) => {
            if (container.dataset.rtWaveformToken !== token) return;
            console.error(err);
            if (opts.fallback) opts.fallback();
            else container.innerHTML = graphEmptyStateHTML(opts.title);
        });
    }

    let pitchWaveformInstanceCount = 0;
    const PITCH_WAVEFORM_SAMPLES = 96;
    // Fixed stand-in length, same approach as Spectrogram's hardcoded
    // 3.0s axis (see drawSpectrogram) until a real recording duration is
    // wired up.
    const PITCH_WAVEFORM_DURATION = 4.0;

    // Small deterministic PRNG so the jitter walk below is repeatable.
    function mulberry32(seed) {
        return function () {
            seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
            let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    function synthesizePitchTrace(vals, n) {
        const mean = vals.f0Mean;
        const range = Math.max(6, (vals.f0Max - vals.f0Min) || mean * 0.15);
        const jitterStep = Math.max(0.002, vals.jitterLocal || 0.01) * mean * 2;
        const rand = mulberry32(0xA57C0DE ^ Math.round(mean * 97));
        let walk = 0;
        const trace = new Array(n);
        for (let i = 0; i < n; i++) {
            const t = (i / (n - 1)) * PITCH_WAVEFORM_DURATION;
            const vibrato = Math.sin(t * 2 * Math.PI * 5) * range * 0.16;
            const drift = Math.sin(t * 2 * Math.PI * 0.35) * range * 0.28;
            walk = walk * 0.88 + (rand() - 0.5) * jitterStep;
            trace[i] = Math.max(20, mean + vibrato + drift + walk);
        }
        return trace;
    }

    // Prefers a real per-frame pitch contour if the backend ever starts
    // sending one (analysisTargetRef._raw.pitch_contour for a single
    // recording, or the _summary equivalent for a session/subject
    // rollup), falling back to the synthesized stand-in otherwise.
    function getPitchTraceForTarget(vals) {
        const real = analysisTargetType === "recording"
            ? (analysisTargetRef && analysisTargetRef._raw && analysisTargetRef._raw.pitch_contour)
            : (analysisTargetRef && analysisTargetRef._summary && analysisTargetRef._summary.pitch_contour);
        if (Array.isArray(real) && real.length > 1) return real;
        return synthesizePitchTrace(vals, PITCH_WAVEFORM_SAMPLES);
    }

    function formatClockTime(seconds) {
        const s = Math.max(0, seconds);
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${String(sec).padStart(2, "0")}`;
    }

    // Builds the mirrored-bar SVG for one Pitch Waveform instance. Bars
    // are drawn twice — once gray as the full-track base layer, once
    // white on top clipped by a per-instance <clipPath> whose width
    // grows with playback progress (see wirePitchWaveformPlayback) — so
    // played/unplayed portions read like a familiar audio-player
    // waveform. `id` disambiguates the clipPath if more than one Pitch
    // Waveform card is open at once.
    function pitchWaveformSVG(id, trace) {
        const W = 700, H = 200, midY = H / 2;
        const n = trace.length;
        const mean = trace.reduce((a, b) => a + b, 0) / n;
        const maxDev = Math.max(1, ...trace.map((v) => Math.abs(v - mean)));
        const barGap = 2;
        const barW = Math.max(1.5, W / n - barGap);
        let bars = "";
        for (let i = 0; i < n; i++) {
            const frac = Math.min(1, Math.abs(trace[i] - mean) / maxDev);
            const halfH = frac * (midY - 4);
            const x = (i / n) * W;
            bars += `<rect x="${x.toFixed(2)}" y="${(midY - halfH).toFixed(2)}" width="${barW.toFixed(2)}" height="${(halfH * 2).toFixed(2)}" rx="1"/>`;
        }
        const svg = `
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="pitch-wave-svg">
                <defs>
                    <clipPath id="pitch-waveform-clip-${id}">
                        <rect id="pitch-waveform-clip-rect-${id}" x="0" y="0" width="0" height="${H}"/>
                    </clipPath>
                </defs>
                <line x1="0" y1="${midY}" x2="${W}" y2="${midY}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
                <g fill="#4b4b52">${bars}</g>
                <g fill="#ffffff" clip-path="url(#pitch-waveform-clip-${id})">${bars}</g>
                <line id="pitch-waveform-playhead-${id}" x1="0" y1="0" x2="0" y2="${H}" stroke="#ffffff" stroke-width="1.5"/>
            </svg>`;
        return { mean, maxDev, svg };
    }

    // Wires up playback for one Pitch Waveform instance: play/pause,
    // click-and-drag seeking on the waveform itself, and an Web Audio
    // oscillator swept through the pitch trace so the contour is
    // actually audible in sync with the visual playhead.
    function wirePitchWaveformPlayback(container, id, trace, duration) {
        const playBtn = container.querySelector(".pitch-play-btn");
        const playIcon = container.querySelector(".pitch-play-icon");
        const pauseIcon = container.querySelector(".pitch-pause-icon");
        const timeReadout = container.querySelector(".pitch-time-readout");
        const clipRect = container.querySelector(`#pitch-waveform-clip-rect-${id}`);
        const playhead = container.querySelector(`#pitch-waveform-playhead-${id}`);
        const seekOverlay = container.querySelector(".pitch-seek-overlay");
        const W = 700;

        let audioCtx = null;
        let oscillator = null;
        let gainNode = null;
        let rafId = null;
        let playing = false;
        let startFrac = 0;    // playback fraction the current oscillator run started from
        let startCtxTime = 0; // audioCtx.currentTime at that moment

        function currentFraction() {
            if (!playing || !audioCtx) return startFrac;
            const elapsed = audioCtx.currentTime - startCtxTime;
            return Math.min(1, startFrac + elapsed / duration);
        }

        function paint(frac) {
            const x = frac * W;
            if (clipRect) clipRect.setAttribute("width", x.toFixed(2));
            if (playhead) { playhead.setAttribute("x1", x.toFixed(2)); playhead.setAttribute("x2", x.toFixed(2)); }
            if (timeReadout) timeReadout.textContent = `${formatClockTime(frac * duration)} / ${formatClockTime(duration)}`;
        }

        function tick() {
            const frac = currentFraction();
            paint(frac);
            if (!playing) return;
            if (frac >= 1) { stop(true); return; }
            rafId = requestAnimationFrame(tick);
        }

        function stopOscillator() {
            if (oscillator) {
                try { oscillator.onended = null; oscillator.stop(); } catch (e) { /* already stopped */ }
                oscillator.disconnect();
                oscillator = null;
            }
            if (gainNode) { gainNode.disconnect(); gainNode = null; }
            if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
        }

        function stop(reset) {
            playing = false;
            stopOscillator();
            if (playIcon) playIcon.style.display = "";
            if (pauseIcon) pauseIcon.style.display = "none";
            if (reset) { startFrac = 0; paint(0); }
        }

        function startFrom(frac) {
            if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            if (audioCtx.state === "suspended") audioCtx.resume();
            stopOscillator();

            startFrac = Math.min(0.999, Math.max(0, frac));
            const remaining = Math.max(0.02, duration * (1 - startFrac));
            const startIdx = Math.min(trace.length - 2, Math.floor(startFrac * trace.length));
            const curve = new Float32Array(trace.slice(startIdx));

            oscillator = audioCtx.createOscillator();
            oscillator.type = "sine";
            gainNode = audioCtx.createGain();
            oscillator.connect(gainNode).connect(audioCtx.destination);

            const now = audioCtx.currentTime;
            const fade = Math.min(0.03, remaining / 3);
            gainNode.gain.setValueAtTime(0, now);
            gainNode.gain.linearRampToValueAtTime(0.15, now + fade);
            gainNode.gain.setValueAtTime(0.15, now + Math.max(fade, remaining - fade));
            gainNode.gain.linearRampToValueAtTime(0, now + remaining);

            oscillator.frequency.setValueCurveAtTime(curve, now, remaining);
            oscillator.start(now);
            oscillator.onended = () => { if (playing) stop(true); };

            startCtxTime = now;
            playing = true;
            if (playIcon) playIcon.style.display = "none";
            if (pauseIcon) pauseIcon.style.display = "";
            rafId = requestAnimationFrame(tick);
        }

        function togglePlay() {
            if (playing) stop(false);
            else startFrom(currentFraction() >= 1 ? 0 : currentFraction());
        }

        function seekToClientX(clientX) {
            const rect = seekOverlay.getBoundingClientRect();
            if (!rect.width) return;
            const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
            if (playing) startFrom(frac);
            else { startFrac = frac; paint(frac); }
        }

        // The card system's drag-start handler listens for mousedown
        // anywhere on a header-less graph widget (see wireWidget's
        // dragSurface) and already skips anything matching
        // ".graph-interactive" — both controls below carry that class —
        // but stopPropagation here too as defense in depth.
        if (playBtn) {
            playBtn.addEventListener("mousedown", (e) => e.stopPropagation());
            playBtn.addEventListener("click", (e) => { e.stopPropagation(); togglePlay(); });
        }

        if (seekOverlay) {
            seekOverlay.addEventListener("mousedown", (e) => {
                e.stopPropagation();
                e.preventDefault();
                seekToClientX(e.clientX);
                function onMove(ev) { seekToClientX(ev.clientX); }
                function onUp() {
                    window.removeEventListener("mousemove", onMove);
                    window.removeEventListener("mouseup", onUp);
                }
                window.addEventListener("mousemove", onMove);
                window.addEventListener("mouseup", onUp);
            });
        }

        paint(0);
        container._pitchWaveformState = { cleanup() { stop(false); } };

        // Hook the widget's close button once so removing the card stops
        // the oscillator/rAF loop instead of leaking them. Re-renders
        // (refreshAllWidgetValues) rebuild this container's innerHTML but
        // never touch the close button itself, so this only needs
        // binding the first time — the listener re-reads
        // container._pitchWaveformState at click time, so it always
        // tears down whichever instance is current.
        const widget = container.closest(".pinboard-widget");
        const closeBtn = widget && widget.querySelector(".pinboard-widget-close-btn, .pinboard-close-btn");
        if (closeBtn && !closeBtn.dataset.pitchWaveformCleanupBound) {
            closeBtn.dataset.pitchWaveformCleanupBound = "1";
            closeBtn.addEventListener("click", () => {
                if (container._pitchWaveformState) container._pitchWaveformState.cleanup();
            });
        }
    }

    // ---- DDK Waveform graph content ----
    //
    // Same mirrored-bar audio-player look as Pitch Waveform, but driven
    // by the DDK intensity/rhythm envelope instead of F0. The backend
    // doesn't expose the real per-frame intensity contour yet (see
    // _ddk_intensity_contour() in feature_extractor.py — it's computed
    // internally for repetition-peak picking but only the scalar
    // aggregates like DDK Repetition Rate/Interval Mean/Regularity are
    // returned), so this is synthesized the same way Pitch Waveform's
    // trace is: a repeating burst envelope (one bump per pa-ta-ka
    // repetition) shaped from ddkRepetitionRate/ddkIntervalMean, with
    // timing jitter scaled by ddkIntervalStd/ddkRegularity so an
    // irregular DDK sequence visibly wobbles. Seeded, not time-based, so
    // it's stable across re-renders. Once a real contour is available
    // (e.g. GET /api/recordings/ddk-intensity-contour), swap it in
    // inside getIntensityTraceForTarget() and nothing else changes.
    let ddkWaveformInstanceCount = 0;
    const DDK_WAVEFORM_SAMPLES = 96;

    function synthesizeIntensityTrace(vals, n) {
        const rate = Math.max(1.5, vals.ddkRepetitionRate || 4.5); // reps/sec
        const period = 1 / rate;
        const duration = DDK_WAVEFORM_DURATION;
        const jitterFrac = Math.min(0.4, Math.max(0.02, (vals.ddkRegularity || 8) / 100));
        const rand = mulberry32(0xD57A11 ^ Math.round(rate * 977));
        const trace = new Array(n);
        // Pre-place burst centers across the duration, each nudged by
        // jitter so the envelope reads as slightly irregular rather than
        // a perfect metronome.
        const centers = [];
        for (let t = period / 2; t < duration; t += period) {
            centers.push(t + (rand() - 0.5) * period * jitterFrac);
        }
        const pauseDip = Math.min(0.6, (vals.pauseSpeechRatio || 0.1));
        for (let i = 0; i < n; i++) {
            const t = (i / (n - 1)) * duration;
            let level = 0;
            for (const c of centers) {
                const d = (t - c) / (period * 0.32);
                level = Math.max(level, Math.exp(-(d * d)));
            }
            trace[i] = 20 + level * 80 * (1 - pauseDip * 0.3);
        }
        return trace;
    }

    // Prefers a real per-frame intensity contour if the backend ever
    // starts sending one (analysisTargetRef._raw.ddk_intensity_contour
    // for a single recording, or the _summary equivalent for a
    // session/subject rollup), falling back to the synthesized stand-in
    // otherwise — same pattern as getPitchTraceForTarget().
    function getIntensityTraceForTarget(vals) {
        const real = analysisTargetType === "recording"
            ? (analysisTargetRef && analysisTargetRef._raw && analysisTargetRef._raw.ddk_intensity_contour)
            : (analysisTargetRef && analysisTargetRef._summary && analysisTargetRef._summary.ddk_intensity_contour);
        if (Array.isArray(real) && real.length > 1) return real;
        return synthesizeIntensityTrace(vals, DDK_WAVEFORM_SAMPLES);
    }

    const DDK_WAVEFORM_DURATION = 4.0;

    // Builds the mirrored-bar SVG for one DDK Waveform instance. Bars
    // are unsigned (0-100 intensity, not mirrored around a mean like
    // pitch), drawn full-height and scaled by level so repetition bursts
    // read as pulses along the track. Same gray-base/clipped-white-top
    // played-progress trick as pitchWaveformSVG.
    function ddkWaveformSVG(id, trace) {
        const W = 700, H = 200;
        const n = trace.length;
        const barW = W / n;
        const bars = trace.map((v, i) => {
            const h = Math.max(2, (v / 100) * H);
            const x = i * barW;
            const y = H - h;
            return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${(barW * 0.7).toFixed(2)}" height="${h.toFixed(2)}"/>`;
        }).join("");
        const svg = `
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
                <defs>
                    <clipPath id="ddk-waveform-clip-${id}">
                        <rect id="ddk-waveform-clip-rect-${id}" x="0" y="0" width="0" height="${H}"/>
                    </clipPath>
                </defs>
                <g fill="#4c4c52">${bars}</g>
                <g fill="#6ea8fe" clip-path="url(#ddk-waveform-clip-${id})">${bars}</g>
                <line id="ddk-waveform-playhead-${id}" x1="0" y1="0" x2="0" y2="${H}" stroke="#6ea8fe" stroke-width="1.5"/>
            </svg>`;
        return { svg };
    }

    // Wires up playback for one DDK Waveform instance: play/pause,
    // click-and-drag seeking, and a clip-path playhead sweep — mirrors
    // wirePitchWaveformPlayback() exactly, just namespaced to "ddk-".
    function wireDDKWaveformPlayback(container, id, trace, duration) {
        const playBtn = container.querySelector(".pitch-play-btn");
        const playIcon = container.querySelector(".pitch-play-icon");
        const pauseIcon = container.querySelector(".pitch-pause-icon");
        const timeReadout = container.querySelector(".pitch-time-readout");
        const seekOverlay = container.querySelector(".pitch-seek-overlay");
        const clipRect = container.querySelector(`#ddk-waveform-clip-rect-${id}`);
        const playhead = container.querySelector(`#ddk-waveform-playhead-${id}`);
        if (!playBtn || !clipRect || !playhead) return;

        let playing = false, startTs = null, elapsed = 0, rafId = null;
        let audioCtx = null, oscNode = null, gainNode = null;

        function setProgress(t) {
            const frac = Math.min(1, Math.max(0, t / duration));
            clipRect.setAttribute("width", String(700 * frac));
            playhead.setAttribute("x1", String(700 * frac));
            playhead.setAttribute("x2", String(700 * frac));
            timeReadout.textContent = `${formatClockTime(t)} / ${formatClockTime(duration)}`;
        }

        function currentIntensityAt(t) {
            const idx = Math.min(trace.length - 1, Math.max(0, Math.round((t / duration) * (trace.length - 1))));
            return trace[idx];
        }

        function ensureAudio() {
            if (audioCtx) return;
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) return;
            audioCtx = new Ctx();
            oscNode = audioCtx.createOscillator();
            gainNode = audioCtx.createGain();
            oscNode.type = "square";
            oscNode.frequency.value = 220;
            gainNode.gain.value = 0;
            oscNode.connect(gainNode).connect(audioCtx.destination);
            oscNode.start();
        }

        function tick(ts) {
            if (!playing) return;
            if (startTs === null) startTs = ts;
            const t = elapsed + (ts - startTs) / 1000;
            if (t >= duration) { stop(true); return; }
            setProgress(t);
            if (gainNode) gainNode.gain.value = (currentIntensityAt(t) / 100) * 0.05;
            rafId = requestAnimationFrame(tick);
        }

        function play() {
            if (playing) return;
            playing = true;
            startTs = null;
            ensureAudio();
            if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
            playIcon.style.display = "none";
            pauseIcon.style.display = "";
            rafId = requestAnimationFrame(tick);
        }

        function stop(reset) {
            playing = false;
            if (rafId) cancelAnimationFrame(rafId);
            rafId = null;
            if (gainNode) gainNode.gain.value = 0;
            playIcon.style.display = "";
            pauseIcon.style.display = "none";
            if (reset) { elapsed = 0; setProgress(0); }
        }

        playBtn.addEventListener("click", () => {
            if (playing) { elapsed = elapsed + (startTs !== null ? (performance.now() - startTs) / 1000 : 0); stop(false); }
            else play();
        });

        if (seekOverlay) {
            const seekTo = (clientX) => {
                const rect = seekOverlay.getBoundingClientRect();
                const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
                elapsed = frac * duration;
                startTs = null;
                setProgress(elapsed);
            };
            seekOverlay.addEventListener("mousedown", (e) => {
                e.stopPropagation();
                e.preventDefault();
                seekTo(e.clientX);
                function onMove(ev) { seekTo(ev.clientX); }
                function onUp() {
                    window.removeEventListener("mousemove", onMove);
                    window.removeEventListener("mouseup", onUp);
                }
                window.addEventListener("mousemove", onMove);
                window.addEventListener("mouseup", onUp);
            });
        }

        setProgress(0);

        container._ddkWaveformState = { cleanup() { stop(false); if (audioCtx) audioCtx.close(); } };

        const widget = container.closest(".pinboard-widget");
        const closeBtn = widget && widget.querySelector(".pinboard-widget-close-btn, .pinboard-close-btn");
        if (closeBtn && !closeBtn.dataset.ddkWaveformCleanupBound) {
            closeBtn.dataset.ddkWaveformCleanupBound = "1";
            closeBtn.addEventListener("click", () => {
                if (container._ddkWaveformState) container._ddkWaveformState.cleanup();
            });
        }
    }

    // Entry point for the DDK Waveform widget. A single recording has a
    // real WAV file behind it, so try that first (real waveform + real
    // playback); only fall back to the synthesized burst-envelope stand-in
    // if there's no audio to point at (target isn't a recording, or the
    // file failed to load).
    function renderDDKWaveform(container) {
        if (container._ddkWaveformState) container._ddkWaveformState.cleanup();
        if (container._realWaveformState) container._realWaveformState.cleanup();

        // Recording-only widget (see updateWidgetButtonsAvailability) --
        // if the analysis target changes out from under an already-open
        // DDK Waveform widget (e.g. user switches to a session), show
        // the empty state instead of a stale or meaningless trace.
        if (analysisTargetType !== "recording") {
            container.innerHTML = graphEmptyStateHTML("DDK Waveform");
            return;
        }
        const filepath = analysisTargetRef && analysisTargetRef._raw && analysisTargetRef._raw.patient_filepath;
        const vals = getDdkValuesForTarget();

        // Real playback only needs the WAV file, not the analysis stats --
        // check for it first so a recording still awaiting feature
        // extraction shows the real waveform instead of "no data yet".
        if (filepath) {
            renderRealAudioWaveform(container, {
                title: "DDK Waveform",
                subtitle: "Real waveform of the recorded pa-ta-ka repetitions",
                filepath,
                color: "#6ea8fe",
                fallback: () => {
                    if (vals) renderSynthesizedDDKWaveform(container, vals);
                    else container.innerHTML = graphEmptyStateHTML("DDK Waveform");
                },
            });
            return;
        }

        if (!vals) { container.innerHTML = graphEmptyStateHTML("DDK Waveform"); return; }
        renderSynthesizedDDKWaveform(container, vals);
    }

    function renderSynthesizedDDKWaveform(container, vals) {
        if (container._ddkWaveformState) container._ddkWaveformState.cleanup();

        const id = ++ddkWaveformInstanceCount;
        const trace = getIntensityTraceForTarget(vals);
        const { svg } = ddkWaveformSVG(id, trace);
        const duration = DDK_WAVEFORM_DURATION;
        const xTicks = [0, 1, 2, 3, 4].map((i) => ((duration / 4) * i).toFixed(1) + "s");

        container.innerHTML = `
            <div class="area-root">
                <div class="area-header">
                    <div>
                        <div class="area-title">DDK Waveform</div>
                        <div class="area-sub">Intensity envelope of pa-ta-ka repetitions</div>
                    </div>
                    <div class="pitch-controls-pill">
                        <button type="button" class="pitch-play-btn graph-interactive" title="Play" aria-label="Play">
                            <svg class="pitch-play-icon" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                            <svg class="pitch-pause-icon" viewBox="0 0 24 24" fill="currentColor" style="display:none"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>
                        </button>
                        <span class="pitch-time-readout">0:00 / ${formatClockTime(duration)}</span>
                    </div>
                </div>
                <div class="area-body">
                    <div class="area-yaxis"><span>100</span><span>50</span><span>0</span></div>
                    <div class="area-chart-wrap pitch-chart-wrap">
                        ${svg}
                        <div class="pitch-seek-overlay graph-interactive"></div>
                    </div>
                </div>
                <div class="area-xaxis-row">
                    <div class="area-xaxis-spacer"></div>
                    <div class="area-xaxis">${xTicks.map((t) => `<span>${t}</span>`).join("")}</div>
                </div>
            </div>`;

        wireDDKWaveformPlayback(container, id, trace, duration);
    }

    // Entry point for the Pitch Waveform widget. Recording-only, same as
    // DDK Waveform (see updateWidgetButtonsAvailability) — a waveform
    // plots one audio clip and has no coherent meaning averaged across a
    // session/subject's several trials, so those targets get the empty
    // state instead of the old synthesized F0 stand-in.
    function renderPitchWaveform(container) {
        if (container._pitchWaveformState) container._pitchWaveformState.cleanup();
        if (container._realWaveformState) container._realWaveformState.cleanup();

        if (analysisTargetType !== "recording") {
            container.innerHTML = graphEmptyStateHTML("Pitch Waveform");
            return;
        }

        const filepath = analysisTargetRef && analysisTargetRef._raw && analysisTargetRef._raw.patient_filepath;
        const vals = getSustainedValuesForTarget();

        // Real playback only needs the WAV file, not the analysis stats --
        // check for it first so a recording still awaiting feature
        // extraction shows the real waveform instead of "no data yet".
        if (filepath) {
            renderRealAudioWaveform(container, {
                title: "Pitch Waveform",
                subtitle: "Real waveform of the recorded sustained /a/",
                filepath,
                color: "#ffffff",
                fallback: () => {
                    if (vals) renderSynthesizedPitchWaveform(container, vals);
                    else container.innerHTML = graphEmptyStateHTML("Pitch Waveform");
                },
            });
            return;
        }

        if (!vals) { container.innerHTML = graphEmptyStateHTML("Pitch Waveform"); return; }
        renderSynthesizedPitchWaveform(container, vals);
    }

    function renderSynthesizedPitchWaveform(container, vals) {
        if (container._pitchWaveformState) container._pitchWaveformState.cleanup();

        const id = ++pitchWaveformInstanceCount;
        const trace = getPitchTraceForTarget(vals);
        const { mean, maxDev, svg } = pitchWaveformSVG(id, trace);
        const duration = PITCH_WAVEFORM_DURATION;

        const yTop = Math.round(mean + maxDev);
        const yMid = Math.round(mean);
        const xTicks = [0, 1, 2, 3, 4].map((i) => ((duration / 4) * i).toFixed(1) + "s");

        container.innerHTML = `
            <div class="area-root">
                <div class="area-header">
                    <div>
                        <div class="area-title">Pitch Waveform</div>
                        <div class="area-sub">F0 mirrored around its mean for a sustained /a/</div>
                    </div>
                    <div class="pitch-controls-pill">
                        <button type="button" class="pitch-play-btn graph-interactive" title="Play" aria-label="Play">
                            <svg class="pitch-play-icon" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                            <svg class="pitch-pause-icon" viewBox="0 0 24 24" fill="currentColor" style="display:none"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>
                        </button>
                        <span class="pitch-time-readout">0:00 / ${formatClockTime(duration)}</span>
                    </div>
                </div>
                <div class="area-body">
                    <div class="area-yaxis"><span>${yTop} Hz</span><span>${yMid} Hz</span><span>${yTop} Hz</span></div>
                    <div class="area-chart-wrap pitch-chart-wrap">
                        ${svg}
                        <div class="pitch-seek-overlay graph-interactive"></div>
                    </div>
                </div>
                <div class="area-xaxis-row">
                    <div class="area-xaxis-spacer"></div>
                    <div class="area-xaxis">${xTicks.map((t) => `<span>${t}</span>`).join("")}</div>
                </div>
            </div>`;

        wirePitchWaveformPlayback(container, id, trace, duration);
    }

    // Registry of graph widgets that have real render content wired up.
    // Only Spectrogram, Formants, Voice Quality, Voice Metrics, and
    // Pitch Waveform are ported for now — Contours stays as an empty
    // placeholder until requested.
    //
    // taskType is "Sustained", "DDK", or "Both" (task-agnostic) -- see
    // the big comment above getAvailableTaskTypesForTarget() near the
    // top of this file for the filtering this drives, and read it
    // before adding a new graph here so it gets tagged correctly.
    //
    // Formants and Voice Quality read live Sustained-vowel data (see
    // getSustainedValuesForTarget()), so they're tagged Sustained.
    // Spectrogram is tagged "Both": for a single-recording target it
    // renders the real compute_spectrogram() STFT of that recording's
    // waveform (see renderRealSpectrogram/api.getRecordingSpectrogram),
    // which is task-agnostic and works just as well for DDK audio; it
    // only falls back to the Sustained-only synthesized stand-in (see
    // renderSynthesizedSpectrogram) if that recording's real fetch
    // fails. A session/subject aggregate target has no single waveform
    // to analyze, so it shows the empty state instead of synthesizing
    // stand-in data.
    const GRAPH_RENDERERS = {
        Spectrogram: { render: renderSpectrogram, width: 520, height: 340, taskType: "Both" },
        Formants: { render: renderFormants, width: 320, height: 200, taskType: "Sustained" },
        "Voice Quality": { render: renderVoiceQuality, width: 320, height: 200, taskType: "Sustained" },
        "Voice Metrics": { render: renderAreaChart, width: 520, height: 320, taskType: "Both" },
        "Pitch Waveform": { render: renderPitchWaveform, width: 520, height: 320, taskType: "Sustained" },
        "DDK Waveform": { render: renderDDKWaveform, width: 520, height: 320, taskType: "DDK" },
    };

    // Exposed so top-level code (updateWidgetButtonsAvailability, outside
    // this IIFE) can filter graph buttons by task type without duplicating
    // GRAPH_RENDERERS as the source of truth.
    window.GRAPH_TASK_TYPES = Object.fromEntries(
        Object.entries(GRAPH_RENDERERS).map(([title, cfg]) => [title, cfg.taskType])
    );

    // Builds a widget's inner markup for a given title/valueType — pulled
    // out so it can be reused both for real widgets and for measuring a
    // hypothetical widget's natural size (see measureWidgetWidth).
    function buildWidgetMarkup(widgetTitle, valueType) {
        const isMetricType = widgetTitle === "Values" || widgetTitle === "Quality";
        const subtypeHtml = isMetricType && valueType
            ? `<span class="pinboard-widget-subtype">${valueType}</span>`
            : "";
        const emptyText = isMetricType ? "No recordings selected yet" : "No graph selected yet";
        const metrics = isMetricType ? ((WIDGET_METRICS[widgetTitle] && WIDGET_METRICS[widgetTitle][valueType]) || []) : [];
        const metricValues = isMetricType ? getWidgetValuesSync(widgetTitle, valueType) : {};

        const bodyHtml = metrics.length
            ? `<div class="pinboard-values-list">
                ${metrics.map(label => `
                <div class="pinboard-values-row" data-metric-key="${label}">
                    <span class="pinboard-values-label">${label}</span>
                    <span class="pinboard-values-value">${metricValues[label] !== undefined ? metricValues[label] : "&mdash;"}</span>
                </div>`).join("")}
            </div>`
            : `<div class="pinboard-widget-empty">${emptyText}</div>`;
        const bodyClass = metrics.length ? "pinboard-widget-body pinboard-widget-body--list" : "pinboard-widget-body";

        if (!isMetricType) {
            // Graph placeholder widgets (Formants, Voice Quality, Spectrogram,
            // Voice Metrics, and any plain "Widget N") are left completely
            // empty — no header, no title, no pin control — with only a
            // content container (used by graph render functions), a
            // hover-revealed close button in the corner, and the resize
            // handle.
            return `
                <div class="pinboard-widget-graph-content"></div>
                <button type="button" class="pinboard-widget-close-btn" title="Remove widget" aria-label="Remove graph">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
                </button>
                <div class="pinboard-widget-resize-handle"></div>
            `;
        }

        return `
            <div class="pinboard-widget-header">
                <span class="pinboard-widget-title">${widgetTitle}</span>
                ${subtypeHtml}
                <div class="pinboard-widget-actions">
                    <button type="button" class="pinboard-widget-btn pinboard-pin-btn" title="Pin in place">
                        <svg class="pin-icon" viewBox="0 0 85 97" xmlns="http://www.w3.org/2000/svg">
                            <path class="pin-fill" fill-rule="evenodd" d="
                                M33,24 L58,24 L58,29 L55,30 L55,46 L60,52 L60,56 L48,57 L48,71
                                L45.5,74 L43,71 L43,57 L31,56 L31,52 L36,46 L36,30 L33,29 Z
                                M41,30 L50,30 L50,49 L41,49 Z
                            "/>
                        </svg>
                    </button>
                    <button type="button" class="pinboard-widget-btn pinboard-close-btn" title="Remove widget">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                            <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" />
                        </svg>
                    </button>
                </div>
            </div>
            <div class="${bodyClass}">
                ${bodyHtml}
            </div>
            <div class="pinboard-widget-resize-handle"></div>
        `;
    }

    // Re-reads current values for one widget and patches its rows in
    // place (no re-render) — used once a pending subject/session summary
    // fetch lands, so any Values widget already on the board picks up the
    // real numbers instead of staying on em-dashes.
    function refreshWidgetValues(widget) {
        const kind = widget.dataset.widgetKind;
        const widgetTitle = kind === "values" ? "Values" : kind === "quality" ? "Quality" : null;
        if (!widgetTitle) return;
        const values = getWidgetValuesSync(widgetTitle, widget.dataset.valueType);
        widget.querySelectorAll(".pinboard-values-row").forEach(row => {
            const key = row.dataset.metricKey;
            const valueEl = row.querySelector(".pinboard-values-value");
            if (valueEl) valueEl.textContent = (key in values) ? values[key] : "\u2014";
        });
    }

    window.refreshAllWidgetValues = function () {
        board.querySelectorAll(".pinboard-widget[data-widget-kind]").forEach(refreshWidgetValues);
        // Also re-render every open graph widget (Formants, Voice Quality,
        // Spectrogram, Voice Metrics) so they pick up the fresh
        // _summary/_raw data too, not just the Values/Quality number
        // widgets above -- e.g. after a new recording is added to the
        // session/subject currently being analyzed. Each graph reads its
        // own live data on every render (see getSustainedValuesForTarget/
        // getDdkValuesForTarget), so simply calling render() again is
        // enough; no separate "patch in place" step is needed the way
        // refreshWidgetValues() does for Values/Quality rows.
        board.querySelectorAll(".pinboard-widget[data-graph-title]").forEach(widget => {
            const renderer = GRAPH_RENDERERS[widget.dataset.graphTitle];
            const content = widget.querySelector(".pinboard-widget-graph-content");
            if (renderer && content) renderer.render(content);
        });
        // Also re-run task-type filtering (see getAvailableTaskTypesForTarget()
        // near the top of this file) now that a lazily-fetched session/subject
        // summary has landed -- until now we didn't know which task types were
        // actually present, so buttons/dropdown options were left showing.
        if (typeof updateWidgetButtonsAvailability === "function") updateWidgetButtonsAvailability();
    };

    // Measures the natural width a widget of the given kind would have,
    // by rendering it hidden off to the side and reading its offsetWidth.
    // Used so DDK can be placed flush against Sustained's right edge even
    // when no Sustained widget currently exists on the board.
    function measureWidgetWidth(widgetTitle, valueType) {
        return measureWidgetSize(widgetTitle, valueType).w;
    }

    function measureWidgetSize(widgetTitle, valueType) {
        const probe = document.createElement("div");
        probe.className = "pinboard-widget";
        probe.style.position = "absolute";
        probe.style.width = "max-content";
        probe.style.height = "max-content";
        probe.style.visibility = "hidden";
        probe.innerHTML = buildWidgetMarkup(widgetTitle, valueType);
        canvas.appendChild(probe);
        const boardRect = board.getBoundingClientRect();
        const isMetricType = widgetTitle === "Values" || widgetTitle === "Quality";
        const naturalW = probe.offsetWidth + (isMetricType ? METRIC_WIDTH_BUFFER : 0);
        const w = clamp(naturalW, MIN_W, boardRect.width);
        const h = clamp(probe.offsetHeight, MIN_H, boardRect.height);
        probe.remove();
        return { w, h };
    }

    function createWidget(title, valueType) {
        widgetCount += 1;
        const widgetTitle = title || `Widget ${widgetCount}`;
        const isMetricType = widgetTitle === "Values" || widgetTitle === "Quality";

        const widget = document.createElement("div");
        widget.className = "pinboard-widget";
        if (isMetricType) {
            widget.dataset.widgetKind = widgetTitle.toLowerCase();
            widget.dataset.valueType = valueType || "";
        } else {
            // Graph widgets aren't tagged with data-widget-kind (that's
            // reserved for Values/Quality), but we still stash the title
            // so the "already on the pinboard" check can name it later.
            widget.dataset.graphTitle = widgetTitle;
        }
        widget.innerHTML = buildWidgetMarkup(widgetTitle, valueType);

        // Size the widget to just fit its content (header + body) rather than
        // a fixed footprint, by measuring its natural (max-content) size once
        // it's in the DOM, then locking that in as an explicit px size.
        const boardRect = board.getBoundingClientRect();

        widget.style.position = "absolute";
        widget.style.width = "max-content";
        widget.style.height = "max-content";
        widget.style.visibility = "hidden";
        widget.style.zIndex = ++zCounter;
        canvas.appendChild(widget);

        // Ambient/Spectral is forced to match RMS/Noise/Clipping's natural
        // width, rather than sizing to its own (shorter) content, so the
        // two Quality widgets always default to the same width.
        const isAmbientQuality = widgetTitle === "Quality" && valueType === "Ambient/Spectral";
        // Overall is likewise forced to match SNR/Signal's natural width.
        const isOverallQuality = widgetTitle === "Quality" && valueType === "Overall";
        // Graph widgets (the plain "Widget N" placeholders from "Add Graph")
        // default to a fixed 30vw instead of sizing to their placeholder text.
        // Widgets with a registered renderer (see GRAPH_RENDERERS) use that
        // renderer's own default width/height instead.
        const graphRenderer = GRAPH_RENDERERS[widgetTitle];
        const isGraphWidget = !isMetricType;
        let naturalW = widget.offsetWidth;
        let naturalH = widget.offsetHeight;
        if (isAmbientQuality) {
            naturalW = measureWidgetWidth("Quality", "RMS/Noise/Clipping");
        } else if (isOverallQuality) {
            naturalW = measureWidgetWidth("Quality", "SNR/Signal");
        } else if (graphRenderer) {
            naturalW = graphRenderer.width;
            naturalH = graphRenderer.height;
        } else if (isGraphWidget) {
            naturalW = window.innerWidth * 0.30;
        } else if (isMetricType) {
            naturalW += METRIC_WIDTH_BUFFER;
        }

        const widgetW = clamp(naturalW, MIN_W, boardRect.width);
        const widgetH = clamp(naturalH, MIN_H, boardRect.height);

        const maxLeft = Math.max(0, boardRect.width - widgetW);
        const maxTop = Math.max(0, boardRect.height - widgetH);

        // Fixed spawn points — no memory of previous widgets, no shifting
        // to avoid overlap. Every widget of a given kind always lands in
        // the same spot; the user repositions it manually if they want.
        const isSustainedValues = widgetTitle === "Values" && valueType === "Sustained";
        const isDdkValues = widgetTitle === "Values" && valueType === "DDK";
        const isRmsQuality = widgetTitle === "Quality" && valueType === "RMS/Noise/Clipping";
        const isSnrQuality = widgetTitle === "Quality" && valueType === "SNR/Signal";
        const isAmbientPlacement = widgetTitle === "Quality" && valueType === "Ambient/Spectral";
        const isOverallPlacement = widgetTitle === "Quality" && valueType === "Overall";

        let desiredLeft;
        let desiredTop;
        if (isSustainedValues) {
            desiredLeft = 0; // touch the left edge
            desiredTop = 0; // touch the top edge
        } else if (isDdkValues) {
            // A directly-selected DDK recording has no Sustained widget to
            // sit beside (there's only ever one task type per recording),
            // so it goes in the top-left corner instead, flush against
            // both the left and top edges of the board.
            if (getDirectRecordingValueType() === "DDK") {
                desiredLeft = 0; // touch the left edge
                desiredTop = 0; // touch the top edge
            } else {
                const sustainedWidth = measureWidgetWidth("Values", "Sustained");
                desiredLeft = clamp(sustainedWidth, 0, maxLeft); // touch Sustained's right edge
                desiredTop = 0; // touch the top edge
            }
        } else if (isRmsQuality) {
            desiredLeft = maxLeft; // touch the right edge
            desiredTop = 0; // touch the top edge
        } else if (isSnrQuality) {
            const rmsWidth = measureWidgetWidth("Quality", "RMS/Noise/Clipping");
            const rmsLeft = Math.max(0, boardRect.width - rmsWidth); // RMS's left edge
            desiredLeft = clamp(rmsLeft - widgetW, 0, maxLeft); // touch RMS's left edge
            desiredTop = 0; // touch the top edge
        } else if (isAmbientPlacement) {
            const rmsSize = measureWidgetSize("Quality", "RMS/Noise/Clipping");
            const rmsLeft = Math.max(0, boardRect.width - rmsSize.w); // RMS's left edge
            desiredLeft = clamp(rmsLeft, 0, maxLeft); // align under RMS's left edge
            desiredTop = clamp(rmsSize.h, 0, maxTop); // touch RMS's bottom edge
        } else if (isOverallPlacement) {
            const rmsWidth = measureWidgetWidth("Quality", "RMS/Noise/Clipping");
            const snrSize = measureWidgetSize("Quality", "SNR/Signal");
            const rmsLeft = Math.max(0, boardRect.width - rmsWidth); // RMS's left edge
            const snrLeft = rmsLeft - snrSize.w; // SNR's left edge (touches RMS's left edge)
            desiredLeft = clamp(snrLeft, 0, maxLeft); // align under SNR's left edge
            desiredTop = clamp(snrSize.h, 0, maxTop); // touch SNR's bottom edge
        } else {
            desiredLeft = clamp(SPAWN_LEFT, 0, maxLeft);
            desiredTop = clamp(SPAWN_TOP, 0, maxTop);
        }

        widget.style.width = widgetW + "px";
        widget.style.height = widgetH + "px";
        widget.style.left = desiredLeft + "px";
        widget.style.top = desiredTop + "px";
        widget.style.visibility = "";

        // Graph widgets with a registered renderer (currently just
        // Spectrogram) draw their content now that the widget has its real
        // on-board size — canvas-based renderers measure their wrapper's
        // clientWidth/clientHeight, which isn't reliable until this point.
        if (graphRenderer) {
            const content = widget.querySelector(".pinboard-widget-graph-content");
            if (content) graphRenderer.render(content);
        }

        // Lock in this natural size as the 1x baseline for text/icon scaling.
        widget.dataset.baseW = widgetW;
        widget.dataset.baseH = widgetH;
        updateWidgetScale(widget);

        bringToFront(widget);
        wireWidget(widget);
    }

    function bringToFront(widget) {
        widget.style.zIndex = ++zCounter;
    }

    // Scales the widget's text/icons/padding to match its current footprint.
    // baseW/baseH (stored on the widget when it's created) are the widget's
    // "natural" content-fit size — i.e. the size at which text should render
    // at 1x. Growing/shrinking the widget from there scales everything
    // proportionally instead of just changing how much empty space there is.
    const MIN_SCALE = 0.75;
    const MAX_SCALE = 2.25;

    function updateWidgetScale(widget) {
        const baseW = parseFloat(widget.dataset.baseW) || widget.offsetWidth;
        const baseH = parseFloat(widget.dataset.baseH) || widget.offsetHeight;
        if (!baseW || !baseH) return;
        const scale = clamp(
            Math.min(widget.offsetWidth / baseW, widget.offsetHeight / baseH),
            MIN_SCALE,
            MAX_SCALE
        );
        widget.style.setProperty("--w-scale", scale.toFixed(3));
    }

    function wireWidget(widget) {
        const header = widget.querySelector(".pinboard-widget-header");
        const pinBtn = widget.querySelector(".pinboard-pin-btn");
        const closeBtn = widget.querySelector(".pinboard-close-btn, .pinboard-widget-close-btn");
        const resizeHandle = widget.querySelector(".pinboard-widget-resize-handle");
        // Graph placeholder widgets have no header (see buildWidgetMarkup) —
        // they're dragged from anywhere on the widget body instead, and have
        // no pin control (only the hover-revealed close button) to wire up.
        const dragSurface = header || widget;

        widget.addEventListener("mousedown", () => bringToFront(widget));

        // ---- Drag (from the header, unless pinned) ----
        dragSurface.addEventListener("mousedown", (e) => {
            if (e.target.closest(".pinboard-widget-btn")) return;
            if (e.target.closest(".pinboard-widget-close-btn")) return;
            if (e.target.closest(".pinboard-widget-resize-handle")) return;
            // Generic escape hatch for any interactive control inside a
            // header-less graph widget (e.g. Pitch Waveform's play button
            // and seek area) — .card-content's whole-widget drag surface
            // would otherwise swallow clicks meant for the control.
            if (e.target.closest(".graph-interactive")) return;
            if (widget.classList.contains("pinned")) return;
            e.preventDefault();

            const boardRect = board.getBoundingClientRect();
            const startX = e.clientX;
            const startY = e.clientY;
            const startLeft = widget.offsetLeft;
            const startTop = widget.offsetTop;

            widget.classList.add("dragging");

            function onMove(ev) {
                // The board can be zoomed in/out (see the pan/zoom camera
                // further down), so a given on-screen mouse movement no
                // longer always equals that many canvas pixels — divide
                // by the live scale to keep the widget glued to the cursor.
                const camScale = (typeof window.getPinboardScale === "function") ? window.getPinboardScale() : 1;
                const dx = (ev.clientX - startX) / camScale;
                const dy = (ev.clientY - startY) / camScale;
                // Clamp against the canvas's current *accessible* bounds
                // (the initial default view, grown to include whatever
                // area zooming/panning has revealed since) rather than the
                // fixed on-screen viewport size — otherwise widgets could
                // never be moved past the original default-view edges no
                // matter how far the user had zoomed out. See the pinboard
                // pan/zoom camera IIFE further down for how these bounds
                // grow and persist.
                const bounds = (typeof window.getPinboardAccessibleBounds === "function")
                    ? window.getPinboardAccessibleBounds()
                    : { left: 0, top: 0, right: boardRect.width, bottom: boardRect.height };
                const minLeft = bounds.left;
                const minTop = bounds.top;
                const maxLeft = Math.max(minLeft, bounds.right - widget.offsetWidth);
                const maxTop = Math.max(minTop, bounds.bottom - widget.offsetHeight);
                widget.style.left = clamp(startLeft + dx, minLeft, maxLeft) + "px";
                widget.style.top = clamp(startTop + dy, minTop, maxTop) + "px";
            }

            function onUp() {
                widget.classList.remove("dragging");
                window.removeEventListener("mousemove", onMove);
                window.removeEventListener("mouseup", onUp);
            }

            window.addEventListener("mousemove", onMove);
            window.addEventListener("mouseup", onUp);
        });

        // ---- Resize (from the bottom-right corner, unless pinned) ----
        resizeHandle.addEventListener("mousedown", (e) => {
            if (widget.classList.contains("pinned")) return;
            e.preventDefault();
            e.stopPropagation();
            bringToFront(widget);

            const boardRect = board.getBoundingClientRect();
            const startX = e.clientX;
            const startY = e.clientY;
            const startW = widget.offsetWidth;
            const startH = widget.offsetHeight;

            function onMove(ev) {
                // Same scale correction as widget dragging above.
                const camScale = (typeof window.getPinboardScale === "function") ? window.getPinboardScale() : 1;
                const dx = (ev.clientX - startX) / camScale;
                const dy = (ev.clientY - startY) / camScale;
                // Same accessible-bounds clamp as dragging above, so a
                // widget can be grown into newly revealed canvas space
                // instead of being capped at the original viewport edge.
                const bounds = (typeof window.getPinboardAccessibleBounds === "function")
                    ? window.getPinboardAccessibleBounds()
                    : { left: 0, top: 0, right: boardRect.width, bottom: boardRect.height };
                const maxW = bounds.right - widget.offsetLeft;
                const maxH = bounds.bottom - widget.offsetTop;

                const newW = clamp(startW + dx, MIN_W, Math.max(MIN_W, maxW));
                let newH = clamp(startH + dy, MIN_H, Math.max(MIN_H, maxH));

                widget.style.width = newW + "px";
                widget.style.height = newH + "px";
                updateWidgetScale(widget);

                // Don't let the widget shrink vertically past what its content
                // (at the current text scale) actually needs — otherwise the
                // body would need to scroll. Grow back to fit instead.
                const body = widget.querySelector(".pinboard-widget-body");
                if (body && body.scrollHeight > body.clientHeight + 1) {
                    const header = widget.querySelector(".pinboard-widget-header");
                    const needed = (header ? header.offsetHeight : 0) + body.scrollHeight;
                    newH = clamp(Math.max(newH, needed), MIN_H, Math.max(MIN_H, maxH));
                    widget.style.height = newH + "px";
                    updateWidgetScale(widget);
                }
            }

            function onUp() {
                window.removeEventListener("mousemove", onMove);
                window.removeEventListener("mouseup", onUp);
            }

            window.addEventListener("mousemove", onMove);
            window.addEventListener("mouseup", onUp);
        });

        // ---- Pin toggle ----
        if (pinBtn) {
            pinBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                const pinned = widget.classList.toggle("pinned");
                pinBtn.classList.toggle("active", pinned);
                pinBtn.title = pinned ? "Unpin" : "Pin in place";
            });
        }

        // ---- Remove ----
        if (closeBtn) {
            closeBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                widget.remove();
            });
        }
    }

    // ---- Formants / Voice Quality / Spectrogram / Voice Metrics buttons ----
    // Same behavior as the Graphs button (plain graph-placeholder widgets),
    // just pre-labeled instead of falling back to "Widget N".
    const addFormantsBtn = document.getElementById("add-formants-btn");
    const addVoiceQualityBtn = document.getElementById("add-voice-quality-btn");
    const addSpectrogramBtn = document.getElementById("add-spectrogram-btn");
    const addVoiceMetricsBtn = document.getElementById("add-voice-metrics-btn");
    const addPitchWaveformBtn = document.getElementById("add-pitch-waveform-btn");
    const addDdkWaveformBtn = document.getElementById("add-ddk-waveform-btn");

    // Only one widget of each graph type (Formants / Voice Quality /
    // Spectrogram / Voice Metrics / Pitch Waveform) is allowed on the pinboard at a
    // time — different graph types can still coexist. Graph widgets
    // are tagged with data-graph-title (data-widget-kind is reserved
    // for the Values/Quality metric widgets). If one of this type is
    // already up there, focus/highlight it and let the user know
    // instead of adding a duplicate.
    function addGraphWidget(title) {
        const existing = board.querySelector(`.pinboard-widget[data-graph-title="${title}"]`);
        if (existing) {
            bringToFront(existing);
            existing.classList.remove("pinboard-widget-highlight");
            void existing.offsetWidth;
            existing.classList.add("pinboard-widget-highlight");
            showToast(`A ${title} widget is already on the pinboard.`);
            return;
        }
        createWidget(title);
    }

    if (addFormantsBtn) addFormantsBtn.addEventListener("click", () => addGraphWidget("Formants"));
    if (addVoiceQualityBtn) addVoiceQualityBtn.addEventListener("click", () => addGraphWidget("Voice Quality"));
    if (addSpectrogramBtn) addSpectrogramBtn.addEventListener("click", () => addGraphWidget("Spectrogram"));
    if (addVoiceMetricsBtn) addVoiceMetricsBtn.addEventListener("click", () => addGraphWidget("Voice Metrics"));
    if (addPitchWaveformBtn) addPitchWaveformBtn.addEventListener("click", () => addGraphWidget("Pitch Waveform"));
    if (addDdkWaveformBtn) addDdkWaveformBtn.addEventListener("click", () => addGraphWidget("DDK Waveform"));

    // ---- Widget type dropdowns (Values: Sustained vowel / DDK — Quality: Overall / SNR / RMS / Ambient) ----
    const typeDropdowns = [];

    function closeAllTypeDropdowns() {
        typeDropdowns.forEach(dd => dd.classList.remove("open"));
    }
    // Exposed so the recording-select dropdown (wired up elsewhere) can
    // close these when it opens, and vice versa.
    window.closeAllTypeDropdowns = closeAllTypeDropdowns;

    function addOrFocusWidget(widgetTitle, valueType, label) {
        const existing = board.querySelector(
            `.pinboard-widget[data-widget-kind="${widgetTitle.toLowerCase()}"][data-value-type="${valueType}"]`
        );

        if (existing) {
            bringToFront(existing);
            existing.classList.remove("pinboard-widget-highlight");
            // Force reflow so the highlight animation can replay.
            void existing.offsetWidth;
            existing.classList.add("pinboard-widget-highlight");
            showToast(`A ${label} widget is already on the pinboard.`);
        } else {
            createWidget(widgetTitle, valueType);
        }
    }

    function wireTypeDropdown(triggerId, wrapId, dropdownId, widgetTitle) {
        const trigger = document.getElementById(triggerId);
        const wrap = document.getElementById(wrapId);
        const dropdown = document.getElementById(dropdownId);
        if (!trigger || !wrap || !dropdown) return;

        typeDropdowns.push(dropdown);

        trigger.addEventListener("click", (e) => {
            e.stopPropagation();

            if (typeof window.closeRecordingSelectDropdown === "function") {
                window.closeRecordingSelectDropdown();
            }

            if (widgetTitle === "Values") {
                const directType = getDirectRecordingValueType();
                if (directType) {
                    closeAllTypeDropdowns();
                    addOrFocusWidget(widgetTitle, directType, directType === "Sustained" ? "Sustained vowel" : "DDK");
                    return;
                }
            }

            const willOpen = !dropdown.classList.contains("open");
            closeAllTypeDropdowns();
            if (willOpen) dropdown.classList.add("open");
        });

        dropdown.addEventListener("click", (e) => e.stopPropagation());

        dropdown.querySelectorAll(".menubar-dropdown-item").forEach(item => {
            item.addEventListener("click", () => {
                const valueType = item.dataset.valueType;
                addOrFocusWidget(widgetTitle, valueType, item.textContent);
                closeAllTypeDropdowns();
            });
        });
    }

    wireTypeDropdown("add-values-btn", "values-type-wrap", "values-type-dropdown", "Values");
    wireTypeDropdown("add-quality-btn", "quality-type-wrap", "quality-type-dropdown", "Quality");

    document.addEventListener("click", (e) => {
        if (isInsideOpenModal(e.target)) return;
        closeAllTypeDropdowns();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeAllTypeDropdowns();
    });
})();

// ================= Pinboard: infinite pan & zoom camera =================
// The board (#nav-strip) is a fixed-size viewport; #pinboard-canvas is a
// much larger layer, positioned behind it, that holds every widget. This
// IIFE lets the user grab and drag that layer around and zoom it in/out,
// which makes the pinboard feel like an unbounded surface even though the
// widgets themselves still live in the same coordinate space they always
// have. A small round button toggles the mode on/off; a second button,
// which only appears while the mode is active, snaps the camera straight
// back to its starting position and zoom level.
(function () {
    const board = document.getElementById("nav-strip");
    const canvas = document.getElementById("pinboard-canvas");
    const toggleBtn = document.getElementById("pinboard-pan-toggle-btn");
    const recenterBtn = document.getElementById("pinboard-recenter-btn");
    if (!board || !canvas || !toggleBtn || !recenterBtn) return;

    const MIN_SCALE = 0.4;
    const MAX_SCALE = 2.5;

    let panX = 0;
    let panY = 0;
    let scale = 1;
    let panModeActive = false;
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let dragStartPanX = 0;
    let dragStartPanY = 0;

    // ---- Accessible canvas bounds ----
    // The default view on load is only the *initial* viewport, not a
    // permanent boundary. This rectangle (in canvas-local coordinates,
    // the same space widget left/top live in) tracks the full area the
    // camera has ever revealed: it starts as exactly the default view
    // and only ever grows — via growAccessibleBounds(), called on every
    // pan/zoom — as zooming out or panning uncovers more space. It never
    // shrinks back when the user zooms/pans back into the default view,
    // so anything placed outside that original area stays reachable.
    // Widget drag/resize (see wireWidget()) clamps against this instead
    // of the fixed on-screen viewport size via window.getPinboardAccessibleBounds().
    const initialBoardRect = board.getBoundingClientRect();
    const accessibleBounds = {
        left: 0,
        top: 0,
        right: initialBoardRect.width || 0,
        bottom: initialBoardRect.height || 0
    };

    function growAccessibleBounds() {
        const boardRect = board.getBoundingClientRect();
        if (!boardRect.width || !boardRect.height) return;
        // The canvas-local rectangle currently visible through the
        // viewport, given the live pan offset and zoom scale.
        const visLeft = -panX / scale;
        const visTop = -panY / scale;
        const visRight = visLeft + boardRect.width / scale;
        const visBottom = visTop + boardRect.height / scale;
        accessibleBounds.left = Math.min(accessibleBounds.left, visLeft);
        accessibleBounds.top = Math.min(accessibleBounds.top, visTop);
        accessibleBounds.right = Math.max(accessibleBounds.right, visRight);
        accessibleBounds.bottom = Math.max(accessibleBounds.bottom, visBottom);
    }

    // Lets widget drag/resize (defined earlier in this file) read the
    // current accessible bounds without this IIFE needing to run first.
    window.getPinboardAccessibleBounds = () => ({ ...accessibleBounds });

    // A window resize can also grow (or shrink the on-screen footprint
    // of, but never truly shrink) what's currently visible — treat it
    // the same as a pan/zoom for bounds purposes.
    window.addEventListener("resize", growAccessibleBounds);

    // True only once the user has actually grabbed and dragged the board.
    // The math above is correct for zoom-only movement too, but a ring
    // showing a direction after nothing but a scroll still reads as
    // "why is this pointing anywhere, I didn't drag" — so the ring stays
    // hidden until a real drag happens, and goes quiet again on recenter.
    let hasManualPan = false;

    // Continuous (unwrapped) angle driving the recenter button's compass
    // ring, in degrees. Kept unbounded (rather than clamped to -180..180)
    // so the CSS transition always rotates the short way around instead
    // of occasionally spinning a full circle when crossing that boundary.
    let compassAngle = 0;

    function updateCompassAngle() {
        if (!hasManualPan) {
            recenterBtn.classList.add("pinboard-recenter-no-direction");
            return;
        }
        recenterBtn.classList.remove("pinboard-recenter-no-direction");

        // "Home" means the specific piece of canvas content that would be
        // centered in the viewport once reset — the canvas-local point
        // that currently sits at the viewport's own center, back when
        // panX/panY/scale were all at their default values. Point toward
        // wherever THAT content is sitting on screen right now.
        //
        // At scale 1, that reduces to the plain pan offset (panX, panY).
        // But zooming shifts what's centered too — and since the wheel
        // handler anchors zoom on the cursor rather than the viewport
        // center, panX/panY alone stop being enough once scale != 1. The
        // extra (viewport-half)*(scale-1) term corrects for that: it's
        // zero exactly when zoom was centered (nothing to correct for),
        // and grows as the zoom's anchor drifts from center.
        const boardRect = board.getBoundingClientRect();
        const dx = panX + (boardRect.width / 2) * (scale - 1);
        const dy = panY + (boardRect.height / 2) * (scale - 1);
        // Dead-center: no meaningful direction, so just leave the ring
        // wherever it last pointed rather than snapping it somewhere.
        if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;

        const target = Math.atan2(dx, -dy) * (180 / Math.PI); // 0deg = up, clockwise
        let delta = target - (compassAngle % 360);
        while (delta > 180) delta -= 360;
        while (delta < -180) delta += 360;
        compassAngle += delta;
        recenterBtn.style.setProperty("--compass-angle", `${compassAngle}deg`);
    }

    function applyTransform() {
        canvas.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
        updateCompassAngle();
        // Whatever area this move/zoom just brought into view becomes
        // (permanently) part of the accessible canvas.
        growAccessibleBounds();
    }

    // easeOutExpo — matches the CSS linear()/anime.js "outExpo" curve: a
    // fast initial burst that eases into the landing spot instead of
    // stopping abruptly. 1 - 2^(-10t), with t=1 handled explicitly since
    // the formula only approaches (never exactly hits) 1 on its own.
    // Softened a bit (t*0.85 exponent scaling) and given more time to
    // play out — the raw curve reaches ~97% of the distance in the first
    // 200ms, which read as a snap rather than a glide.
    function easeOutExpo(t) {
        return t === 1 ? 1 : 1 - Math.pow(2, -8 * t);
    }

    let resetAnimFrame = null;

    function resetView() {
        // A second click mid-flight should retarget smoothly from wherever
        // the camera currently is, not restart from the old start point.
        if (resetAnimFrame) {
            cancelAnimationFrame(resetAnimFrame);
            resetAnimFrame = null;
        }

        // Heading home — the ring has nothing left to point at until the
        // next real drag.
        hasManualPan = false;

        const startX = panX;
        const startY = panY;
        const startScale = scale;
        const duration = 1100; // ms
        const startTime = performance.now();

        function step(now) {
            const t = Math.min(1, (now - startTime) / duration);
            const eased = easeOutExpo(t);

            panX = startX + (0 - startX) * eased;
            panY = startY + (0 - startY) * eased;
            scale = startScale + (1 - startScale) * eased;
            applyTransform();

            if (t < 1) {
                resetAnimFrame = requestAnimationFrame(step);
            } else {
                resetAnimFrame = null;
            }
        }

        resetAnimFrame = requestAnimationFrame(step);
    }

    function setPanMode(active) {
        panModeActive = active;
        document.body.classList.toggle("pinboard-pan-mode", active);
        toggleBtn.classList.toggle("active", active);
        toggleBtn.setAttribute("aria-pressed", active ? "true" : "false");
        toggleBtn.title = active ? "Exit move & zoom mode" : "Move & zoom board";
        // Turning the mode off no longer snaps the camera back to its
        // starting position/zoom — the whole point of panning around is
        // to land somewhere, so leaving the mode should leave the board
        // exactly where the user put it. Widget dragging/resizing reads
        // the live scale (see window.getPinboardScale below) so it stays
        // pixel-accurate at any zoom level, not just scale === 1. The
        // recenter button (visible only while the mode is active) is
        // still there for anyone who explicitly wants to go back home.
    }

    // Lets other code (widget drag/resize) convert on-screen mouse deltas
    // into canvas-local deltas, since the canvas can now stay zoomed in
    // or out even after the user exits move/zoom mode.
    window.getPinboardScale = () => scale;

    toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        setPanMode(!panModeActive);
    });

    recenterBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        resetView();
        // Getting back to the default view via this button should feel
        // like "I'm done" — drop out of move/zoom mode too instead of
        // leaving the toggle on and requiring a second click.
        if (panModeActive) setPanMode(false);
    });

    // ---- Drag to pan ----
    board.addEventListener("mousedown", (e) => {
        if (!panModeActive) return;
        if (e.target.closest(".pinboard-pan-toggle-btn, .pinboard-recenter-btn")) return;
        e.preventDefault();

        // Grabbing the board mid-recenter-animation should hand control
        // straight back to the user instead of the animation continuing
        // to fight their drag.
        if (resetAnimFrame) {
            cancelAnimationFrame(resetAnimFrame);
            resetAnimFrame = null;
        }

        isDragging = true;
        hasManualPan = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        dragStartPanX = panX;
        dragStartPanY = panY;
        board.classList.add("pinboard-panning");

        function onMove(ev) {
            panX = dragStartPanX + (ev.clientX - dragStartX);
            panY = dragStartPanY + (ev.clientY - dragStartY);
            applyTransform();
        }

        function onUp() {
            isDragging = false;
            board.classList.remove("pinboard-panning");
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
        }

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    });

    // ---- Scroll/wheel to zoom, centered on the cursor ----
    board.addEventListener("wheel", (e) => {
        if (!panModeActive) return;
        e.preventDefault();

        if (resetAnimFrame) {
            cancelAnimationFrame(resetAnimFrame);
            resetAnimFrame = null;
        }

        const boardRect = board.getBoundingClientRect();
        const mouseX = e.clientX - boardRect.left;
        const mouseY = e.clientY - boardRect.top;

        const zoomFactor = Math.exp(-e.deltaY * 0.001);
        const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale * zoomFactor));
        if (newScale === scale) return;

        // Keep whatever point is under the cursor fixed on screen while
        // the scale changes, so zooming feels anchored to the cursor
        // instead of always zooming toward the top-left corner.
        panX = mouseX - ((mouseX - panX) / scale) * newScale;
        panY = mouseY - ((mouseY - panY) / scale) * newScale;
        scale = newScale;
        applyTransform();
    }, { passive: false });

    applyTransform();
})();

// Initial render
updateSortLabel();
renderLevelChrome();
loadSubjects();   // fetches /api/subjects and renders once loaded
renderSessions();
renderRecordings();
