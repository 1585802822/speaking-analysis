"""报告生成."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import ProcessingResult


class Reporter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.output_dir = Path(config["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, result: ProcessingResult, stem: str) -> None:
        md_path = self.output_dir / f"{stem}_report.md"
        json_path = self.output_dir / f"{stem}_report.json"
        corrections_path = self.output_dir / f"{stem}_corrections.json"
        md_path.write_text(self._render_markdown(result), encoding="utf-8")
        json_path.write_text(self._render_json(result), encoding="utf-8")
        corrections_path.write_text(
            self._render_corrections(result, stem), encoding="utf-8"
        )

    def _render_markdown(self, result: ProcessingResult) -> str:
        lines = [
            f"# 录音分析报告：{Path(result.audio_path).name}",
            "",
            "## 总体摘要",
            f"- 时长：{result.duration_sec:.1f} 秒",
            f"- 识别到的用户语音：{result.user_speech_sec:.1f} 秒",
            "",
            "## 详细发现",
        ]
        for analysis in result.analyses:
            lines.append(f"\n### {analysis.dimension}")
            lines.append(analysis.summary)
            for finding in analysis.findings:
                lines.append(f"- {finding}")
        if result.low_confidence_segments:
            lines.append("\n## 低置信度片段（请确认是否为用户本人）")
            for seg in result.low_confidence_segments:
                lines.append(
                    f"- {seg.start:.2f}s - {seg.end:.2f}s (置信度: {seg.confidence:.2f})"
                )
            lines.append("\n## 声纹纠偏反馈")
            lines.append(
                "以下片段置信度较低, 请使用 CLI 确认或否认, 以增量优化声纹模型:"
            )
            lines.append("```bash")
            for seg in result.low_confidence_segments:
                lines.append(
                    f"speaking-analysis correct {result.audio_path} "
                    f"--confirm {seg.start:.2f},{seg.end:.2f}"
                )
            lines.append("```")
            lines.append(
                "若某片段不是您本人, 请将 `--confirm` 替换为 `--deny` 并执行。"
            )
        return "\n".join(lines)

    def _render_json(self, result: ProcessingResult) -> str:
        return json.dumps(
            {
                "audio_path": result.audio_path,
                "duration_sec": result.duration_sec,
                "user_speech_sec": result.user_speech_sec,
                "utterances": [
                    {
                        "text": u.text,
                        "start": u.start,
                        "end": u.end,
                        "words": [
                            {"text": w.text, "start": w.start, "end": w.end}
                            for w in u.words
                        ],
                    }
                    for u in result.utterances
                ],
                "analyses": [
                    {
                        "dimension": a.dimension,
                        "summary": a.summary,
                        "findings": a.findings,
                    }
                    for a in result.analyses
                ],
                "low_confidence_segments": [
                    {"start": s.start, "end": s.end, "confidence": s.confidence}
                    for s in result.low_confidence_segments
                ],
            },
            ensure_ascii=False,
            indent=2,
        )

    def _render_corrections(self, result: ProcessingResult, stem: str) -> str:
        """生成可供人工确认/否认的纠偏 JSON 模板."""
        corrections = {
            "audio_path": result.audio_path,
            "report_stem": stem,
            "low_confidence_segments": [
                {
                    "start": round(s.start, 2),
                    "end": round(s.end, 2),
                    "confidence": round(s.confidence, 4) if s.confidence is not None else None,
                    "confirmed": None,  # 用户可改为 True/False
                }
                for s in result.low_confidence_segments
            ],
            "suggested_command": self._suggested_correct_command(result),
        }
        return json.dumps(corrections, ensure_ascii=False, indent=2)

    def _suggested_correct_command(self, result: ProcessingResult) -> str:
        """生成一条聚合的 correct 命令."""
        if not result.low_confidence_segments:
            return ""
        confirms = " ".join(
            f"--confirm {s.start:.2f},{s.end:.2f}"
            for s in result.low_confidence_segments
        )
        return f"speaking-analysis correct {result.audio_path} {confirms}"
