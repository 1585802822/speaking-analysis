"""数据库访问层测试."""

from __future__ import annotations

import pytest

from src.db import Database
from src.types import Segment, SegmentTranscription, Word


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def test_save_and_get_recording(db):
    db.save_recording("rec1", "/path/to/rec1.wav", 120.5, 16000, "segmented")
    row = db.get_recording("rec1")
    assert row is not None
    assert row["original_path"] == "/path/to/rec1.wav"
    assert row["duration_sec"] == 120.5
    assert row["status"] == "segmented"


def test_update_recording_status(db):
    db.save_recording("rec1", "/path/to/rec1.wav", 120.5)
    db.update_recording_status("rec1", "transcribed")
    row = db.get_recording("rec1")
    assert row["status"] == "transcribed"


def test_save_and_get_segments(db):
    db.save_recording("rec1", "/path/to/rec1.wav", 10.0)
    segments = [
        Segment(start=0.0, end=2.0, segment_index=0, recording_id="rec1"),
        Segment(start=2.5, end=4.5, segment_index=1, recording_id="rec1"),
    ]
    audio_paths = ["/path/to/0000.wav", "/path/to/0001.wav"]
    db.save_segments("rec1", segments, audio_paths)

    rows = db.get_segments("rec1")
    assert len(rows) == 2
    assert rows[0]["segment_index"] == 0
    assert rows[1]["segment_index"] == 1


def test_save_and_get_diarization(db):
    db.save_recording("rec1", "/path/to/rec1.wav", 10.0)
    segments = [
        Segment(start=0.0, end=2.0, segment_index=0, recording_id="rec1"),
        Segment(start=2.5, end=4.5, segment_index=1, recording_id="rec1"),
    ]
    db.save_segments("rec1", segments, ["/a.wav", "/b.wav"])

    segments[0].speaker_label = "user"
    segments[0].speaker_confidence = 0.85
    segments[0].is_user = True
    segments[1].speaker_label = "other"
    segments[1].speaker_confidence = 0.45
    segments[1].is_user = False
    db.save_diarization("rec1", segments)

    rows = db.get_diarization("rec1")
    assert len(rows) == 2
    assert rows[0]["speaker_label"] == "user"
    assert rows[1]["speaker_label"] == "other"


def test_get_segments_by_speaker(db):
    db.save_recording("rec1", "/path/to/rec1.wav", 10.0)
    segments = [
        Segment(start=0.0, end=2.0, segment_index=0, recording_id="rec1"),
        Segment(start=2.5, end=4.5, segment_index=1, recording_id="rec1"),
    ]
    db.save_segments("rec1", segments, ["/a.wav", "/b.wav"])
    segments[0].speaker_label = "user"
    segments[0].is_user = True
    segments[1].speaker_label = "other"
    segments[1].is_user = False
    db.save_diarization("rec1", segments)

    user_rows = db.get_segments_by_speaker("rec1", "user")
    assert len(user_rows) == 1
    assert user_rows[0]["segment_index"] == 0


def test_save_and_get_asr_results(db):
    db.save_recording("rec1", "/path/to/rec1.wav", 10.0)
    segments = [Segment(start=0.0, end=2.0, segment_index=0, recording_id="rec1")]
    db.save_segments("rec1", segments, ["/a.wav"])

    transcription = SegmentTranscription(
        recording_id="rec1",
        segment_index=0,
        speaker_label="user",
        asr_source="api",
        audio_path="/a.wav",
        start=0.0,
        end=2.0,
        text="你好世界",
        words=[Word(text="你好", start=0.0, end=1.0), Word(text="世界", start=1.0, end=2.0)],
    )
    db.save_asr_results("rec1", [transcription])

    rows = db.get_asr_results("rec1")
    assert len(rows) == 1
    assert rows[0]["text"] == "你好世界"
    assert rows[0]["asr_source"] == "api"


def test_apply_speaker_correction(db):
    db.save_recording("rec1", "/path/to/rec1.wav", 10.0)
    segments = [Segment(start=0.0, end=2.0, segment_index=0, recording_id="rec1")]
    db.save_segments("rec1", segments, ["/a.wav"])
    segments[0].speaker_label = "other"
    db.save_diarization("rec1", segments)

    success = db.apply_speaker_correction("rec1", 0, "user")
    assert success is True

    diarization = db.get_diarization("rec1")
    assert diarization[0]["speaker_label"] == "user"

    history = db.get_correction_history("rec1")
    assert len(history) == 1
    assert history[0]["old_label"] == "other"
    assert history[0]["new_label"] == "user"


def test_get_transcription_view(db):
    db.save_recording("rec1", "/path/to/rec1.wav", 10.0)
    segments = [Segment(start=0.0, end=2.0, segment_index=0, recording_id="rec1")]
    db.save_segments("rec1", segments, ["/a.wav"])
    segments[0].speaker_label = "user"
    db.save_diarization("rec1", segments)

    transcription = SegmentTranscription(
        recording_id="rec1",
        segment_index=0,
        speaker_label="user",
        asr_source="api",
        audio_path="/a.wav",
        start=0.0,
        end=2.0,
        text="你好",
        words=[Word(text="你好", start=0.0, end=2.0)],
    )
    db.save_asr_results("rec1", [transcription])

    view = db.get_transcription_view("rec1")
    assert len(view) == 1
    assert view[0]["text"] == "你好"
    assert view[0]["speaker_label"] == "user"
    assert view[0]["words"][0]["text"] == "你好"
