"""Helpers for the low-cost 15-second trial workflow."""

from __future__ import annotations

import copy
from typing import Any, Dict, List

TRIAL_DURATION_SECONDS = 15
# Two reference frames / video calls are enough for a 15-second proof-of-concept,
# including providers whose single-clip maximum is below 15 seconds.
TRIAL_MAX_SEGMENTS = 2


def _duration(segment: Dict[str, Any]) -> int:
    shots = segment.get("shots") or []
    return max(1, int(segment.get("total_duration") or sum(int(s.get("duration") or 0) for s in shots) or 5))


def _trim_segment(segment: Dict[str, Any], seconds: int) -> Dict[str, Any]:
    """Return a copy of a segment whose shot durations add up to ``seconds``."""
    result = copy.deepcopy(segment)
    remaining = max(1, int(seconds))
    trimmed_shots: List[Dict[str, Any]] = []
    for shot in result.get("shots") or []:
        if remaining <= 0:
            break
        next_shot = copy.deepcopy(shot)
        shot_duration = max(1, int(next_shot.get("duration") or 2))
        next_shot["duration"] = min(shot_duration, remaining)
        trimmed_shots.append(next_shot)
        remaining -= next_shot["duration"]

    if not trimmed_shots:
        trimmed_shots = [{
            "shot_number": 1,
            "shot_type": "中景",
            "duration": seconds,
            "content": result.get("visual_prompt") or result.get("plot") or "试片开场镜头",
        }]
    elif remaining > 0:
        trimmed_shots[-1]["duration"] += remaining

    for index, shot in enumerate(trimmed_shots, 1):
        shot["shot_number"] = index
    result["shots"] = trimmed_shots
    result["total_duration"] = seconds
    return result


def limit_trial_storyboard(
    payload: Dict[str, Any],
    duration_seconds: int = TRIAL_DURATION_SECONDS,
    max_segment_seconds: int = TRIAL_DURATION_SECONDS,
) -> Dict[str, Any]:
    """Keep only the material required for the first trial clip."""
    result = copy.deepcopy(payload)
    episodes = result.get("episodes") or []
    if not episodes:
        return result

    source_segments = episodes[0].get("segments") or []
    kept: List[Dict[str, Any]] = []
    remaining = max(1, int(duration_seconds))
    max_segment_seconds = max(2, int(max_segment_seconds))
    for segment in source_segments:
        if remaining <= 0 or len(kept) >= TRIAL_MAX_SEGMENTS:
            break
        source_remaining = _duration(segment)
        while source_remaining > 0 and remaining > 0 and len(kept) < TRIAL_MAX_SEGMENTS:
            seconds = min(source_remaining, remaining, max_segment_seconds)
            part = _trim_segment(segment, seconds)
            if kept and source_remaining < _duration(segment):
                part["continuation_of"] = segment.get("segment_id")
                if part.get("shots"):
                    part["shots"][0]["content"] = f"延续上一片段动作。{part['shots'][0].get('content', '')}"
            kept.append(part)
            remaining -= seconds
            source_remaining -= seconds

    for index, segment in enumerate(kept, 1):
        segment["episode_number"] = 1
        segment["segment_number"] = index
        segment["segment_id"] = f"seg_01_{index:02d}"

    first_episode = copy.deepcopy(episodes[0])
    first_episode["episode_number"] = 1
    first_episode["episode_title"] = first_episode.get("episode_title") or "轻量试片"
    first_episode["segments"] = kept
    result["episodes"] = [first_episode]
    result["trial_duration_seconds"] = sum(_duration(item) for item in kept)
    result["creation_mode"] = "trial"
    return result


def merge_trial_opening(full_payload: Dict[str, Any], trial_payload: Dict[str, Any], duration_seconds: int = TRIAL_DURATION_SECONDS) -> Dict[str, Any]:
    """Replace the regenerated opening with the approved trial segments."""
    result = copy.deepcopy(full_payload)
    full_episodes = result.get("episodes") or []
    trial_episodes = (trial_payload or {}).get("episodes") or []
    if not full_episodes or not trial_episodes:
        return result

    trial_segments = copy.deepcopy(trial_episodes[0].get("segments") or [])
    duration_seconds = int(
        (trial_payload or {}).get("trial_duration_seconds")
        or sum(_duration(item) for item in trial_segments)
        or duration_seconds
    )
    full_segments = copy.deepcopy(full_episodes[0].get("segments") or [])
    consumed = 0
    continuation: List[Dict[str, Any]] = []
    for segment in full_segments:
        if consumed < duration_seconds:
            consumed += _duration(segment)
            continue
        continuation.append(segment)

    merged = trial_segments + continuation
    for index, segment in enumerate(merged, 1):
        segment["episode_number"] = 1
        segment["segment_number"] = index
        if index > len(trial_segments):
            segment["segment_id"] = f"seg_01_{index:02d}"

    first_episode = copy.deepcopy(full_episodes[0])
    first_episode["episode_number"] = 1
    first_episode["segments"] = merged
    result["episodes"] = [first_episode]
    result["creation_mode"] = "expanded"
    result["trial_opening_segments"] = len(trial_segments)
    return result
