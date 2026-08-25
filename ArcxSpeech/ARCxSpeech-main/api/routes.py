from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import time
import tempfile
import itertools

import numpy as np
import soundfile as sf

from app.feature_extractor import extract_vowel_features, extract_ddk_features, load_audio, compute_spectrogram
from app.recorder import record_audio, prepare_serial, release_prepared, RecordingError, RecordingTimeoutError
from app.preprocessing import remove_dc_offset, apply_frequency_filtering
from app.ambient_analyzer import extract_ambient_metrics
from app.verifier import verify_audio
from app.recording_quality import (
    analyze_recording_quality,
    classify_recording_quality,
    aggregate_recording_quality_metrics,
)
from app import subject_store, session_store, recording_store

router = APIRouter()

# Setup paths
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(APP_ROOT, "recordings")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Local counter so two uploads/recordings finishing in the same
# microsecond can't collide on a filename.
_upload_counter = itertools.count()


def _recording_abspath(rel_path: str) -> str:
    """Recordings are stored as relative paths (e.g. "recordings/x.wav")
    in recordings.json; resolve against APP_ROOT to get a real
    filesystem path."""
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.join(APP_ROOT, rel_path)


def _safe_recording_path(rel_path: str) -> str:
    """Resolves a recording path the CLIENT supplied (as opposed to
    _recording_abspath above, whose input always comes from paths this
    server already wrote into its own JSON files) into a real
    filesystem path, refusing anything that isn't safely inside the
    recordings directory.

    Client-controlled input needs this extra containment check --
    absolute paths, "../" segments, or a symlink inside recordings/
    pointing elsewhere could otherwise be used to read arbitrary files
    off disk. os.path.commonpath (rather than a startswith() string
    check) is what actually catches lookalike-prefix escapes, e.g.
    "recordings_backup/..." not being mistaken for a path inside
    "recordings/"."""
    if not rel_path or os.path.isabs(rel_path):
        raise HTTPException(status_code=400, detail="Invalid recording path.")

    recordings_root = os.path.normpath(UPLOAD_DIR)
    candidate = os.path.normpath(os.path.join(APP_ROOT, rel_path))

    if os.path.commonpath([candidate, recordings_root]) != recordings_root:
        raise HTTPException(status_code=400, detail="Invalid recording path.")

    if not os.path.isfile(candidate):
        raise HTTPException(status_code=404, detail="Recording not found.")

    return candidate


def _delete_unreferenced_recordings(candidate_paths: List[str], surviving_recordings: List[dict]):
    """Deletes each candidate recording file from disk, UNLESS some other
    surviving recording (any session, any subject) still points at that
    same path -- mock/demo data in this project can reuse a couple of
    shared sample WAVs across multiple recordings, so a naive delete
    would break those too."""
    still_referenced = set()
    for r in surviving_recordings:
        if r.get("patient_filepath"):
            still_referenced.add(r["patient_filepath"])
        if r.get("ambient_filepath"):
            still_referenced.add(r["ambient_filepath"])

    for rel_path in candidate_paths:
        if not rel_path or rel_path in still_referenced:
            continue
        try:
            abspath = _recording_abspath(rel_path)
            if os.path.exists(abspath):
                os.remove(abspath)
        except OSError:
            pass


# =====================================
# SUBJECTS
# =====================================

class Subject(BaseModel):
    id: Optional[str] = None
    name: str
    sex: str = ""
    age: str = ""
    group: str = ""


@router.get("/api/subjects")
def get_subjects():
    return subject_store.load_subjects()


@router.post("/api/subjects")
def add_subject(subject: Subject):
    return subject_store.add_subject(
        name=subject.name,
        subject_id=subject.id,
        sex=subject.sex,
        age=subject.age,
        group=subject.group,
    )


@router.delete("/api/subjects/{subject_id}")
def delete_subject(subject_id: str):
    """Deletes a subject entirely: their record, every session they
    have, every recording inside those sessions, and any recording
    files on disk that no other surviving recording still references."""
    subject = subject_store.get_subject(subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found.")

    sessions = session_store.get_sessions_for_subject(subject_id)

    deleted_recordings = []
    for sess in sessions:
        deleted_recordings.extend(
            recording_store.delete_recordings_for_session(sess["session_id"])
        )
        session_store.delete_session(sess["session_id"])

    subject_store.delete_subject(subject_id)

    candidate_paths = []
    for r in deleted_recordings:
        if r.get("patient_filepath"):
            candidate_paths.append(r["patient_filepath"])
        if r.get("ambient_filepath"):
            candidate_paths.append(r["ambient_filepath"])
    _delete_unreferenced_recordings(candidate_paths, recording_store.load_recordings())

    return {"status": "success", "deleted_subject_id": subject_id}


# =====================================
# SESSIONS (empty containers -- recordings are added to them later,
# whenever, via the endpoints below)
# =====================================

class SessionCreate(BaseModel):
    name: Optional[str] = None


@router.post("/api/subjects/{subject_id}/sessions")
def create_session(subject_id: str, session: SessionCreate):
    if not subject_store.get_subject(subject_id):
        raise HTTPException(status_code=404, detail="Subject not found.")
    return session_store.create_session(subject_id, name=session.name)


@router.get("/api/subjects/{subject_id}/sessions")
def get_sessions(subject_id: str):
    if not subject_store.get_subject(subject_id):
        raise HTTPException(status_code=404, detail="Subject not found.")
    return session_store.get_sessions_for_subject(subject_id)


@router.get("/api/subjects/{subject_id}/summary")
def get_subject_summary(subject_id: str):
    """Subject-level counterpart to /api/sessions/{session_id} -- a
    live-computed mean/SD summary built from every recording across
    every one of this subject's sessions. Used when the UI's analysis
    target is a whole subject rather than one session or recording."""
    if not subject_store.get_subject(subject_id):
        raise HTTPException(status_code=404, detail="Subject not found.")

    sessions = session_store.get_sessions_for_subject(subject_id)
    session_ids = [s["session_id"] for s in sessions]
    return recording_store.compute_subject_summary(subject_id, session_ids)


@router.get("/api/sessions/{session_id}")
def get_session_detail(session_id: str):
    """Full session detail: metadata plus a live-computed summary
    (trials/mean/SD per task) built from whatever recordings currently
    belong to this session -- never a stored snapshot, so adding a
    recording later is always reflected here immediately."""
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    summary = recording_store.compute_session_summary(session_id)
    return {**session, **summary}


@router.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """Deletes one session: its row, every recording inside it, and any
    recording files on disk that only that session's recordings
    referenced."""
    if not session_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    deleted_recordings = recording_store.delete_recordings_for_session(session_id)
    session_store.delete_session(session_id)

    candidate_paths = []
    for r in deleted_recordings:
        if r.get("patient_filepath"):
            candidate_paths.append(r["patient_filepath"])
        if r.get("ambient_filepath"):
            candidate_paths.append(r["ambient_filepath"])
    _delete_unreferenced_recordings(candidate_paths, recording_store.load_recordings())

    return {"status": "success"}


# =====================================
# RECORDING PLAYBACK
# =====================================
# Lets the frontend play back a saved recording (e.g. an <audio> tag
# pointed at this URL). `path` is the same relative path already handed
# to the frontend -- patient_filepath/ambient_filepath from a recording
# row -- so no new ID scheme or lookup is needed.
@router.get("/api/recordings/audio")
def get_recording_audio(path: str):
    abspath = _safe_recording_path(path)
    return FileResponse(
        abspath,
        media_type="audio/wav",
        filename=os.path.basename(abspath),
    )


# =====================================
# LIVE RECORDING -- one trial, added to an existing session
# =====================================
# Runs the exact same pipeline the old batched flow used per trial (raw
# capture -> verify -> ambient/quality analysis -> DC-offset removal ->
# frequency filtering -> feature extraction on the preprocessed audio),
# just chained together server-side into a single call, and committed
# to the session immediately instead of being held client-side until a
# whole session's worth of trials was ready.

class LiveRecordingRequest(BaseModel):
    task: str  # "Sustained Vowel" | "DDK"
    duration: float
    # Token from /api/recording/prepare, when the client warmed up the
    # serial connection during the pre-record countdown. Lets
    # record_audio() start reading immediately instead of spending ~2s
    # opening + settling the port after this request lands -- which is
    # what previously made real capture start (and, since a fixed
    # duration's worth of samples is read, end) run late relative to
    # the on-screen countdown/progress bar.
    prepare_token: Optional[str] = None


@router.post("/api/recording/prepare")
def prepare_recording():
    """Opens + settles the serial connection ahead of a timed capture,
    so that settle time can happen during the UI's pre-record
    countdown instead of after the actual recording request lands.
    Call this when the countdown starts, then pass the returned token
    to POST /api/sessions/{id}/recordings."""

    try:
        token = prepare_serial()
    except RecordingError as e:
        raise HTTPException(
            status_code=503,
            detail={"error_type": "hardware_not_connected", "detail": str(e)},
        )

    return {"token": token}


@router.delete("/api/recording/prepare/{token}")
def release_recording_prepare(token: str):
    """Discards a prepared-but-unused connection, e.g. when the user
    cancels the pre-record countdown before it finishes. Best-effort --
    an unknown/already-expired token is a no-op, not an error."""

    release_prepared(token)
    return {"released": True}


def _extract_features(filepath: str, task: str) -> dict:
    if task == "DDK":
        return extract_ddk_features(filepath)
    return extract_vowel_features(filepath)


def _preprocess_and_extract(patient_filepath: str, task: str) -> dict:
    """Same 2-layer preprocessing pipeline as before (DC offset removal,
    then frequency filtering) on a temp WAV, then feature extraction on
    that cleaned copy. Pulled out into its own helper so it can run
    either inline (old behavior) or deferred, batched across a whole
    session's recordings (see /recordings/extract below)."""
    raw_audio, sr = sf.read(patient_filepath, dtype="float32", always_2d=False)
    audio_dc = remove_dc_offset(raw_audio)
    audio_clean = apply_frequency_filtering(audio_dc, sr)

    fd, temp_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    try:
        safe_audio = np.clip(audio_clean, -1.0, 1.0).astype(np.float32)
        sf.write(temp_path, safe_audio, sr, subtype="PCM_16")
        return _extract_features(temp_path, task)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@router.post("/api/sessions/{session_id}/recordings")
def add_live_recording(session_id: str, payload: LiveRecordingRequest):
    if not session_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        patient_filepath, ambient_filepath, _audio = record_audio(
            payload.duration, prefix="clinical", prepare_token=payload.prepare_token
        )
    except RecordingTimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail={"error_type": "recording_timeout", "detail": str(e)},
        )
    except RecordingError as e:
        raise HTTPException(
            status_code=503,
            detail={"error_type": "hardware_not_connected", "detail": str(e)},
        )

    # record_audio() builds these from config.PATIENT_AUDIO_DIR /
    # AMBIENT_AUDIO_DIR, which are now absolute (see config.py). All the
    # processing below (verification, ambient/quality analysis, feature
    # extraction) needs those real absolute paths -- but what gets
    # persisted to recordings.json must stay APP_ROOT-relative, same
    # convention _save_upload() uses below, since _safe_recording_path()
    # (used by the audio-playback endpoint) rejects absolute paths
    # outright as a path-traversal guard. Without this conversion, every
    # live recording's patient_filepath/ambient_filepath would be stored
    # absolute and fail to play back.
    stored_patient_filepath = (
        os.path.relpath(patient_filepath, APP_ROOT)
        if os.path.isabs(patient_filepath) else patient_filepath
    )
    stored_ambient_filepath = (
        os.path.relpath(ambient_filepath, APP_ROOT)
        if os.path.isabs(ambient_filepath) else ambient_filepath
    )

    # Chain-of-custody verification (peak/clipping check + SHA256 hash),
    # logged server-side for the audit trail -- same as the old /api/verify.
    verification = {
        "patient": verify_audio(patient_filepath),
        "ambient": verify_audio(ambient_filepath),
    }

    # Ambient + recording-quality analysis, same as the old
    # /api/analyze_quality -- failures here don't block the trial, they
    # just leave that metric set empty, same as before.
    ambient_metrics = None
    quality_metrics = None
    quality_classification = None

    try:
        ambient_metrics = extract_ambient_metrics(ambient_filepath)
    except Exception as e:
        print(f"Ambient analysis failed for {ambient_filepath}: {e}")

    try:
        quality_metrics = analyze_recording_quality(patient_filepath, ambient_filepath)
    except Exception as e:
        print(f"Quality analysis failed for {patient_filepath}: {e}")

    if quality_metrics:
        try:
            quality_classification = classify_recording_quality(quality_metrics)
        except (KeyError, TypeError):
            quality_classification = None

    # Preprocessing (DC offset removal + frequency filtering) and feature
    # extraction are NOT run here anymore -- the take is logged with
    # features={} the moment it's quality-confirmed, and the frontend's
    # "Extract Features" button (top-right of the recording modal) is
    # what triggers /api/sessions/{id}/recordings/extract to batch-run
    # this pipeline over every pending recording in the session at once.
    recording = recording_store.add_recording(
        session_id=session_id,
        task=payload.task,
        source="live",
        patient_filepath=stored_patient_filepath,
        features={},
        ambient_filepath=stored_ambient_filepath,
        ambient_metrics=ambient_metrics,
        quality_metrics=quality_metrics,
        quality_classification=quality_classification,
    )

    return {**recording, "verification": verification}


# =====================================
# UPLOAD -- any number of files, added to an existing session,
# callable repeatedly
# =====================================
# Deliberately does NOT touch the clinical pipeline (verifier,
# recording_quality, quality_thresholds, ambient_analyzer) -- there's no
# ambient channel or live hardware involved for an uploaded file. Features
# are extracted directly from the uploaded file with plain
# extract_vowel_features/extract_ddk_features -- no DC-offset removal or
# frequency filtering, so uploaded recordings show raw, unprocessed
# biomarkers, same as the old upload path.

def _save_upload(upload: UploadFile, prefix: str) -> str:
    timestamp = int(time.time() * 1_000_000)
    trial_id = next(_upload_counter)
    ext = os.path.splitext(upload.filename or "")[1] or ".wav"
    filename = f"upload_{prefix}_{timestamp}_{trial_id}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(upload.file.read())
    # Stored (and later returned to the client) as a path relative to
    # APP_ROOT -- e.g. "recordings/upload_vowel_...wav" -- matching the
    # convention record_audio() already uses (see app/recorder.py's
    # PATIENT_AUDIO_DIR, which is built from a relative OUTPUT_DIR).
    # UPLOAD_DIR itself is absolute (os.path.join(APP_ROOT, "recordings")),
    # so without this, patient_filepath was saved as a full filesystem
    # path -- which _safe_recording_path() (used by the audio-playback
    # endpoint below) rejects outright, since an absolute path from a
    # client is exactly what that check exists to block.
    return os.path.relpath(filepath, APP_ROOT)


@router.post("/api/sessions/{session_id}/recordings/upload")
def upload_recordings(
    session_id: str,
    task: str = Form(...),
    files: List[UploadFile] = File(...),
):
    if not session_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    if len(files) < 1:
        raise HTTPException(status_code=400, detail="At least 1 .wav file is required.")

    created = []
    try:
        for upload in files:
            prefix = "vowel" if task == "Sustained Vowel" else "ddk"
            rel_filepath = _save_upload(upload, prefix)
            # Extraction reads the file straight off disk, so it needs the
            # real absolute path regardless of the server's cwd -- only
            # what's persisted to recordings.json (rel_filepath) needs to
            # be the APP_ROOT-relative form the playback endpoint expects.
            features = _extract_features(_recording_abspath(rel_filepath), task)
            created.append(
                recording_store.add_recording(
                    session_id=session_id,
                    task=task,
                    source="uploaded",
                    patient_filepath=rel_filepath,
                    features=features,
                )
            )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Feature extraction failed: {e}")

    return created


@router.post("/api/sessions/{session_id}/recordings/extract")
def extract_session_features(session_id: str):
    """Batch-runs preprocessing + feature extraction over every recording
    in the session that's still pending it (features == {}) -- i.e. every
    take logged via the live-recording flow since add_live_recording no
    longer extracts inline. Triggered by the "Extract Features" button at
    the top-right of the recording modal. A recording failing extraction
    doesn't block the rest; it's reported back in `errors` and stays
    pending so a re-run can retry it."""

    if not session_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    pending = [
        r for r in recording_store.get_recordings_for_session(session_id)
        if not r.get("features")
    ]

    updated = []
    errors = []

    for r in pending:
        try:
            abs_patient_path = _recording_abspath(r["patient_filepath"])
            features = _preprocess_and_extract(abs_patient_path, r["task"])
            updated_row = recording_store.update_recording_features(r["recording_id"], features)
            if updated_row:
                updated.append(updated_row)
        except Exception as e:
            errors.append({"recording_id": r["recording_id"], "error": str(e)})

    return {"updated": updated, "errors": errors}


@router.get("/api/sessions/{session_id}/recordings")
def get_recordings(session_id: str):
    if not session_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return recording_store.get_recordings_for_session(session_id)


# =====================================
# SPECTROGRAM (real STFT, not the frontend's scalar-feature stand-in)
# =====================================
# The Spectrogram graph widget (UI/js/project.js) used to synthesize a
# fake-but-plausible harmonic image from F0/F1/F2/HNR alone -- never a
# real STFT of the waveform. compute_spectrogram() in
# app/feature_extractor.py already did the real work but was never
# wired to an endpoint. This exposes it per-recording: load that
# recording's patient audio (same 16kHz-resampled signal every other
# feature is measured from, so it lines up with F0/formant readouts),
# run the STFT, and return the freq/time/magnitude grid as JSON for
# the frontend to paint directly instead of synthesizing.
#
# Trimmed to 0-4kHz (same range the widget already displays) and
# rounded before serializing -- an untrimmed 16kHz STFT is ~513 freq
# bins, most of which are above where vowel/formant energy lives and
# would roughly double the payload for no visual benefit at this
# widget's size.
SPECTROGRAM_MAX_FREQ_HZ = 4000


@router.get("/api/sessions/{session_id}/recordings/{recording_id}/spectrogram")
def get_recording_spectrogram(session_id: str, recording_id: str):
    recording = recording_store.get_recording(recording_id)
    if not recording or recording.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="Recording not found.")

    patient_filepath = recording.get("patient_filepath")
    if not patient_filepath:
        raise HTTPException(status_code=404, detail="No audio on this recording.")

    abspath = _recording_abspath(patient_filepath)
    if not os.path.isfile(abspath):
        raise HTTPException(status_code=404, detail="Audio file missing on disk.")

    patient_audio, _ambient_audio, sr, _duration, _sound = load_audio(abspath)
    freqs, times, magnitude_db = compute_spectrogram(patient_audio, sr)

    freq_mask = freqs <= SPECTROGRAM_MAX_FREQ_HZ
    freqs = freqs[freq_mask]
    magnitude_db = magnitude_db[freq_mask, :]

    return {
        "freqs": [round(float(f), 1) for f in freqs],
        "times": [round(float(t), 3) for t in times],
        # [freq_bins][time_bins], low frequency first -- matches freqs
        # order above; the frontend flips it when painting (low
        # frequency at the bottom of the image).
        # Whole dB, not one decimal -- a color-mapped heatmap doesn't
        # need sub-dB precision, and this is the bulk of the payload
        # (up to ~150k values for a longer DDK clip), so trimming it
        # to integers noticeably shrinks the response.
        "magnitude_db": [[round(float(v)) for v in row] for row in magnitude_db],
    }


@router.delete("/api/sessions/{session_id}/recordings/{recording_id}")
def delete_recording(session_id: str, recording_id: str):
    deleted = recording_store.delete_recording(recording_id)
    if not deleted or deleted.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="Recording not found.")

    candidate_paths = []
    if deleted.get("patient_filepath"):
        candidate_paths.append(deleted["patient_filepath"])
    if deleted.get("ambient_filepath"):
        candidate_paths.append(deleted["ambient_filepath"])
    _delete_unreferenced_recordings(candidate_paths, recording_store.load_recordings())

    return {"status": "success"}
