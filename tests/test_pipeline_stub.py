"""流水线端到端桩测试."""

from pathlib import Path

import numpy as np

from src.pipeline import Pipeline


def _create_silent_wav(path: Path, duration_sec: float = 1.0, sr: int = 16000) -> None:
    """生成一个静音 WAV 文件用于测试."""
    import soundfile as sf

    y = np.zeros(int(duration_sec * sr), dtype=np.float32)
    sf.write(str(path), y, sr)


def test_pipeline_runs(tmp_path):
    config = {
        "input_dir": str(tmp_path / "input"),
        "output_dir": str(tmp_path / "output"),
        "voiceprint_dir": str(tmp_path / "voiceprint"),
        "audio_formats": [".wav"],
        "segmentation": {
            "target_sample_rate": 16000,
            "max_segment_duration_sec": 300,
            "min_segment_duration_sec": 0.1,
        },
        "vad": {"min_speech_duration_ms": 100, "max_silence_duration_ms": 500},
        "speaker": {
            "similarity_threshold": 0.75,
            "low_confidence_threshold": 0.55,
        },
        "analysis": {
            "filler_words": {"zh": ["然后"], "en": []},
            "max_sentence_words": 10,
            "min_pause_sec": 0.3,
            "max_pause_sec": 2.0,
            "pronunciation": {"low_confidence_threshold": 0.65},
        },
        "asr": {"model": "tiny", "language": "zh"},
    }
    # 创建输入目录和注册声纹
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    wav = input_dir / "test.wav"
    _create_silent_wav(wav)

    from src.enrollment import EnrollmentManager

    EnrollmentManager(config).enroll(str(wav))

    pipeline = Pipeline(config)
    result = pipeline.process(str(wav))

    assert result.audio_path == str(wav)
    output_files = list((tmp_path / "output").glob("*"))
    assert len(output_files) == 3  # md + json + corrections
    assert any("_corrections.json" in str(p) for p in output_files)
