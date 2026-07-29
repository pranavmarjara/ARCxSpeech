from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import List, Optional
import json
import os
import time
import uuid
import tempfile
import itertools
from datetime import datetime

import numpy as np
import soundfile as sf

from app.feature_extractor import extract_vowel_features, extract_ddk_features
from app.recorder import record_audio, RecordingError, RecordingTimeoutError
from app.preprocessing import remove_dc_offset, apply_frequency_filtering
from app.ambient_analyzer import extract_ambient_metrics
from app.verifier import verify_audio
from app.recording_quality import (
    analyze_recording_quality,
    classify_recording_quality,
    aggregate_recording_quality_metrics,
)
from app import assessment_store

router = APIRouter()

# Setup paths
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATIENTS_FILE = os.path.join(APP_ROOT, "patients.json")
UPLOAD_DIR = os.path.join(APP_ROOT, "recordings")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Local counter so two uploads finishing in the same microsecond can't
# collide on a filename (mirrors app/recorder.py's trial_id pattern).
_upload_counter = itertools.count()

# Patient Model
class Patient(BaseModel):
    id: Optional[str] = None
    name: str
    sex: str
    age: str
    disease: str
    createdAt: Optional[str] = None

def _read_json(filepath, default=[]):
    if not os.path.exists(filepath):
        return default
    with open(filepath, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default

def _write_json(filepath, data):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

@router.get("/api/patients")
def get_patients():
    return _read_json(PATIENTS_FILE)

@router.post("/api/patients")
def add_patient(patient: Patient):
    patients = _read_json(PATIENTS_FILE)
    
    # Generate ID if not provided
    if not patient.id:
        import random
        taken = {p.get("id") for p in patients}
        while True:
            new_id = f"RD-{random.randint(10000, 99999)}"
            if new_id not in taken:
                patient.id = new_id
                break
                
    patient.createdAt = datetime.now().isoformat()
    
    new_patient = patient.dict()
    patients.append(new_patient)
    _write_json(PATIENTS_FILE, patients)
    
    return new_patient


ASSESSMENTS_FILE = os.path.join(APP_ROOT, "clinical_assessments.json")


@router.delete("/api/patients/{patient_id}")
def delete_patient(patient_id: str):
    """Deletes a patient entirely: their record, every recording session
    (both the "ui_tasks" stub and the full assessment) they have on file,
    and any recording files on disk that no other patient's session still
    references."""
    patients = _read_json(PATIENTS_FILE)
    if not any(p.get("id") == patient_id for p in patients):
        raise HTTPException(status_code=404, detail="Patient not found.")

    remaining_patients = [p for p in patients if p.get("id") != patient_id]
    _write_json(PATIENTS_FILE, remaining_patients)

    assessments = _read_json(ASSESSMENTS_FILE)
    patient_entries = [a for a in assessments if a.get("patient_id") == patient_id]
    remaining_assessments = [a for a in assessments if a.get("patient_id") != patient_id]
    _write_json(ASSESSMENTS_FILE, remaining_assessments)

    recording_paths = []
    for entry in patient_entries:
        recording_paths.extend(entry.get("vowel_recordings") or [])
        recording_paths.extend(entry.get("ddk_recordings") or [])
    _delete_unreferenced_recordings(recording_paths, remaining_assessments)

    return {"status": "success", "deleted_patient_id": patient_id}

class SessionTask(BaseModel):
    name: str
    duration: str
    status: str

class Session(BaseModel):
    date: str
    tasks: List[SessionTask]
    # Optional so older callers (and the live-recording flow, which
    # generates its own id client-side to share with /api/assessments)
    # keep working either way.
    session_id: Optional[str] = None
    source: Optional[str] = "live"


def _session_source(entry: dict) -> str:
    """Best-effort source label for a stub entry. Newer entries carry an
    explicit "source"; older ones (saved before this field existed) are
    inferred from task status, since uploaded tasks are tagged
    "Uploaded" and live ones "Recorded"/"Processed"/"Skipped"."""
    if entry.get("source"):
        return entry["source"]
    tasks = entry.get("ui_tasks") or []
    if tasks and all(t.get("status") == "Uploaded" for t in tasks):
        return "uploaded"
    return "live"


@router.get("/api/sessions/{patient_id}")
def get_sessions(patient_id: str):
    assessments = _read_json(ASSESSMENTS_FILE)
    # clinical_assessments.json holds two different shapes of record in the
    # same array: lightweight session stubs (written here, tagged with
    # "ui_tasks") and full assessments (written by /api/assessments, with
    # vowel_trials/ddk_trials/etc, no "ui_tasks"). data.js expects the
    # sessions list and the assessments list to line up 1:1 by index for a
    # given patient, so only the stub entries belong here -- a full
    # assessment record showing up in this list too would double-count
    # every saved session and desync that index alignment.
    patient_sessions = [
        a for a in assessments
        if a.get("patient_id") == patient_id and "ui_tasks" in a
    ]

    formatted_sessions = [
        {
            "date": p.get("timestamp", "").split(" ")[0],
            "tasks": p["ui_tasks"],
            # Falls back to a positional id for legacy stubs saved before
            # session_id existed, so every session is still deletable.
            "session_id": p.get("session_id") or f"legacy-{i}",
            "source": _session_source(p),
        }
        for i, p in enumerate(patient_sessions)
    ]

    return formatted_sessions

@router.post("/api/sessions/{patient_id}")
def save_session(patient_id: str, session: Session):
    assessments = _read_json(ASSESSMENTS_FILE)
    
    assessment = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "patient_id": patient_id,
        "session_id": session.session_id or str(uuid.uuid4()),
        "source": session.source or "live",
        "ui_tasks": [t.dict() for t in session.tasks]
    }
    
    assessments.append(assessment)
    _write_json(ASSESSMENTS_FILE, assessments)
    return {"status": "success"}


def _recording_abspath(rel_path: str) -> str:
    """Recordings are stored as relative paths (e.g. "recordings/x.wav")
    in clinical_assessments.json; resolve against APP_ROOT to get a real
    filesystem path."""
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.join(APP_ROOT, rel_path)


def _delete_unreferenced_recordings(candidate_paths: List[str], surviving_assessments: List[dict]):
    """Deletes each candidate recording file from disk, UNLESS some other
    surviving assessment (any patient) still references that same path --
    mock/demo data in this project reuses a couple of shared sample WAVs
    across multiple patients, so a naive delete would break their sessions
    too."""
    still_referenced = set()
    for a in surviving_assessments:
        still_referenced.update(a.get("vowel_recordings") or [])
        still_referenced.update(a.get("ddk_recordings") or [])

    for rel_path in candidate_paths:
        if not rel_path or rel_path in still_referenced:
            continue
        try:
            abspath = _recording_abspath(rel_path)
            if os.path.exists(abspath):
                os.remove(abspath)
        except OSError:
            pass


@router.delete("/api/sessions/{patient_id}/{session_id}")
def delete_session(patient_id: str, session_id: str):
    """Deletes one recording session for a patient: both the lightweight
    "ui_tasks" stub (shown in the Home page list) and its paired full
    assessment record (the feature data behind the Data page), plus any
    recording files on disk that only that session referenced."""
    assessments = _read_json(ASSESSMENTS_FILE)

    stub_positions = [
        (i, a) for i, a in enumerate(assessments)
        if a.get("patient_id") == patient_id and "ui_tasks" in a
    ]

    target_stub_idx = None
    for logical_idx, (_, a) in enumerate(stub_positions):
        effective_id = a.get("session_id") or f"legacy-{logical_idx}"
        if effective_id == session_id:
            target_stub_idx = logical_idx
            break

    if target_stub_idx is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Full assessment records (the ones carrying actual feature data) for
    # this patient, in the same relative order as the stubs above -- see
    # get_sessions' comment on why these line up 1:1 by position.
    full_positions = [
        (i, a) for i, a in enumerate(assessments)
        if a.get("patient_id") == patient_id and "ui_tasks" not in a
    ]

    positions_to_remove = [stub_positions[target_stub_idx][0]]
    recording_paths = []
    if target_stub_idx < len(full_positions):
        full_pos, full_entry = full_positions[target_stub_idx]
        positions_to_remove.append(full_pos)
        recording_paths.extend(full_entry.get("vowel_recordings") or [])
        recording_paths.extend(full_entry.get("ddk_recordings") or [])

    remaining = [a for i, a in enumerate(assessments) if i not in positions_to_remove]
    _write_json(ASSESSMENTS_FILE, remaining)
    _delete_unreferenced_recordings(recording_paths, remaining)

    return {"status": "success"}


# =====================================
# CLINICAL ASSESSMENTS (full feature data behind the Data page)
# =====================================
# These were referenced by UI/js/home.js and UI/js/data.js but were
# missing from this file, so nothing recorded live could ever actually
# show up on the Data page. Added here to close that gap, in addition
# to the new upload-based (R&D) path below.

class Assessment(BaseModel):
    patient_name: str
    patient_id: str
    age: str
    sex: str
    vowel_trials: List[dict] = []
    ddk_trials: List[dict] = []
    vowel_mean: dict = {}
    ddk_mean: dict = {}
    ambient_mean: dict = {}
    vowel_recordings: List[str] = []
    ddk_recordings: List[str] = []
    vowel_sd: dict = {}
    ddk_sd: dict = {}
    ambient_sd: dict = {}
    recording_quality_mean: dict = {}
    recording_quality_sd: dict = {}
    recording_quality_classification: dict = {}
    # Shared with the paired "ui_tasks" stub (see Session model above) so
    # the two halves of one session can be deleted together.
    session_id: Optional[str] = None
    source: Optional[str] = "live"


# =====================================
# LIVE RECORDING (real ARC hardware)
# =====================================
# Mirrors the clinical pipeline from the reference desktop app
# (app/assessment_ui.py, AssessmentWindow.process_assessment /
# _preprocess_to_temp) -- MINUS ambient analysis and the Recording
# Quality Engine/gate, which are intentionally deferred to a later task.
# Every trial: raw capture (record_audio) -> DC-offset removal ->
# frequency filtering -> feature extraction on the preprocessed audio.
# This is the opposite of the upload path above, which deliberately
# skips preprocessing.

class RecordRequest(BaseModel):
    duration: float
    prefix: str = "clinical"


class ExtractRequest(BaseModel):
    patient_filepath: str
    task: str


class QualityAggregateRequest(BaseModel):
    quality_metrics: List[dict] = []
    ambient_metrics: List[dict] = []


class VerifyRequest(BaseModel):
    patient_filepath: str
    ambient_filepath: str


@router.post("/api/verify")
def verify_trial(payload: VerifyRequest):
    """
    Chain-of-custody verification: computes peak/clipping check and
    SHA256 hash for a raw trial file. Logged server-side for audit trail.
    Called before analysis on every raw trial file, matching the reference
    implementation's behavior.
    """
    if not os.path.exists(payload.patient_filepath) or not os.path.exists(payload.ambient_filepath):
        raise HTTPException(
            status_code=404,
            detail={
                "error_type": "file_not_found",
                "detail": f"Recording file not found: {payload.patient_filepath}",
            },
        )

    return {
        "patient": verify_audio(payload.patient_filepath),
        "ambient": verify_audio(payload.ambient_filepath),
    }


class QualityOnlyRequest(BaseModel):
    patient_filepath: str
    ambient_filepath: str


@router.post("/api/analyze_quality")
def analyze_quality_only(payload: QualityOnlyRequest):
    """
    Analyzes ambient and recording quality metrics ONLY (no feature
    extraction). This endpoint is called in batch across all raw trial
    files before the quality gate, matching the reference implementation's
    execution order: ambient + quality → gate → feature extraction (only
    if gate passes).
    """
    if not os.path.exists(payload.patient_filepath) or not os.path.exists(payload.ambient_filepath):
        raise HTTPException(
            status_code=404,
            detail={
                "error_type": "recording_failed",
                "detail": f"Recording file not found: {payload.patient_filepath}",
            },
        )

    ambient = None
    quality = None

    try:
        ambient = extract_ambient_metrics(payload.ambient_filepath)
    except Exception as e:
        print(f"Ambient analysis failed for {payload.ambient_filepath}: {e}")
        ambient = None

    try:
        quality = analyze_recording_quality(payload.patient_filepath, payload.ambient_filepath)
    except Exception as e:
        print(f"Quality analysis failed for {payload.patient_filepath}: {e}")
        quality = None

    return {
        "ambient": ambient,
        "quality": quality,
    }


class QualityAggregateRequest(BaseModel):
    quality_metrics: List[dict] = []
    ambient_metrics: List[dict] = []


@router.post("/api/record")
def record_trial(payload: RecordRequest):
    try:
        patient_filepath, ambient_filepath, _audio = record_audio(payload.duration, prefix=payload.prefix)
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

    return {"patient_filepath": patient_filepath, "ambient_filepath": ambient_filepath}


@router.post("/api/extract")
def extract_trial(payload: ExtractRequest):
    if not os.path.exists(payload.patient_filepath):
        raise HTTPException(
            status_code=404,
            detail={
                "error_type": "recording_failed",
                "detail": f"Recording file not found: {payload.patient_filepath}",
            },
        )

    # Same 2-layer pipeline as the reference desktop app's
    # _preprocess_to_temp(): DC offset removal, then frequency filtering,
    # written to a temp WAV so extraction runs on the cleaned audio
    # instead of the raw capture.
    raw_audio, sr = sf.read(payload.patient_filepath, dtype="float32", always_2d=False)
    audio_dc = remove_dc_offset(raw_audio)
    audio_clean = apply_frequency_filtering(audio_dc, sr)

    fd, temp_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    try:
        safe_audio = np.clip(audio_clean, -1.0, 1.0).astype(np.float32)
        sf.write(temp_path, safe_audio, sr, subtype="PCM_16")

        if payload.task == "DDK":
            features = extract_ddk_features(temp_path)
        else:
            features = extract_vowel_features(temp_path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    # Ambient + Recording Quality analysis now happen separately via
    # /api/analyze_quality (called before extraction, in batch, across
    # all raw trial files) so the quality gate can run before feature
    # extraction starts. This matches the reference implementation's
    # execution order.

    return {
        "features": features,
    }


@router.post("/api/quality/aggregate")
def aggregate_quality(payload: QualityAggregateRequest):
    """
    Aggregates the per-trial ambient/quality metrics collected across a
    session's recordings into session-level mean/SD, and classifies the
    aggregated quality metrics into a star rating. Thin wrapper around
    app/recording_quality.py's existing aggregation + classification --
    kept server-side so the classification thresholds live in one place
    instead of being duplicated in the UI.
    """

    quality_mean, quality_sd = aggregate_recording_quality_metrics(
        payload.quality_metrics
    )
    ambient_mean, ambient_sd = aggregate_recording_quality_metrics(
        payload.ambient_metrics
    )

    classification = {}
    if quality_mean:
        try:
            classification = classify_recording_quality(quality_mean)
        except (KeyError, TypeError):
            classification = {}

    return {
        "ambient_mean": ambient_mean,
        "ambient_sd": ambient_sd,
        "recording_quality_mean": quality_mean,
        "recording_quality_sd": quality_sd,
        "recording_quality_classification": classification,
    }


@router.post("/api/assessments")
def save_assessment(assessment: Assessment):
    assessment_store.save_assessment(
        patient_name=assessment.patient_name,
        patient_id=assessment.patient_id,
        age=assessment.age,
        sex=assessment.sex,
        vowel_trials=assessment.vowel_trials,
        ddk_trials=assessment.ddk_trials,
        vowel_mean=assessment.vowel_mean,
        ddk_mean=assessment.ddk_mean,
        ambient_mean=assessment.ambient_mean,
        vowel_recordings=assessment.vowel_recordings,
        ddk_recordings=assessment.ddk_recordings,
        vowel_sd=assessment.vowel_sd,
        ddk_sd=assessment.ddk_sd,
        ambient_sd=assessment.ambient_sd,
        recording_quality_mean=assessment.recording_quality_mean,
        recording_quality_sd=assessment.recording_quality_sd,
        recording_quality_classification=assessment.recording_quality_classification,
        session_id=assessment.session_id,
        source=assessment.source,
    )
    return {"status": "success"}


@router.get("/api/assessments/{patient_id}")
def get_assessments(patient_id: str):
    assessments = assessment_store.load_assessments()
    return [a for a in assessments if a.get("patient_id") == patient_id]


# =====================================
# R&D UPLOAD-BASED SESSION
# =====================================
# Lets a session be built from uploaded WAV files instead of a live
# hardware recording. Deliberately does NOT touch the clinical
# pipeline (app/verifier.py, app/recording_quality.py,
# app/quality_thresholds.py, app/ambient_analyzer.py) -- there's no
# ambient channel or live hardware involved for an uploaded file, so
# that scoring/gating logic doesn't apply. Features are extracted
# directly from the uploaded file with app/feature_extractor's plain
# extract_vowel_features / extract_ddk_features -- no DC-offset removal
# or frequency filtering is applied first, so the Data page shows raw,
# unprocessed biomarkers for uploaded sessions.
#
# Results are saved through the same assessment_store used by the live
# flow (so this shows up on the Data page next to normal sessions,
# exactly like the request asked), just computed from the raw upload
# instead of via the clinical pipeline.

def _save_upload(upload: UploadFile, prefix: str) -> str:
    timestamp = int(time.time() * 1_000_000)
    trial_id = next(_upload_counter)
    ext = os.path.splitext(upload.filename or "")[1] or ".wav"
    filename = f"upload_{prefix}_{timestamp}_{trial_id}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(upload.file.read())
    return filepath


def _extract_raw_features(filepath: str, task_label: str) -> dict:
    """Extracts biomarkers straight from the uploaded file, with no
    preprocessing layers applied -- raw audio in, raw metrics out."""
    if task_label == "Sustained Vowel":
        return extract_vowel_features(filepath)
    elif task_label == "DDK":
        return extract_ddk_features(filepath)
    else:
        raise ValueError(f"Unknown task: {task_label}")


def _compute_mean(feature_dicts: List[dict]) -> dict:
    if not feature_dicts:
        return {}
    result = {}
    for key in feature_dicts[0].keys():
        values = [d[key] for d in feature_dicts if isinstance(d.get(key), (int, float))]
        if values:
            result[key] = round(sum(values) / len(values), 3)
    return result


def _compute_sd(feature_dicts: List[dict]) -> dict:
    if len(feature_dicts) < 2:
        return {}
    result = {}
    for key in feature_dicts[0].keys():
        values = [d[key] for d in feature_dicts if isinstance(d.get(key), (int, float))]
        if len(values) > 1:
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            result[key] = round(variance ** 0.5, 3)
    return result


@router.post("/api/sessions/{patient_id}/upload")
def create_session_from_upload(
    patient_id: str,
    vowel_files: List[UploadFile] = File(...),
    ddk_files: List[UploadFile] = File(...),
):
    if len(vowel_files) < 1:
        raise HTTPException(status_code=400, detail="At least 1 Sustained Vowel .wav file is required.")
    if len(ddk_files) < 1:
        raise HTTPException(status_code=400, detail="At least 1 DDK .wav file is required.")

    patients = _read_json(PATIENTS_FILE)
    patient = next((p for p in patients if p.get("id") == patient_id), None)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")

    try:
        vowel_recordings, vowel_trials = [], []
        for upload in vowel_files:
            filepath = _save_upload(upload, "vowel")
            vowel_recordings.append(filepath)
            vowel_trials.append(_extract_raw_features(filepath, "Sustained Vowel"))

        ddk_recordings, ddk_trials = [], []
        for upload in ddk_files:
            filepath = _save_upload(upload, "ddk")
            ddk_recordings.append(filepath)
            ddk_trials.append(_extract_raw_features(filepath, "DDK"))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Feature extraction failed: {e}")

    vowel_mean = _compute_mean(vowel_trials)
    vowel_sd = _compute_sd(vowel_trials)
    ddk_mean = _compute_mean(ddk_trials)
    ddk_sd = _compute_sd(ddk_trials)

    # Shared by both halves of this session (the full assessment saved
    # here, and the "ui_tasks" stub saved just below) so they can later
    # be deleted together as one unit.
    session_id = str(uuid.uuid4())

    # Ambient/recording-quality fields are intentionally left empty --
    # that's the clinical pipeline, which doesn't apply to uploaded files.
    assessment_store.save_assessment(
        patient_name=patient.get("name", ""),
        patient_id=patient_id,
        age=patient.get("age", ""),
        sex=patient.get("sex", ""),
        vowel_trials=vowel_trials,
        ddk_trials=ddk_trials,
        vowel_mean=vowel_mean,
        ddk_mean=ddk_mean,
        ambient_mean={},
        vowel_recordings=vowel_recordings,
        ddk_recordings=ddk_recordings,
        vowel_sd=vowel_sd,
        ddk_sd=ddk_sd,
        ambient_sd={},
        session_id=session_id,
        source="uploaded",
    )

    # Lightweight session stub for the Home page list, same as a live
    # recording produces -- tasks are tagged "Uploaded" so they read
    # distinctly from live-recorded ("Recorded"/"Processed") sessions.
    today = datetime.now().strftime("%b %d, %Y")
    tasks = (
        [{"name": "Sustained Vowel", "duration": "--", "status": "Uploaded"}] * len(vowel_files)
        + [{"name": "DDK Task", "duration": "--", "status": "Uploaded"}] * len(ddk_files)
    )

    assessments = _read_json(ASSESSMENTS_FILE)
    assessments.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "patient_id": patient_id,
        "session_id": session_id,
        "source": "uploaded",
        "ui_tasks": tasks,
    })
    _write_json(ASSESSMENTS_FILE, assessments)

    return {"status": "success", "date": today, "tasks": tasks}
