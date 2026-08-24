"""
Speech Motor


Pipeline:
- Stage 1: Non-linear normalization (ascending/descending/dual-bounded
  sigmoids, Gaussian windows) turns each raw metric into a 0-100 score.
- Stage 2: Per-domain scores are a weighted average of their component
  scores.
- Stage 3: Each domain also gets a confidence figure (recording
  quality x trial consistency) and a short list of plain-language
  evidence explaining the score.

Every metric passes through a bounded transfer function, so any finite
input produces a score in [0, 100] -- no raw value can blow up the output.
"""

import numpy as np
from typing import Dict, Any, Optional, List, Tuple
import math


# ---------------------------------------------------------------------
# Constants and safety settings
# ---------------------------------------------------------------------

EPSILON = 1e-7
SAFE_EXP_MIN = -500.0
SAFE_EXP_MAX = 500.0

# Target F0 by sex. Only Male/Female are modeled -- if a patient's
# sex isn't recorded as one of these two, the F0 proximity component
# is skipped rather than scored against a guessed target (see
# _evaluate_phonatory_control).
F0_TARGETS = {
    "Male": {"target": 120.0, "tolerance": 25.0},
    "Female": {"target": 210.0, "tolerance": 35.0},
}

# Recording-quality rating -> confidence multiplier
RECORDING_QUALITY_FACTORS = {
    "100%": 1.00,
    "85%": 0.85,
    "70%": 0.70,
    "50%": 0.50,
    "25%": 0.25,
}

# How much each raw metric counts toward its domain's score
DOMAIN_WEIGHTS = {
    "stability": {
        "Jitter Local": 0.40,
        "HNR": 0.35,
        "pitch_variability": 0.25,
    },
    "timing": {
        "DDK Regularity": 0.45,
        "Pause/Speech Ratio": 0.35,
        "DDK Interval Std": 0.20,
    },
    "coordination": {
        "DDK Repetition Rate": 0.50,
        "Speech Rate": 0.30,
        "DDK Interval Mean": 0.20,
    },
    "phonatory_control": {
        "HNR": 0.40,
        "F0 proximity": 0.30,
        "formant_ratio": 0.30,
    },
}

# Curve shape + reference point used to normalize each raw metric into
# a 0-100 score. "x0"/"k" drive the sigmoids; "mu"/"sigma" drive the
# Gaussian windows. These are engineering defaults, not clinically
# validated cutoffs -- see module docstring.
NORMALIZATION_PARAMS = {
    "stability": {
        "Jitter Local": {"x0": 1.2, "k": 2.5, "type": "descending"},
        "HNR": {"x0": 15.0, "k": 0.35, "type": "ascending"},
        "pitch_variability": {"x0": 3.0, "k": 1.0, "type": "descending"},
    },
    "timing": {
        "DDK Regularity": {"x0": 15.0, "k": 0.25, "type": "descending"},
        "Pause/Speech Ratio": {"x0": 0.35, "k": 8.0, "type": "descending"},
        "DDK Interval Std": {"x0": 0.04, "k": 70.0, "type": "descending"},
    },
    "coordination": {
        "DDK Repetition Rate": {
            "lower": 4.0, "upper": 7.5,
            "lower_cutoff": 3.0, "upper_cutoff": 2.5,
            "type": "dual"
        },
        "Speech Rate": {
            "lower": 3.0, "upper": 6.5,
            "lower_cutoff": 2.5, "upper_cutoff": 2.0,
            "type": "dual"
        },
        "DDK Interval Mean": {"mu": 0.17, "sigma": 0.05, "type": "window"},
    },
    "phonatory_control": {
        "HNR": {"x0": 15.0, "k": 0.35, "type": "ascending"},
        "F0 proximity": {"type": "f0_window"},
        "formant_ratio": {"mu": 1.5, "sigma": 0.35, "type": "window"},
    },
}


# ---------------------------------------------------------------------
# Stage 1: normalize raw metrics into 0-100 scores
# ---------------------------------------------------------------------


def _is_finite(value: Any) -> bool:
    """True if value converts to a finite float (guards every metric before use)."""
    try:
        val = float(value)
        return np.isfinite(val)
    except (TypeError, ValueError):
        return False


def _clamp_exponential_input(x: float) -> float:
    """Keeps sigmoid exponents inside a range np.exp() can't overflow on."""
    return float(np.clip(x, SAFE_EXP_MIN, SAFE_EXP_MAX))


def _clamp_score(score: float) -> float:
    """Final safety net -- every returned score is forced into [0, 100]."""
    return float(np.clip(score, 0.0, 100.0))


def _sigmoid_ascending(x: float, x0: float, k: float) -> float:
    """Higher x = higher score. Used for metrics like HNR."""
    if not _is_finite(x) or not _is_finite(x0) or not _is_finite(k):
        return 0.0

    exponent = _clamp_exponential_input(-k * (x - x0))
    score = 100.0 / (1.0 + np.exp(exponent))
    return _clamp_score(score)


def _sigmoid_descending(x: float, x0: float, k: float) -> float:
    """Lower x = higher score. Used for jitter, pause ratio, DDK regularity."""
    if not _is_finite(x) or not _is_finite(x0) or not _is_finite(k):
        return 0.0

    exponent = _clamp_exponential_input(k * (x - x0))
    score = 100.0 / (1.0 + np.exp(exponent))
    return _clamp_score(score)


def _score_window(x: float, mu: float, sigma: float) -> float:
    """Gaussian window: score peaks at mu and falls off on both sides."""
    if not _is_finite(x) or not _is_finite(mu) or not _is_finite(sigma):
        return 0.0

    sigma_safe = max(sigma, EPSILON)
    exponent = _clamp_exponential_input(-0.5 * ((x - mu) / sigma_safe) ** 2)
    score = 100.0 * np.exp(exponent)
    return _clamp_score(score)


def _score_dual_sigmoid(
    x: float,
    lower: float,
    upper: float,
    lower_cutoff: float,
    upper_cutoff: float
) -> float:
    """
    Flat 100 between lower/upper, sigmoid falloff outside that band on
    both sides. Used for rate metrics where being too slow or too fast
    is equally undesirable.
    """
    if not all(_is_finite(v) for v in [x, lower, upper, lower_cutoff, upper_cutoff]):
        return 0.0

    if x < lower:
        score = _sigmoid_ascending(x, lower, lower_cutoff)
    elif x <= upper:
        score = 100.0
    else:
        score = _sigmoid_descending(x, upper, upper_cutoff)

    return _clamp_score(score)


def _normalize_metric(
    value: float,
    params: Dict[str, Any],
    f0_target: Optional[float] = None,
    f0_tolerance: Optional[float] = None,
) -> Optional[float]:
    """Routes a raw value to the right transfer function based on params["type"]."""
    if not _is_finite(value):
        return None

    norm_type = params.get("type")

    if norm_type == "ascending":
        return _sigmoid_ascending(value, params["x0"], params["k"])
    elif norm_type == "descending":
        return _sigmoid_descending(value, params["x0"], params["k"])
    elif norm_type == "window":
        return _score_window(value, params["mu"], params["sigma"])
    elif norm_type == "dual":
        return _score_dual_sigmoid(
            value, params["lower"], params["upper"],
            params["lower_cutoff"], params["upper_cutoff"]
        )
    elif norm_type == "f0_window":
        if f0_target is None or f0_tolerance is None:
            return None
        return _score_window(value, f0_target, f0_tolerance)
    else:
        return None


# ---------------------------------------------------------------------
# Stage 2: combine normalized metrics into domain scores
# ---------------------------------------------------------------------


def _safe_get(dictionary: Dict, key: str, default: Any = None) -> Any:
    """dict.get with a shorter name, used everywhere below for readability."""
    return dictionary.get(key, default)


def _compute_pitch_variability(
    vowel_mean: Dict[str, Any],
    vowel_sd: Dict[str, Any],
) -> Optional[float]:
    """F0 coefficient of variation, as a percentage."""
    f0_mean = _safe_get(vowel_mean, "F0 Mean", 0.0)
    f0_sd = _safe_get(vowel_sd, "F0 Mean", 0.0)

    if not _is_finite(f0_mean) or not _is_finite(f0_sd) or f0_mean <= 0:
        return None

    return (f0_sd / f0_mean) * 100.0


def _compute_formant_ratio(
    vowel_mean: Dict[str, Any],
) -> Optional[float]:
    """F2/F1 ratio. Values below 100 Hz on either formant are treated as noise, not signal."""
    f1 = _safe_get(vowel_mean, "F1 Mean", 0.0)
    f2 = _safe_get(vowel_mean, "F2 Mean", 0.0)

    if not _is_finite(f1) or not _is_finite(f2) or f1 <= 100.0 or f2 <= 100.0:
        return None

    return f2 / f1


def _synthesize_domain_score(
    component_scores: Dict[str, float],
    weights: Dict[str, float],
) -> Tuple[Optional[float], Dict[str, float]]:
    """
    Weighted average over whatever components actually have a score.
    Missing components drop out and the remaining weights simply
    re-normalize against each other (Domain = sum(w*s) / sum(w)).
    """
    available_components = {}

    for component, score in component_scores.items():
        if score is not None and _is_finite(score):
            weight = _safe_get(weights, component, 0.0)
            if weight > 0:
                available_components[component] = {
                    "score": score,
                    "weight": weight,
                }

    if not available_components:
        return None, {}

    total_weight = sum(comp["weight"] for comp in available_components.values())

    if total_weight < EPSILON:
        return None, {}

    weighted_sum = sum(
        comp["score"] * comp["weight"]
        for comp in available_components.values()
    )

    domain_score = weighted_sum / total_weight

    return _clamp_score(domain_score), available_components


# ---------------------------------------------------------------------
# Stage 3: confidence scoring + plain-language evidence
# ---------------------------------------------------------------------


def _compute_trial_consistency(
    mean_dict: Dict[str, Any],
    sd_dict: Dict[str, Any],
    metric_keys: List[str],
) -> float:
    """
    Averages each metric's coefficient of variation across trials and
    converts that into a 0.5-1.0 multiplier -- noisy trials pull
    confidence down, but never below half credit.
    """
    coefficients_of_variation = []

    for key in metric_keys:
        m_val = _safe_get(mean_dict, key, 0.0)
        sd_val = _safe_get(sd_dict, key, 0.0)

        if _is_finite(m_val) and _is_finite(sd_val) and m_val != 0:
            cv = abs(sd_val / m_val)
            coefficients_of_variation.append(min(1.0, cv))

    if not coefficients_of_variation:
        return 1.0

    mean_cov = float(np.mean(coefficients_of_variation))
    trial_factor = max(0.50, 1.0 - (0.50 * mean_cov))

    return trial_factor


def _compute_confidence(
    rq_classification: Dict[str, Any],
    mean_dict: Dict[str, Any],
    sd_dict: Dict[str, Any],
    metric_keys: List[str],
) -> float:
    """Confidence = recording-quality factor x trial-consistency factor, as a 0-100 score."""
    rq_rating = _safe_get(rq_classification, "Recording Quality Rating", "★★★☆☆")
    rq_factor = RECORDING_QUALITY_FACTORS.get(rq_rating, 0.70)

    trial_factor = _compute_trial_consistency(mean_dict, sd_dict, metric_keys)

    confidence = 100.0 * rq_factor * trial_factor

    return _clamp_score(round(confidence, 1))


def _generate_evidence(
    component_scores: Dict[str, Any],
    raw_metrics: Dict[str, Any],
    missing_components: List[str],
    has_clipping: bool,
    domain: str,
) -> Dict[str, List[str]]:
    """
    Turns component scores into short, human-readable notes: what's
    holding up well (>=85), what's dragging the score down (<60), and
    anything the clinician should know went missing or got flagged.
    """
    evidence = {
        "strengths": [],
        "impairment_drivers": [],
        "warnings": [],
    }

    for component, data in component_scores.items():
        score = data.get("score", 0.0)
        raw_value = raw_metrics.get(component)

        if score >= 85:
            if raw_value is not None and _is_finite(raw_value):
                evidence["strengths"].append(f"Preserved {component.lower()} (raw: {raw_value:.2f})")
            else:
                evidence["strengths"].append(f"Preserved {component.lower()}")
        elif score < 60:
            if raw_value is not None and _is_finite(raw_value):
                evidence["impairment_drivers"].append(f"Elevated {component.lower()} (raw: {raw_value:.2f})")
            else:
                evidence["impairment_drivers"].append(f"Elevated {component.lower()}")

    for component in missing_components:
        evidence["warnings"].append(f"Missing {component.lower()}")

    if has_clipping and domain == "stability":
        evidence["warnings"].append(
            "Stability score affected by digital microphone clipping; "
            "physiological tremor is not confirmed."
        )

    return evidence


# ---------------------------------------------------------------------
# Domain evaluators -- one function per motor-speech domain
# ---------------------------------------------------------------------


def _evaluate_stability(
    vowel_mean: Dict[str, Any],
    vowel_sd: Dict[str, Any],
    rq_classification: Dict[str, Any],
) -> Dict[str, Any]:
    """Stability = voice steadiness, from jitter, HNR, and pitch variability."""
    f0_mean = _safe_get(vowel_mean, "F0 Mean", 0.0)

    if not _is_finite(f0_mean) or f0_mean <= 0.0:
        return {
            "status": "Non-Evaluable",
            "score": 0.0,
            "confidence": 0.0,
            "components": {},
            "evidence": {
                "strengths": [],
                "impairment_drivers": [],
                "warnings": ["No sustained phonation or voicing detected."],
            },
        }

    jitter = _safe_get(vowel_mean, "Jitter Local")
    hnr = _safe_get(vowel_mean, "HNR")
    pitch_var = _compute_pitch_variability(vowel_mean, vowel_sd)

    params = NORMALIZATION_PARAMS["stability"]

    s_jitter = _normalize_metric(jitter, params["Jitter Local"]) if jitter is not None else None
    s_hnr = _normalize_metric(hnr, params["HNR"]) if hnr is not None else None
    s_pitch = _normalize_metric(pitch_var, params["pitch_variability"]) if pitch_var is not None else None

    component_scores = {
        "Jitter Local": s_jitter,
        "HNR": s_hnr,
        "pitch_variability": s_pitch,
    }

    weights = DOMAIN_WEIGHTS["stability"]
    domain_score, weighted_components = _synthesize_domain_score(component_scores, weights)

    metric_keys = ["Jitter Local", "HNR", "F0 Mean"]
    confidence = _compute_confidence(rq_classification, vowel_mean, vowel_sd, metric_keys)

    missing = [k for k, v in component_scores.items() if v is None]

    raw_metrics = {
        "Jitter Local": jitter,
        "HNR": hnr,
        "pitch_variability": pitch_var,
    }

    has_clipping = _safe_get(rq_classification, "Clipping Detected", False)
    evidence = _generate_evidence(weighted_components, raw_metrics, missing, has_clipping, "stability")

    if domain_score is None:
        status = "Non-Evaluable"
        domain_score = 0.0
    elif len(missing) > 0:
        status = "Evaluated (Partial)"
    else:
        status = "Evaluated"

    return {
        "status": status,
        "score": round(domain_score, 1),
        "confidence": confidence,
        "components": {k: round(v["score"], 1) for k, v in weighted_components.items()},
        "evidence": evidence,
    }


def _evaluate_timing(
    ddk_mean: Dict[str, Any],
    ddk_sd: Dict[str, Any],
    rq_classification: Dict[str, Any],
) -> Dict[str, Any]:
    """Timing = pacing consistency, from DDK regularity, pause ratio, and interval std."""
    ddk_count = _safe_get(ddk_mean, "DDK Repetition Count", 0)

    if not _is_finite(ddk_count) or ddk_count < 2:
        return {
            "status": "Non-Evaluable",
            "score": 0.0,
            "confidence": 0.0,
            "components": {},
            "evidence": {
                "strengths": [],
                "impairment_drivers": [],
                "warnings": ["Insufficient valid repetitions to evaluate pacing."],
            },
        }

    ddk_regularity = _safe_get(ddk_mean, "DDK Regularity")
    pause_ratio = _safe_get(ddk_mean, "Pause/Speech Ratio")
    interval_std = _safe_get(ddk_mean, "DDK Interval Std")

    params = NORMALIZATION_PARAMS["timing"]

    s_regularity = _normalize_metric(ddk_regularity, params["DDK Regularity"]) if ddk_regularity is not None else None
    s_pause = _normalize_metric(pause_ratio, params["Pause/Speech Ratio"]) if pause_ratio is not None else None
    s_istd = _normalize_metric(interval_std, params["DDK Interval Std"]) if interval_std is not None else None

    component_scores = {
        "DDK Regularity": s_regularity,
        "Pause/Speech Ratio": s_pause,
        "DDK Interval Std": s_istd,
    }

    weights = DOMAIN_WEIGHTS["timing"]
    domain_score, weighted_components = _synthesize_domain_score(component_scores, weights)

    metric_keys = ["DDK Regularity", "Pause/Speech Ratio", "DDK Interval Std"]
    confidence = _compute_confidence(rq_classification, ddk_mean, ddk_sd, metric_keys)

    missing = [k for k, v in component_scores.items() if v is None]

    raw_metrics = {
        "DDK Regularity": ddk_regularity,
        "Pause/Speech Ratio": pause_ratio,
        "DDK Interval Std": interval_std,
    }

    evidence = _generate_evidence(weighted_components, raw_metrics, missing, False, "timing")

    if domain_score is None:
        status = "Non-Evaluable"
        domain_score = 0.0
    elif len(missing) > 0:
        status = "Evaluated (Partial)"
    else:
        status = "Evaluated"

    return {
        "status": status,
        "score": round(domain_score, 1),
        "confidence": confidence,
        "components": {k: round(v["score"], 1) for k, v in weighted_components.items()},
        "evidence": evidence,
    }


def _evaluate_coordination(
    ddk_mean: Dict[str, Any],
    ddk_sd: Dict[str, Any],
    rq_classification: Dict[str, Any],
) -> Dict[str, Any]:
    """Coordination = movement speed/control, from repetition rate, speech rate, interval mean."""
    ddk_count = _safe_get(ddk_mean, "DDK Repetition Count", 0)

    if not _is_finite(ddk_count) or ddk_count < 2:
        return {
            "status": "Non-Evaluable",
            "score": 0.0,
            "confidence": 0.0,
            "components": {},
            "evidence": {
                "strengths": [],
                "impairment_drivers": [],
                "warnings": ["Insufficient valid repetitions to evaluate pacing."],
            },
        }

    rep_rate = _safe_get(ddk_mean, "DDK Repetition Rate")
    speech_rate = _safe_get(ddk_mean, "Speech Rate")
    interval_mean = _safe_get(ddk_mean, "DDK Interval Mean")

    params = NORMALIZATION_PARAMS["coordination"]

    s_rep_rate = _normalize_metric(rep_rate, params["DDK Repetition Rate"]) if rep_rate is not None else None
    s_speech_rate = _normalize_metric(speech_rate, params["Speech Rate"]) if speech_rate is not None else None
    s_imean = _normalize_metric(interval_mean, params["DDK Interval Mean"]) if interval_mean is not None else None

    component_scores = {
        "DDK Repetition Rate": s_rep_rate,
        "Speech Rate": s_speech_rate,
        "DDK Interval Mean": s_imean,
    }

    weights = DOMAIN_WEIGHTS["coordination"]
    domain_score, weighted_components = _synthesize_domain_score(component_scores, weights)

    metric_keys = ["DDK Repetition Rate", "Speech Rate", "DDK Interval Mean"]
    confidence = _compute_confidence(rq_classification, ddk_mean, ddk_sd, metric_keys)

    missing = [k for k, v in component_scores.items() if v is None]

    raw_metrics = {
        "DDK Repetition Rate": rep_rate,
        "Speech Rate": speech_rate,
        "DDK Interval Mean": interval_mean,
    }

    evidence = _generate_evidence(weighted_components, raw_metrics, missing, False, "coordination")

    if domain_score is None:
        status = "Non-Evaluable"
        domain_score = 0.0
    elif len(missing) > 0:
        status = "Evaluated (Partial)"
    else:
        status = "Evaluated"

    return {
        "status": status,
        "score": round(domain_score, 1),
        "confidence": confidence,
        "components": {k: round(v["score"], 1) for k, v in weighted_components.items()},
        "evidence": evidence,
    }


def _evaluate_phonatory_control(
    vowel_mean: Dict[str, Any],
    vowel_sd: Dict[str, Any],
    sex: str,
    rq_classification: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Phonatory Control = voice quality relative to expected pitch, from
    HNR, F0 proximity to the sex-appropriate target, and formant ratio.

    F0 proximity is only scored when sex is exactly "Male" or "Female"
    (see F0_TARGETS) -- with anything else, that one component is
    skipped rather than scored against a guessed target, and the
    domain score re-normalizes over HNR + formant_ratio instead.
    """
    f0_mean = _safe_get(vowel_mean, "F0 Mean", 0.0)

    if not _is_finite(f0_mean) or f0_mean <= 0.0:
        return {
            "status": "Non-Evaluable",
            "score": 0.0,
            "confidence": 0.0,
            "components": {},
            "evidence": {
                "strengths": [],
                "impairment_drivers": [],
                "warnings": ["No sustained phonation or voicing detected."],
            },
        }

    hnr = _safe_get(vowel_mean, "HNR")
    formant_ratio = _compute_formant_ratio(vowel_mean)

    f0_params = F0_TARGETS.get(sex)

    params = NORMALIZATION_PARAMS["phonatory_control"]

    s_hnr = _normalize_metric(hnr, params["HNR"]) if hnr is not None else None

    if f0_params is not None:
        s_f0 = _normalize_metric(
            f0_mean, params["F0 proximity"], f0_params["target"], f0_params["tolerance"]
        )
    else:
        s_f0 = None

    s_formant = _normalize_metric(formant_ratio, params["formant_ratio"]) if formant_ratio is not None else None

    component_scores = {
        "HNR": s_hnr,
        "F0 proximity": s_f0,
        "formant_ratio": s_formant,
    }

    weights = DOMAIN_WEIGHTS["phonatory_control"]
    domain_score, weighted_components = _synthesize_domain_score(component_scores, weights)

    metric_keys = ["HNR", "F0 Mean"]
    confidence = _compute_confidence(rq_classification, vowel_mean, vowel_sd, metric_keys)

    missing = [k for k, v in component_scores.items() if v is None]

    raw_metrics = {
        "HNR": hnr,
        "F0 proximity": f0_mean,
        "formant_ratio": formant_ratio,
    }

    evidence = _generate_evidence(weighted_components, raw_metrics, missing, False, "phonatory_control")

    if f0_params is None:
        evidence["warnings"].append(
            "F0 proximity not evaluated: sex must be recorded as Male or Female."
        )

    if domain_score is None:
        status = "Non-Evaluable"
        domain_score = 0.0
    elif len(missing) > 0:
        status = "Evaluated (Partial)"
    else:
        status = "Evaluated"

    return {
        "status": status,
        "score": round(domain_score, 1),
        "confidence": confidence,
        "components": {k: round(v["score"], 1) for k, v in weighted_components.items()},
        "evidence": evidence,
    }


# ---------------------------------------------------------------------
# Main entry point -- the only function the rest of the app should call
# ---------------------------------------------------------------------


def compute_speech_motor_state(
    vowel_mean: Optional[Dict[str, Any]] = None,
    ddk_mean: Optional[Dict[str, Any]] = None,
    vowel_sd: Optional[Dict[str, Any]] = None,
    ddk_sd: Optional[Dict[str, Any]] = None,
    sex: str = "Male",
    rq_classification: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Computes all four domain scores plus a composite index from one
    session's acoustic measurements. vowel_mean/ddk_mean come straight
    from assessment_store; sex should be "Male" or "Female" -- anything
    else just skips the F0 proximity component (see
    _evaluate_phonatory_control).
    """
    vowel_mean = vowel_mean or {}
    ddk_mean = ddk_mean or {}
    vowel_sd = vowel_sd or {}
    ddk_sd = ddk_sd or {}
    rq_classification = rq_classification or {}

    ddk_empty = not bool(ddk_mean)
    vowel_empty = not bool(vowel_mean)

    stability_result = _evaluate_stability(vowel_mean, vowel_sd, rq_classification) if not vowel_empty else None
    timing_result = _evaluate_timing(ddk_mean, ddk_sd, rq_classification) if not ddk_empty else None
    coordination_result = _evaluate_coordination(ddk_mean, ddk_sd, rq_classification) if not ddk_empty else None
    phonatory_result = _evaluate_phonatory_control(vowel_mean, vowel_sd, sex, rq_classification) if not vowel_empty else None

    if ddk_empty:
        timing_result = {
            "status": "Not Performed",
            "score": None,
            "confidence": None,
            "components": {},
            "evidence": {
                "strengths": [],
                "impairment_drivers": [],
                "warnings": ["DDK task not performed."],
            },
        }
        coordination_result = {
            "status": "Not Performed",
            "score": None,
            "confidence": None,
            "components": {},
            "evidence": {
                "strengths": [],
                "impairment_drivers": [],
                "warnings": ["DDK task not performed."],
            },
        }

    valid_scores = []
    for result in [stability_result, timing_result, coordination_result, phonatory_result]:
        if result is not None and result.get("score") is not None:
            valid_scores.append(result["score"])

    composite_index = None
    if valid_scores:
        composite_index = round(float(np.mean(valid_scores)), 1)

    return {
        "stability": stability_result,
        "timing": timing_result,
        "coordination": coordination_result,
        "phonatory_control": phonatory_result,
        "composite_index": composite_index,
    }


# ---------------------------------------------------------------------
# Self-checks -- run these after touching any normalization constant
# ---------------------------------------------------------------------


def verify_monotonicity_jitter() -> bool:
    """Increasing jitter should never increase the Stability score."""
    previous_score = 100.0

    for jitter in np.linspace(0.1, 8.0, 100):
        mock_vowel = {
            "F0 Mean": 120.0,
            "Jitter Local": jitter,
            "HNR": 20.0,
        }

        state = compute_speech_motor_state(
            vowel_mean=mock_vowel,
            ddk_mean={},
            sex="Male",
            rq_classification={"Recording Quality Rating": "★★★★★"}
        )

        current_score = state["stability"]["score"]

        if current_score > previous_score + EPSILON:
            return False

        previous_score = current_score

    return True


def verify_monotonicity_hnr() -> bool:
    """Increasing HNR should never decrease the Phonatory Control score."""
    previous_score = 0.0

    for hnr in np.linspace(-10, 35, 100):
        mock_vowel = {
            "F0 Mean": 120.0,
            "Jitter Local": 0.5,
            "HNR": hnr,
            "F1 Mean": 750.0,
            "F2 Mean": 1100.0,
        }

        state = compute_speech_motor_state(
            vowel_mean=mock_vowel,
            ddk_mean={},
            sex="Male",
            rq_classification={"Recording Quality Rating": "★★★★★"}
        )

        current_score = state["phonatory_control"]["score"]

        if current_score < previous_score - EPSILON:
            return False

        previous_score = current_score

    return True


def verify_bounds() -> bool:
    """No combination of extreme/garbage input should push a score outside [0, 100]."""
    test_values = [-1000, -100, -10, 0, 10, 100, 1000, 1e6, -1e6]

    for jitter in test_values:
        for hnr in test_values:
            mock_vowel = {
                "F0 Mean": 120.0,
                "Jitter Local": jitter,
                "HNR": hnr,
            }

            state = compute_speech_motor_state(
                vowel_mean=mock_vowel,
                ddk_mean={},
                sex="Male",
                rq_classification={}
            )

            stability = state["stability"]["score"]
            phonatory = state["phonatory_control"]["score"]

            if not (0.0 <= stability <= 100.0):
                return False
            if not (0.0 <= phonatory <= 100.0):
                return False

    return True


def run_verification_suite() -> Dict[str, bool]:
    """Runs all self-checks above. All True = safe to deploy this version's constants."""
    return {
        "jitter_monotonicity": verify_monotonicity_jitter(),
        "hnr_monotonicity": verify_monotonicity_hnr(),
        "score_bounds": verify_bounds(),
    }