import Alpine from "/static/vendor/alpinejs.module.esm.js";

import {
  apiGet,
  formatTime,
  formatDateTime,
  basename,
  statusText,
  canContinueAnalysis,
  canEvaluate,
  startAnalyze,
  continueAnalysis,
  loadTranscription,
  loadEvaluations,
  updateSpeaker,
  updateText,
  startEvaluate,
  setupKeyboardShortcuts,
} from "/static/common.js";

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || res.statusText);
  }
  return res.json();
}

Alpine.data("historyApp", () => ({
  recordings: [],
  formatTime,
  formatDateTime,
  basename,
  statusText,
  async load() {
    const data = await apiGet("/api/recordings");
    this.recordings = data.recordings || [];
  },
}));

Alpine.data("selectApp", () => ({
  scanPath: "D:\\project\\speaking-analysis\\data\\input",
  files: [],
  selected: [],
  scanning: false,
  scanned: false,
  analyzing: false,
  progress: { show: false, message: "", percent: 0 },
  async scan() {
    this.scanning = true;
    this.scanned = false;
    this.files = [];
    this.selected = [];
    try {
      const data = await apiPost("/api/scan", { path: this.scanPath });
      this.files = data.files || [];
      this.selected = this.files.map((f) => f.path);
      this.scanned = true;
    } catch (e) {
      alert(e.message);
    } finally {
      this.scanning = false;
    }
  },
  async analyze() {
    this.analyzing = true;
    this.progress = { show: true, message: "已创建任务...", percent: 0 };
    try {
      await startAnalyze(new Set(this.selected), (job) => {
        this.progress = {
          show: true,
          message: `${job.message || ""}（${job.completed || 0}/${job.total || 1} 完成）`,
          percent: Math.round((job.progress || 0) * 100),
        };
        if (job.status === "completed" || job.status === "failed") {
          this.analyzing = false;
        }
      });
    } catch (e) {
      alert(e.message);
      this.analyzing = false;
    }
  },
}));

Alpine.data("editApp", () => ({
  recordingId: "",
  recording: null,
  segments: [],
  evaluations: [],
  evaluating: false,
  evalProgress: { show: false, message: "", percent: 0 },
  formatTime,
  init() {
    const params = new URLSearchParams(window.location.search);
    this.recordingId = params.get("recording_id") || "";
    this.load();
    this.trackFocus();
    setupKeyboardShortcuts();
  },
  async load() {
    if (!this.recordingId) return;
    const [txData, rec] = await Promise.all([
      loadTranscription(this.recordingId),
      apiGet(`/api/recordings/${this.recordingId}`),
    ]);
    this.segments = txData.segments || [];
    this.recording = rec;
  },
  audioUrl(segmentIndex) {
    return `/api/recordings/${this.recordingId}/segments/${segmentIndex}/audio`;
  },
  async saveSpeaker(seg) {
    try {
      await updateSpeaker(this.recordingId, seg.segment_index, seg.speaker_label);
    } catch (e) {
      alert(e.message);
    }
  },
  async saveText(seg) {
    try {
      await updateText(this.recordingId, seg.segment_index, seg.text || "");
    } catch (e) {
      alert(e.message);
    }
  },
  evalFor(index) {
    return this.evaluations.filter((ev) => ev.segment_index === index);
  },
  scoreFor(ev) {
    const findings = ev.result?.findings || [];
    return findings.find((f) => f.kind === "ise_score");
  },
  phonesFor(ev) {
    const findings = ev.result?.findings || [];
    return findings.filter((f) => f.kind === "ise_phone");
  },
  statusText,
  canContinue() {
    return this.recording && canContinueAnalysis(this.recording.status);
  },
  canEval() {
    return this.recording && canEvaluate(this.recording.status);
  },
  canReevaluate() {
    return this.recording && this.recording.status === "evaluated";
  },
  async runEvaluate(force = false) {
    this.evaluating = true;
    this.evalProgress = { show: true, message: "准备评测...", percent: 0 };
    try {
      await startEvaluate(
        this.recordingId,
        (job) => {
          this.evalProgress = {
            show: true,
            message: job.message || "",
            percent: Math.round((job.progress || 0) * 100),
          };
          if (job.status === "completed") {
            loadEvaluations(this.recordingId).then((data) => {
              this.evaluations = data.evaluations || [];
            });
            this.load();
            this.evaluating = false;
          } else if (job.status === "failed") {
            alert(`评测失败: ${job.message}`);
            this.load();
            this.evaluating = false;
          }
        },
        force
      );
    } catch (e) {
      alert(e.message);
      this.evaluating = false;
    }
  },
  async runContinue() {
    this.evaluating = true;
    this.evalProgress = { show: true, message: "继续分析...", percent: 0 };
    try {
      await continueAnalysis(this.recordingId, (job) => {
        this.evalProgress = {
          show: true,
          message: job.message || "",
          percent: Math.round((job.progress || 0) * 100),
        };
        if (job.status === "completed" || job.status === "failed") {
          if (job.status === "failed") alert(`分析失败: ${job.message}`);
          this.load();
          this.evaluating = false;
        }
      });
    } catch (e) {
      alert(e.message);
      this.evaluating = false;
    }
  },
  activeRow() {
    const active = document.activeElement;
    return (active && active.closest(".segment-row")) || this._lastFocusedRow;
  },
  trackFocus() {
    // 记录最后聚焦的行：焦点在列表外时也能定位当前行
    document.addEventListener("focusin", () => {
      const row = document.activeElement?.closest(".segment-row");
      if (row) this._lastFocusedRow = row;
    });
  },
  focusOffset(delta) {
    const rows = Array.from(document.querySelectorAll(".segment-row"));
    const row = this.activeRow();
    let idx = rows.findIndex((r) => r === row);
    if (idx < 0) idx = 0;
    const next = rows[idx + delta];
    if (next) next.querySelector('input[data-field="text"]')?.focus();
  },
  toggleSpeakerForActive() {
    const row = this.activeRow();
    if (!row) return;
    const idx = Number(row.dataset.segmentIndex);
    const seg = this.segments.find((s) => s.segment_index === idx);
    if (seg) {
      seg.speaker_label = seg.speaker_label === "user" ? "other" : "user";
      this.saveSpeaker(seg);
    }
  },
  saveActiveText() {
    const row = this.activeRow();
    if (!row) return;
    row.querySelector('input[data-field="text"]')?.blur();
  },
  toggleActiveAudio() {
    const row = this.activeRow();
    if (!row) return;
    const audio = row.querySelector("audio");
    if (audio) {
      if (audio.paused) audio.play();
      else audio.pause();
    }
  },
}));

Alpine.start();
