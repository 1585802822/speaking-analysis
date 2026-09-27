"""Web UI API 单元测试."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config import load_config
from src.db import Database
from src.types import Segment
from src.web.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    """创建使用临时数据库的 TestClient."""
    config = load_config()
    config["db_path"] = str(tmp_path / "test.db")
    config["segments_dir"] = str(tmp_path / "segments")
    config["voiceprint_dir"] = str(tmp_path / "voiceprint")
    config["output_dir"] = str(tmp_path / "output")
    app = create_app(config)
    return TestClient(app)


def test_index(client: TestClient) -> None:
    """首页返回入口 HTML."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Web UI Demo" in response.text


def test_static_files(client: TestClient) -> None:
    """静态资源可访问."""
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/prototype/vue/index.html").status_code == 200


def test_list_recordings_empty(client: TestClient) -> None:
    """空数据库返回空列表."""
    response = client.get("/api/recordings")
    assert response.status_code == 200
    assert response.json()["recordings"] == []


def test_scan_directory(client: TestClient, tmp_path: Path) -> None:
    """扫描目录只返回支持的音频格式."""
    (tmp_path / "a.wav").write_text("dummy")
    (tmp_path / "b.txt").write_text("text")
    (tmp_path / "c.mp3").write_text("dummy")
    response = client.post("/api/scan", json={"path": str(tmp_path)})
    assert response.status_code == 200
    files = response.json()["files"]
    assert len(files) == 2
    assert {f["name"] for f in files} == {"a.wav", "c.mp3"}


def test_scan_directory_missing(client: TestClient) -> None:
    """扫描不存在目录返回 400."""
    response = client.post("/api/scan", json={"path": "C:/not-exists-12345"})
    assert response.status_code == 400


def test_update_speaker_and_text(client: TestClient, tmp_path: Path) -> None:
    """说话人标签和 ASR 文本更新后持久化."""
    config = client.app.state.config
    db = Database(config["db_path"])
    db.save_recording("r1", "/tmp/a.wav", 10.0, 16000, "transcribed")
    seg = Segment(start=0.0, end=1.0, segment_index=0, recording_id="r1")
    seg.speaker_label = "other"
    db.save_segments("r1", [seg], [str(tmp_path / "0000.wav")])
    db.save_diarization("r1", [seg])
    db.update_asr_text("r1", 0, "hello")

    assert (
        client.put(
            "/api/recordings/r1/segments/0/speaker",
            json={"speaker_label": "user"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/recordings/r1/segments/0/text",
            json={"text": "world"},
        ).status_code
        == 200
    )

    rows = db.get_transcription_view("r1")
    assert len(rows) == 1
    assert rows[0]["speaker_label"] == "user"
    assert rows[0]["text"] == "world"


def test_audio_not_found(client: TestClient) -> None:
    """访问不存在的片段音频返回 404."""
    response = client.get("/api/recordings/r1/segments/0/audio")
    assert response.status_code == 404


def test_invalid_speaker_label(client: TestClient, tmp_path: Path) -> None:
    """无效说话人标签返回 400（含已废弃的 needs_review）."""
    config = client.app.state.config
    db = Database(config["db_path"])
    db.save_recording("r1", "/tmp/a.wav", 10.0, 16000, "transcribed")
    seg = Segment(start=0.0, end=1.0, segment_index=0, recording_id="r1")
    db.save_segments("r1", [seg], [str(tmp_path / "0000.wav")])
    db.save_diarization("r1", [seg])

    response = client.put(
        "/api/recordings/r1/segments/0/speaker",
        json={"speaker_label": "invalid"},
    )
    assert response.status_code == 400

    response = client.put(
        "/api/recordings/r1/segments/0/speaker",
        json={"speaker_label": "needs_review"},
    )
    assert response.status_code == 400


def _make_recording(db: Database, tmp_path: Path, rec_id: str = "r1") -> None:
    """构造一条带片段与声纹数据的录音."""
    db.save_recording(rec_id, "/tmp/a.wav", 10.0, 16000, "segmented")
    seg = Segment(start=0.0, end=1.0, segment_index=0, recording_id=rec_id)
    seg.speaker_label = "other"
    db.save_segments(rec_id, [seg], [str(tmp_path / "0000.wav")])
    db.save_diarization(rec_id, [seg])


def test_delete_recording(client: TestClient, tmp_path: Path) -> None:
    """删除录音后数据库记录与片段目录一并清理."""
    config = client.app.state.config
    db = Database(config["db_path"])
    _make_recording(db, tmp_path)
    seg_dir = Path(config["segments_dir"]) / "r1"
    seg_dir.mkdir(parents=True, exist_ok=True)
    (seg_dir / "0000.wav").write_bytes(b"dummy")

    assert client.delete("/api/recordings/r1").status_code == 200
    assert db.get_recording("r1") is None
    assert db.get_segments("r1") == []
    assert not seg_dir.exists()


def test_delete_recording_missing(client: TestClient) -> None:
    """删除不存在的录音返回 404."""
    assert client.delete("/api/recordings/nope").status_code == 404


def test_reset_recording(client: TestClient, tmp_path: Path) -> None:
    """重置录音后中间结果清空，recordings 行保留且状态回到 new."""
    config = client.app.state.config
    db = Database(config["db_path"])
    _make_recording(db, tmp_path)

    assert client.post("/api/recordings/r1/reset").status_code == 200
    rec = db.get_recording("r1")
    assert rec is not None
    assert rec["status"] == "new"
    assert db.get_segments("r1") == []
    assert db.get_diarization("r1") == []


def test_continue_recording_completed(client: TestClient, tmp_path: Path) -> None:
    """已完成录音继续分析返回 400（不启动新任务）."""
    config = client.app.state.config
    db = Database(config["db_path"])
    db.save_recording("r1", "/tmp/a.wav", 10.0, 16000, "evaluated")

    response = client.post("/api/recordings/r1/continue")
    assert response.status_code == 400


def test_continue_recording_missing(client: TestClient) -> None:
    """继续分析不存在的录音返回 404."""
    assert client.post("/api/recordings/nope/continue").status_code == 404


def test_cleanup_orphan_segments(client: TestClient, tmp_path: Path) -> None:
    """孤儿片段（数据库行 + WAV 文件）在重跑后被清理."""
    config = client.app.state.config
    db = Database(config["db_path"])
    db.save_recording("r1", "/tmp/a.wav", 10.0, 16000, "segmented")
    seg0 = Segment(start=0.0, end=1.0, segment_index=0, recording_id="r1")
    seg1 = Segment(start=1.0, end=2.0, segment_index=1, recording_id="r1")
    seg0.speaker_label = "other"
    seg1.speaker_label = "other"
    audio0 = tmp_path / "0000.wav"
    audio1 = tmp_path / "0001.wav"
    audio0.write_bytes(b"dummy")
    audio1.write_bytes(b"dummy")
    db.save_segments("r1", [seg0, seg1], [str(audio0), str(audio1)])
    db.save_diarization("r1", [seg0, seg1])

    # 第二次切分只剩 1 个片段，索引 1 成为孤儿
    db.cleanup_orphan_segments("r1", [0])

    assert db.get_segment_by_index("r1", 0) is not None
    assert db.get_segment_by_index("r1", 1) is None
    assert not audio1.exists()


def test_protect_manual_asr(client: TestClient, tmp_path: Path) -> None:
    """protect_manual 模式下重跑 ASR 不覆盖人工修正文本."""
    from src.types import SegmentTranscription

    config = client.app.state.config
    db = Database(config["db_path"])
    _make_recording(db, tmp_path)
    db.update_asr_text("r1", 0, "人工修正文本")

    tx = SegmentTranscription(
        recording_id="r1",
        segment_index=0,
        speaker_label="other",
        asr_source="local",
        audio_path="/tmp/a.wav",
        start=0.0,
        end=1.0,
        text="重新转写文本",
    )
    db.save_asr_results("r1", [tx], protect_manual=True)
    rows = db.get_transcription_view("r1")
    assert rows[0]["text"] == "人工修正文本"

    # 不保护时允许覆盖
    db.save_asr_results("r1", [tx], protect_manual=False)
    rows = db.get_transcription_view("r1")
    assert rows[0]["text"] == "重新转写文本"


def test_ensure_recording_placeholder(client: TestClient) -> None:
    """新录音先占位插入 recordings 行，run_history 外键不再失败."""
    config = client.app.state.config
    db = Database(config["db_path"])

    db.ensure_recording("r1", "/tmp/a.wav")
    rec = db.get_recording("r1")
    assert rec["status"] == "new"
    assert rec["run_count"] == 0

    # 幂等：重复调用不改变已有行
    db.ensure_recording("r1", "/tmp/a.wav")
    assert db.get_recording("r1")["run_count"] == 0

    # 占位行存在后 run_history 写入成功
    db.save_run_history("r1", "segment", "started")
    assert len(db.get_run_history("r1")) == 1

    # 阶段完成后 save_recording 更新真实数据，run_count 递增为 1
    db.save_recording("r1", "/tmp/a.wav", 10.0, 16000, "segmented")
    rec = db.get_recording("r1")
    assert rec["status"] == "segmented"
    assert rec["run_count"] == 1


def test_run_history(client: TestClient, tmp_path: Path) -> None:
    """运行历史按阶段记录并可查询."""
    config = client.app.state.config
    db = Database(config["db_path"])
    db.save_recording("r1", "/tmp/a.wav", 10.0, 16000, "segmented")
    db.save_run_history("r1", "segment", "started")
    db.save_run_history("r1", "segment", "completed")

    history = db.get_run_history("r1")
    assert [item["status"] for item in history] == ["started", "completed"]


def test_recover_interrupted_recordings(client: TestClient, tmp_path: Path) -> None:
    """服务重启后非终态录音被标记为 failed，终态不受影响."""
    from src.web.service import recover_interrupted_recordings

    config = client.app.state.config
    db = Database(config["db_path"])
    db.save_recording("r1", "/tmp/a.wav", 10.0, 16000, "transcribed")
    db.save_recording("r2", "/tmp/b.wav", 10.0, 16000, "evaluated")

    affected = recover_interrupted_recordings(db)
    assert affected == ["r1"]
    assert db.get_recording("r1")["status"] == "failed"
    assert db.get_recording("r2")["status"] == "evaluated"
