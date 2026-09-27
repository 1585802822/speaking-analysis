import {
  createApp,
  ref,
  onMounted,
  computed,
} from "/static/vendor/vue.esm-browser.prod.js";

import {
  apiGet,
  formatTime,
  formatDateTime,
  basename,
  statusText,
  canContinueAnalysis,
  canEvaluate,
  scanDirectory,
  startAnalyze,
  continueAnalysis,
  loadTranscription,
  loadEvaluations,
  updateSpeaker,
  updateText,
  startEvaluate,
  setupKeyboardShortcuts,
} from "/static/common.js";

const path = window.location.pathname;

function useHistory() {
  const recordings = ref([]);
  onMounted(async () => {
    const data = await apiGet("/api/recordings");
    recordings.value = data.recordings || [];
  });
  return { recordings, formatTime, formatDateTime, basename, statusText };
}

function useSelect() {
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
}

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

function useEdit() {
  const params = new URLSearchParams(window.location.search);
  const recordingId = params.get("recording_id");
  const recording = ref(null);
  const segments = ref([]);
  const evaluations = ref([]);
  const evaluating = ref(false);
  const evalProgress = ref({ show: false, message: "", percent: 0 });

  async function load() {
    if (!recordingId) return;
    const [txData, rec] = await Promise.all([
      loadTranscription(recordingId),
      apiGet(`/api/recordings/${recordingId}`),
    ]);
    segments.value = txData.segments || [];
    recording.value = rec;
  }

  function audioUrl(segmentIndex) {
    return `/api/recordings/${recordingId}/segments/${segmentIndex}/audio`;
  }

  async function saveSpeaker(seg) {
    try {
      await updateSpeaker(recordingId, seg.segment_index, seg.speaker_label);
    } catch (e) {
      alert(e.message);
    }
  }

  async function saveText(seg) {
    try {
      await updateText(recordingId, seg.segment_index, seg.text || "");
    } catch (e) {
      alert(e.message);
    }
  }

  const evalMap = computed(() => {
    const map = {};
    for (const ev of evaluations.value) {
      if (!map[ev.segment_index]) map[ev.segment_index] = [];
      map[ev.segment_index].push(ev);
    }
    return map;
  });

  function evalFor(index) {
    return evalMap.value[index] || [];
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
        recordingId,
        (job) => {
          evalProgress.value = {
            show: true,
            message: job.message || "",
            percent: Math.round((job.progress || 0) * 100),
          };
          if (job.status === "completed") {
            loadEvaluations(recordingId).then((data) => {
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
      await continueAnalysis(recordingId, (job) => {
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

  // 键盘快捷键处理
  // 记录最后聚焦的行：焦点在列表外时也能定位当前行
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

  const canContinue = computed(
    () => recording.value && canContinueAnalysis(recording.value.status)
  );
  const canEval = computed(() => recording.value && canEvaluate(recording.value.status));
  const canReevaluate = computed(() => recording.value && recording.value.status === "evaluated");

  onMounted(() => {
    load();
    setupKeyboardShortcuts();
  });

  return {
    recordingId,
    recording,
    segments,
    evaluating,
    evalProgress,
    formatTime,
    statusText,
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
}

if (path.endsWith("/prototype/vue/index.html") || path.endsWith("/prototype/vue/")) {
  createApp({ setup: useHistory }).mount("#app");
} else if (path.endsWith("/prototype/vue/select.html")) {
  createApp({ setup: useSelect }).mount("#app");
} else if (path.endsWith("/prototype/vue/edit.html")) {
  createApp({ setup: useEdit }).mount("#app");
}
