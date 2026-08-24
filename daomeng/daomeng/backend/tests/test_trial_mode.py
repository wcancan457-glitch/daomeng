from core.trial_mode import limit_trial_storyboard, merge_trial_opening


def _storyboard(*durations: int) -> dict:
    return {
        "episodes": [{
            "episode_number": 1,
            "segments": [
                {
                    "segment_id": f"source_{index}",
                    "segment_number": index,
                    "total_duration": duration,
                    "shots": [{"shot_number": 1, "duration": duration, "content": f"镜头{index}"}],
                }
                for index, duration in enumerate(durations, 1)
            ],
        }],
    }


def test_trial_storyboard_is_hard_limited_to_fifteen_seconds() -> None:
    limited = limit_trial_storyboard(_storyboard(8, 8, 8), 15)
    segments = limited["episodes"][0]["segments"]
    assert [item["total_duration"] for item in segments] == [8, 7]
    assert [item["segment_id"] for item in segments] == ["seg_01_01", "seg_01_02"]
    assert limited["trial_duration_seconds"] == 15


def test_trial_splits_for_models_with_twelve_second_clip_limit() -> None:
    limited = limit_trial_storyboard(_storyboard(15), 15, max_segment_seconds=12)
    segments = limited["episodes"][0]["segments"]
    assert [item["total_duration"] for item in segments] == [12, 3]
    assert sum(item["total_duration"] for item in segments) == 15


def test_expansion_keeps_trial_segments_and_only_appends_continuation() -> None:
    trial = limit_trial_storyboard(_storyboard(8, 8), 15)
    expanded = merge_trial_opening(_storyboard(10, 10, 10, 10), trial, 15)
    segments = expanded["episodes"][0]["segments"]
    assert [item["segment_id"] for item in segments[:2]] == ["seg_01_01", "seg_01_02"]
    assert len(segments) == 4
    assert expanded["trial_opening_segments"] == 2
