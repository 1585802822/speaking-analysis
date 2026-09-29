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

const { createApp, ref, onMounted } = Vue;

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

function statusType(status) {
  if (status === "evaluated" || status === "corrected") return "success";
  if (status === "failed") return "danger";
  return "warning";
}

const path = window.location.pathname;

if (path.endsWith("/prototype/element/index.html") || path.endsWith("/prototype/element/")) {
  createApp({
    setup() {
      const recordings = ref([]);
      onMounted(async () => {
        const data = await apiGet("/api/recordings");
        recordings.value = data.recordings || [];
      });
      return {
        recordings,
        formatTime,
        formatDateTime,
        basename,
        statusText,
        statusType,
        location: window.location,
      };
    },
  }).use(ElementPlus).mount("#app");
} else if (path.endsWith("/prototype/element/select.html")) {
  createApp({
    setup() {
      const scanPath = ref("D:\\project\\speaking-analysis\\data\\input");
      const files = ref([]);
      const selected = ref([]);
      const scanning = ref(false);
      const scanned = ref(false);
      const analyzing = ref(false);
      const progress = ref({ show: false, message: "", percent: 0 });

      async function scan() {
        scanning.value = true;
        scanned.value = false;
        files.value = [];
        selected.value = [];
        try {
          const data = await apiPost("/api/scan", { path: scanPath.value });
          files.value = data.files || [];
          selected.value = files.value.map((f) => f.path);
          scanned.value = true;
        } catch (e) {
          alert(e.message);
        } finally {
          scanning.value = false;
        }
      }

      async function analyze() {
        analyzing.value = true;
        progress.value = { show: true, message: "已创建任务...", percent: 0 };
        try {
          await startAnalyze(new Set(selected.value), (job) => {
            progress.value = {
              show: true,
              message: `${job.message || ""}（${job.completed || 0}/${job.total || 1} 完成）`,
              percent: Math.round((job.progress || 0) * 100),
            };
            if (job.status === "completed" || job.status === "failed") {
              analyzing.value = false;
            }
          });
        } catch (e) {
          alert(e.message);
          analyzing.value = false;
        }
      }

      return {
        scanPath,
        files,
        selected,
        scanning,
        scanned,
        analyzing,
        progress,
        scan,
        analyze,
      };
    },
  }).use(ElementPlus).mount("#app");
} else if (path.endsWith("/prototype/element/edit.html")) {
  createApp({
    setup() {
      const params = new URLSearchParams(window.location.search);
      const recordingId = ref(params.get("recording_id") || "");
      const recording = ref(null);
      const segments = ref([]);
      const evaluations = ref([]);
      const evaluating = ref(false);
      const evalProgress = ref({ show: false, message: "", percent: 0 });
      // 各片段最近一次已保存的文本：内容未变则不发请求
      const savedTexts = new Map();

      async function load() {
        if (!recordingId.value) return;
        const [txData, rec] = await Promise.all([
          loadTranscription(recordingId.value),
          apiGet(`/api/recordings/${recordingId.value}`),
        ]);
        segments.value = txData.segments || [];
        savedTexts.clear();
        for (const seg of segments.value) {
          savedTexts.set(seg.segment_index, seg.text || "");
        }
        recording.value = rec;
      }

      onMounted(() => {
        load();
        setupKeyboardShortcuts();
      });

      function audioUrl(segmentIndex) {
        return `/api/recordings/${recordingId.value}/segments/${segmentIndex}/audio`;
      }

      async function saveSpeaker(seg) {
        try {
          await updateSpeaker(recordingId.value, seg.segment_index, seg.speaker_label);
        } catch (e) {
          alert(e.message);
        }
      }

      async function saveText(seg) {
        const text = seg.text || "";
        // 内容未变则不发请求：否则试听时点一下文本框就会被记为人工修正
        if (text === (savedTexts.get(seg.segment_index) ?? "")) return;
        try {
          await updateText(recordingId.value, seg.segment_index, text);
          savedTexts.set(seg.segment_index, text);
        } catch (e) {
          alert(e.message);
        }
      }

      function evalFor(index) {
        return evaluations.value.filter((ev) => ev.segment_index === index);
      }

      function scoreFor(ev) {
        const findings = ev.result?.findings || [];
        return findings.find((f) => f.kind === "ise_score");
      }

      function phonesFor(ev) {
        const findings = ev.result?.findings || [];
        return findings.filter((f) => f.kind === "ise_phone");
      }

      async function runEvaluate(force = false) {
        evaluating.value = true;
        evalProgress.value = { show: true, message: "准备评测...", percent: 0 };
        try {
          await startEvaluate(
            recordingId.value,
            (job) => {
              evalProgress.value = {
                show: true,
                message: job.message || "",
                percent: Math.round((job.progress || 0) * 100),
              };
              if (job.status === "completed") {
                loadEvaluations(recordingId.value).then((data) => {
                  evaluations.value = data.evaluations || [];
                });
                load();
                evaluating.value = false;
              } else if (job.status === "failed") {
                alert(`评测失败: ${job.message}`);
                load();
                evaluating.value = false;
              }
            },
            force
          );
        } catch (e) {
          alert(e.message);
          evaluating.value = false;
        }
      }

      async function runContinue() {
        evaluating.value = true;
        evalProgress.value = { show: true, message: "继续分析...", percent: 0 };
        try {
          await continueAnalysis(recordingId.value, (job) => {
            evalProgress.value = {
              show: true,
              message: job.message || "",
              percent: Math.round((job.progress || 0) * 100),
            };
            if (job.status === "completed" || job.status === "failed") {
              if (job.status === "failed") alert(`分析失败: ${job.message}`);
              load();
              evaluating.value = false;
            }
          });
        } catch (e) {
          alert(e.message);
          evaluating.value = false;
        }
      }

      // 记录最后聚焦的行：el-select 下拉浮层 teleport 到 body 后焦点不在行内，靠它兜底
      let lastFocusedRow = null;
      document.addEventListener("focusin", () => {
        const row = document.activeElement?.closest(".segment-row");
        if (row) lastFocusedRow = row;
      });

      function activeRow() {
        const active = document.activeElement;
        return (active && active.closest(".segment-row")) || lastFocusedRow;
      }

      function focusOffset(delta) {
        const rows = Array.from(document.querySelectorAll(".segment-row"));
        const row = activeRow();
        let idx = rows.findIndex((r) => r === row);
        if (idx < 0) idx = 0;
        const next = rows[idx + delta];
        if (next) next.querySelector('input[data-field="text"]')?.focus();
      }

      function toggleSpeakerForActive() {
        const row = activeRow();
        if (!row) return;
        const idx = Number(row.dataset.segmentIndex);
        const seg = segments.value.find((s) => s.segment_index === idx);
        if (seg) {
          seg.speaker_label = seg.speaker_label === "user" ? "other" : "user";
          saveSpeaker(seg);
        }
      }

      function saveActiveText() {
        const row = activeRow();
        if (!row) return;
        row.querySelector('input[data-field="text"]')?.blur();
      }

      function toggleActiveAudio() {
        const row = activeRow();
        if (!row) return;
        const audio = row.querySelector("audio");
        if (audio) {
          if (audio.paused) audio.play();
          else audio.pause();
        }
      }

      const canContinue = () => canContinueAnalysis(recording.value?.status);
      const canEval = () => canEvaluate(recording.value?.status);
      const canReevaluate = () => recording.value?.status === "evaluated";

      return {
        recordingId,
        recording,
        segments,
        evaluating,
        evalProgress,
        formatTime,
        statusText,
        statusType,
        canContinue,
        canEval,
        canReevaluate,
        audioUrl,
        saveSpeaker,
        saveText,
        runEvaluate,
        runContinue,
        evalFor,
        scoreFor,
        phonesFor,
        focusOffset,
        toggleSpeakerForActive,
        saveActiveText,
        toggleActiveAudio,
      };
    },
  }).use(ElementPlus).mount("#app");
}
