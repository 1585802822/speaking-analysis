"""声纹纠偏闭环测试."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from click.testing import CliRunner

from src.cli import cli
from src.enrollment import EnrollmentManager
from src.reporter import Reporter
from src.types import ProcessingResult, Segment


def _config(tmp_path: Path) -> dict:
    return {
        "voiceprint_dir": str(tmp_path / "voiceprint"),
        "output_dir": str(tmp_path / "output"),
        "speaker": {
            "similarity_threshold": 0.75,
            "low_confidence_threshold": 0.55,
            "positive_lr": 0.25,
            "negative_lr": 0.15,
        },
        "analysis": {"pronunciation": {"low_confidence_threshold": 0.65}},
    }


def test_reporter_writes_corrections_json(tmp_path: Path):
    config = _config(tmp_path)
    reporter = Reporter(config)
    result = ProcessingResult(
        audio_path=str(tmp_path / "test.wav"),
        duration_sec=10.0,
        user_speech_sec=5.0,
        low_confidence_segments=[
            Segment(start=1.0, end=2.0, confidence=0.5),
        ],
    )
    reporter.save(result, "test")

    corrections_path = tmp_path / "output" / "test_corrections.json"
    assert corrections_path.exists()
    data = json.loads(corrections_path.read_text(encoding="utf-8"))
    assert data["audio_path"] == str(tmp_path / "test.wav")
    assert len(data["low_confidence_segments"]) == 1
    assert "suggested_command" in data
    assert "correct" in data["suggested_command"]


def test_update_voiceprint_moves_center(tmp_path: Path):
    config = _config(tmp_path)
    manager = EnrollmentManager(config)

    # 注册初始声纹
    fake_path = tmp_path / "enroll.wav"
    fake_path.write_text("fake audio")
    with patch.object(manager, "_extract_embedding", side_effect=lambda p: _embedding_from_path(p)):
        manager.enroll(str(fake_path))

        center_before = manager.load_voiceprint()["embedding"]
        pos_path = tmp_path / "positive.wav"
        pos_path.write_text("positive")
        neg_path = tmp_path / "negative.wav"
        neg_path.write_text("negative")

        manager.update_voiceprint([str(pos_path)], [str(neg_path)])
        center_after = manager.load_voiceprint()["embedding"]

    #  embedding 应保持单位长度
    import numpy as np

    assert abs(np.linalg.norm(center_after) - 1.0) < 1e-6
    # 由于正/负样本 embedding 不同, 中心应发生变化
    assert not np.allclose(center_before, center_after)

    meta = json.loads((tmp_path / "voiceprint" / "meta.json").read_text(encoding="utf-8"))
    assert len(meta["feedback_history"]) == 1


def _embedding_from_path(path: str) -> "np.ndarray":
    """根据文件内容生成确定性嵌入, 用于测试."""
    import numpy as np

    content = Path(path).read_bytes()
    seed = sum(content) if content else 0
    rng = np.random.default_rng(seed)
    emb = rng.random(192).astype(np.float32)
    return emb / (np.linalg.norm(emb) + 1e-8)


def test_cli_correct_command_parses_segments(tmp_path: Path):
    config = _config(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"voiceprint_dir: {config['voiceprint_dir']}\n"
        f"output_dir: {config['output_dir']}\n"
        "input_dir: ./data/input\n"
        "speaker:\n"
        "  similarity_threshold: 0.75\n"
        "  low_confidence_threshold: 0.55\n"
        "  positive_lr: 0.25\n"
        "  negative_lr: 0.15\n"
        "analysis:\n"
        "  pronunciation:\n"
        "    low_confidence_threshold: 0.65\n"
    )

    audio_path = tmp_path / "audio.wav"
    audio_path.write_text("fake")

    # 先注册, 避免未找到声纹
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=str(tmp_path)):
        result = runner.invoke(cli, ["--config", str(config_path), "register", str(audio_path)])
        assert result.exit_code == 0, result.output

        def _fake_crop(audio_path, start, end, output_path, target_sr=16000):
            Path(output_path).write_bytes(b"cropped" + f"{start},{end}".encode())
            return Path(output_path)

        with patch("src.cli.crop_audio_segment") as mock_crop:
            mock_crop.side_effect = _fake_crop
            with patch.object(
                EnrollmentManager, "_extract_embedding", side_effect=_embedding_from_path
            ):
                result = runner.invoke(
                    cli,
                    [
                        "--config",
                        str(config_path),
                        "correct",
                        str(audio_path),
                        "--confirm",
                        "1.0,2.0",
                        "--deny",
                        "3.0,4.0",
                    ],
                )
    assert result.exit_code == 0, result.output
    assert "声纹已增量更新" in result.output
