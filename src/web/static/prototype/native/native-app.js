import {
  renderHistoryList,
  scanDirectory,
  startAnalyze,
  continueAnalysis,
  loadTranscription,
  loadEvaluations,
  updateSpeaker,
  updateText,
  startEvaluate,
  createAudioPlayer,
  formatTime,
  statusText,
  canContinueAnalysis,
  canEvaluate,
  setupKeyboardShortcuts,
} from "/static/common.js";

const linkPrefix = ".";

function initHistoryPage() {
  renderHistoryList(document.getElementById("history-list"), linkPrefix);
}

function initSelectPage() {
  const pathInput = document.getElementById("scan-path");
  const fileList = document.getElementById("file-list");
  const btnScan = document.getElementById("btn-scan");
  const btnAnalyze = document.getElementById("btn-analyze");
  const progress = document.getElementById("progress");
  let selectedFiles = new Set();

  btnScan.addEventListener("click", async () => {
    try {
      selectedFiles = await scanDirectory(pathInput.value.trim(), fileList);
      btnAnalyze.disabled = selectedFiles.size === 0;
    } catch (e) {
      alert(e.message);
    }
  });

  btnAnalyze.addEventListener("click", async () => {
    btnAnalyze.disabled = true;
    progress.style.display = "block";
    try {
      await startAnalyze(selectedFiles, (job) => {
        const pct = Math.round((job.progress || 0) * 100);
        progress.innerHTML = `
          <div>${job.message || ""}（${job.completed || 0}/${job.total || 1} 完成）</div>
          <div class="progress-bar" style="width: ${pct}%;"></div>
        `;
        if (job.status === "completed" || job.status === "failed") {
          btnAnalyze.disabled = false;
        }
      });
    } catch (e) {
      alert(e.message);
      btnAnalyze.disabled = false;
    }
  });
}

function initEditPage() {
  const params = new URLSearchParams(window.location.search);
  const recordingId = params.get("recording_id");
  if (!recordingId) {
    document.getElementById("recording-info").innerHTML = "<p>缺少 recording_id 参数</p>";
    return;
  }

  const info = document.getElementById("recording-info");
  const list = document.getElementById("segments-list");
  const card = document.getElementById("segments-card");
  const btnEvaluate = document.getElementById("btn-evaluate");
  const btnContinue = document.getElementById("btn-continue");
  const btnReevaluate = document.getElementById("btn-reevaluate");
  const evalProgress = document.getElementById("eval-progress");
  let segments = [];
  let recording = null;

  async function refresh() {
    const data = await loadTranscription(recordingId);
    segments = data.segments || [];
    renderSegments();
    recording = await (await fetch(`/api/recordings/${recordingId}`)).json();
    const failedNote = recording.failed_reason
      ? `<div class="failed-reason">${recording.failed_reason}${
          canContinueAnalysis(recording.status)
            ? `<div class="failed-hint">可点击上方「继续分析」从最近完成的阶段继续处理。</div>`
            : ""
        }</div>`
      : "";
    info.innerHTML = `
      <strong>${recordingId}</strong> · 状态：${statusText(recording.status)} · 时长：${formatTime(recording.duration_sec)}
      ${failedNote}
    `;
    // 未分析完 → 显示“继续分析”；已转写 → 可评测；已评测 → 可重新评测
    btnContinue.style.display = canContinueAnalysis(recording.status) ? "" : "none";
    btnEvaluate.disabled = !canEvaluate(recording.status);
    btnReevaluate.disabled = recording.status !== "evaluated";
  }

  function renderSegments() {
    list.innerHTML = "";
    for (const seg of segments) {
      const row = document.createElement("div");
      row.className = `segment-row ${seg.speaker_label || "other"}`;
      row.dataset.segmentIndex = seg.segment_index;
      row.innerHTML = `
        <div class="segment-index">${seg.segment_index}</div>
        <div class="segment-time">${formatTime(seg.start_sec)} - ${formatTime(seg.end_sec)}</div>
        <div class="segment-speaker">
          <select data-field="speaker">
            <option value="user" ${seg.speaker_label === "user" ? "selected" : ""}>user</option>
            <option value="other" ${seg.speaker_label === "other" ? "selected" : ""}>other</option>
          </select>
        </div>
        <div class="segment-text">
          <input type="text" data-field="text" value="${(seg.text || "").replace(/"/g, "&quot;")}" />
        </div>
        <div class="segment-audio"></div>
        <div class="segment-eval" style="display: none;"></div>
      `;
      const speakerSelect = row.querySelector('[data-field="speaker"]');
      speakerSelect.addEventListener("change", async () => {
        try {
          await updateSpeaker(recordingId, seg.segment_index, speakerSelect.value);
          row.className = `segment-row ${speakerSelect.value}`;
        } catch (e) {
          alert(e.message);
          speakerSelect.value = seg.speaker_label;
        }
      });

      const textInput = row.querySelector('[data-field="text"]');
      textInput.addEventListener("blur", async () => {
        if (textInput.value !== seg.text) {
          try {
            await updateText(recordingId, seg.segment_index, textInput.value);
            seg.text = textInput.value;
          } catch (e) {
            alert(e.message);
          }
        }
      });

      const audioWrap = row.querySelector(".segment-audio");
      audioWrap.appendChild(createAudioPlayer(recordingId, seg.segment_index));

      list.appendChild(row);
    }
    card.style.display = "block";
  }

  async function renderEvaluations() {
    const data = await loadEvaluations(recordingId);
    const evals = data.evaluations || [];
    const byIndex = {};
    for (const ev of evals) {
      if (!byIndex[ev.segment_index]) byIndex[ev.segment_index] = [];
      byIndex[ev.segment_index].push(ev);
    }
    for (const row of list.querySelectorAll(".segment-row")) {
      const idx = Number(row.dataset.segmentIndex);
      const panel = row.querySelector(".segment-eval");
      const items = byIndex[idx] || [];
      if (items.length === 0) {
        panel.style.display = "none";
        continue;
      }
      panel.style.display = "block";
      panel.innerHTML = items
        .map((ev) => {
          const result = ev.result || {};
          const findings = result.findings || [];
          const score = findings.find((f) => f.kind === "ise_score");
          const phones = findings.filter((f) => f.kind === "ise_phone");
          let html = "<div class='eval-panel'>";
          if (ev.status === "failed") {
            html += `<div class="eval-failed">该句评测失败：${ev.error_message || "未知原因"}</div>`;
          }
          if (score) {
            html += `
              <div>
                <span class="eval-score">总分 ${score.overall_score?.toFixed(1) || "-"}</span>
                <span class="eval-score">准确度 ${score.accuracy_score?.toFixed(1) || "-"}</span>
                <span class="eval-score">流利度 ${score.fluency_score?.toFixed(1) || "-"}</span>
                <span class="eval-score">完整度 ${score.integrity_score?.toFixed(1) || "-"}</span>
              </div>
            `;
          }
          for (const ph of phones) {
            html += `<div class="phone-error">${ph.word_text || ""}「${ph.phone}」${ph.error_type}</div>`;
          }
          html += "</div>";
          return html;
        })
        .join("");
    }
  }

  function runEvaluate(force) {
    btnEvaluate.disabled = true;
    btnReevaluate.disabled = true;
    evalProgress.style.display = "block";
    startEvaluate(
      recordingId,
      (job) => {
        const pct = Math.round((job.progress || 0) * 100);
        evalProgress.innerHTML = `
          <div>${job.message || ""}</div>
          <div class="progress-bar" style="width: ${pct}%;"></div>
        `;
        if (job.status === "completed") {
          renderEvaluations();
          refresh();
          evalProgress.style.display = "none";
        } else if (job.status === "failed") {
          alert(`评测失败: ${job.message}`);
          refresh();
          evalProgress.style.display = "none";
        }
      },
      force
    ).catch((e) => {
      alert(e.message);
      refresh();
    });
  }

  btnEvaluate.addEventListener("click", () => runEvaluate(false));
  btnReevaluate.addEventListener("click", () => runEvaluate(true));

  // 未分析完的录音可从断点继续分析
  btnContinue.addEventListener("click", async () => {
    btnContinue.disabled = true;
    evalProgress.style.display = "block";
    try {
      await continueAnalysis(recordingId, (job) => {
        const pct = Math.round((job.progress || 0) * 100);
        evalProgress.innerHTML = `
          <div>${job.message || ""}</div>
          <div class="progress-bar" style="width: ${pct}%;"></div>
        `;
        if (job.status === "completed") {
          refresh();
          evalProgress.style.display = "none";
        } else if (job.status === "failed") {
          alert(`分析失败: ${job.message}`);
          refresh();
          evalProgress.style.display = "none";
        }
      });
    } catch (e) {
      alert(e.message);
      btnContinue.disabled = false;
    }
  });

  // 键盘事件处理
  const container = document.getElementById("segments-list");
  // 记录最后聚焦的行：焦点在列表外（如 Element 下拉浮层）时也能定位当前行
  let lastFocusedRow = null;
  container.addEventListener("focusin", () => {
    const row = document.activeElement?.closest(".segment-row");
    if (row) lastFocusedRow = row;
  });
  container.addEventListener("speaking:focus-prev", () => moveFocus(-1));
  container.addEventListener("speaking:focus-next", () => moveFocus(1));
  container.addEventListener("speaking:toggle-speaker", () => {
    const row = currentRow();
    if (!row) return;
    const sel = row.querySelector('[data-field="speaker"]');
    sel.value = sel.value === "user" ? "other" : "user";
    sel.dispatchEvent(new Event("change"));
  });
  container.addEventListener("speaking:save", () => {
    const row = currentRow();
    if (!row) return;
    const input = row.querySelector('[data-field="text"]');
    input.blur();
  });
  container.addEventListener("speaking:play-toggle", () => {
    const row = currentRow();
    if (!row) return;
    const audio = row.querySelector("audio");
    if (audio) {
      if (audio.paused) audio.play();
      else audio.pause();
    }
  });

  function currentRow() {
    const active = document.activeElement;
    return (active && active.closest(".segment-row")) || lastFocusedRow;
  }

  function moveFocus(delta) {
    const rows = Array.from(list.querySelectorAll(".segment-row"));
    const active = document.activeElement;
    let idx = rows.findIndex((r) => r.contains(active));
    if (idx < 0) idx = 0;
    const next = rows[idx + delta];
    if (next) {
      const input = next.querySelector('[data-field="text"]');
      input.focus();
    }
  }

  setupKeyboardShortcuts();
  refresh().catch((e) => alert(e.message));
}

const path = window.location.pathname;
if (path.endsWith("/prototype/native/index.html") || path.endsWith("/prototype/native/")) {
  initHistoryPage();
} else if (path.endsWith("/prototype/native/select.html")) {
  initSelectPage();
} else if (path.endsWith("/prototype/native/edit.html")) {
  initEditPage();
}
