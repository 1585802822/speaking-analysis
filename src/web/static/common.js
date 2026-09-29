/**
 * Web UI 通用工具函数.
 *
 * 提供 API 调用、SSE 监听、格式化、键盘快捷键分发等能力，
 * 供原生 / Vue / Alpine / Element Plus 四套前端原型共享.
 */

const API_BASE = "";

async function _fetchJson(method, path, body) {
  const options = {
    method,
    headers: {},
  };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      msg = data.detail || msg;
    } catch {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const apiGet = (path) => _fetchJson("GET", path);
export const apiPost = (path, body) => _fetchJson("POST", path, body);
export const apiPut = (path, body) => _fetchJson("PUT", path, body);
export const apiDelete = (path) => _fetchJson("DELETE", path);

export function formatTime(seconds) {
  if (seconds === undefined || seconds === null) return "-";
  const total = Number(seconds);
  if (!Number.isFinite(total) || total < 0) return "-";
  if (total < 60) return `${total.toFixed(1)}s`;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

/** 把后端 UTC ISO 时间戳显示为本地 "MM-DD HH:mm" */
export function formatDateTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function basename(path) {
  if (!path) return "";
  const name = String(path).replace(/\\/g, "/").split("/").pop();
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
}

export function statusText(status) {
  const map = {
    new: "未分析",
    segmented: "已切分",
    diarized: "已分离",
    transcribed: "已转写",
    corrected: "待校对",
    evaluated: "已评测",
    failed: "处理失败",
  };
  return map[status] || status;
}

/** 该状态是否可以从断点继续分析（仅分析未完成时） */
export function canContinueAnalysis(status) {
  return ["segmented", "diarized", "failed"].includes(status);
}

/** 该状态是否可以进行评测 */
export function canEvaluate(status) {
  return ["transcribed", "corrected"].includes(status);
}

export function createAudioPlayer(recordingId, segmentIndex) {
  const audio = document.createElement("audio");
  audio.controls = true;
  audio.preload = "none";
  audio.src = `/api/recordings/${recordingId}/segments/${segmentIndex}/audio`;
  audio.style.width = "160px";
  audio.style.height = "30px";
  return audio;
}

export function listenJobSSE(jobId, onUpdate) {
  const es = new EventSource(`/api/jobs/${jobId}/stream`);
  // 是否已收到过任何事件；用于区分「连接从未建立」与「流正常结束」
  let settled = false;

  // 服务端以命名事件推送：进度用 update，业务错误用 job_error。
  // 注意不能用 es.onmessage —— 它只接收没有 event 字段的默认 message 事件。
  es.addEventListener("update", (e) => {
    settled = true;
    const data = JSON.parse(e.data);
    onUpdate(data);
    if (["completed", "failed"].includes(data.status)) {
      // 服务端推完终态即断流，必须主动关闭，否则浏览器会无限自动重连
      es.close();
    }
  });

  // 服务端明确告知任务不存在（如服务重启后内存任务丢失）
  es.addEventListener("job_error", (e) => {
    settled = true;
    let detail = "任务不存在或已丢失（服务可能已重启）";
    try {
      detail = JSON.parse(e.data).detail || detail;
    } catch {}
    es.close();
    onUpdate({ status: "failed", message: detail, progress: 0 });
  });

  // 传输层错误：EventSource 默认会自动重连，不能一律当作失败；
  // 只有从未收到任何事件、且连接已关闭，才说明连接建立失败
  es.onerror = () => {
    if (!settled && es.readyState === EventSource.CLOSED) {
      onUpdate({ status: "failed", message: "SSE 连接错误", progress: 0 });
    }
  };
  return es;
}

export async function renderHistoryList(container, linkPrefix) {
  if (typeof container === "string") {
    container = document.querySelector(container);
  }
  const data = await apiGet("/api/recordings");
  container.innerHTML = "";
  if (!data.recordings || data.recordings.length === 0) {
    container.innerHTML = "<p>暂无分析记录</p>";
    return;
  }
  const table = document.createElement("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>ID</th>
        <th>文件</th>
        <th>状态</th>
        <th>时长</th>
        <th>处理时间</th>
        <th>操作</th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = table.querySelector("tbody");
  for (const rec of data.recordings) {
    const tr = document.createElement("tr");
    if (rec.status === "failed") {
      tr.className = "row-failed";
    }
    tr.innerHTML = `
      <td>${rec.id}</td>
      <td title="${rec.original_path}">${basename(rec.original_path)}</td>
      <td>${statusText(rec.status)}${rec.failed_reason ? `<div class="failed-reason">${rec.failed_reason}</div>` : ""}</td>
      <td>${formatTime(rec.duration_sec)}</td>
      <td>${formatDateTime(rec.processed_at)}</td>
      <td class="actions"></td>
    `;
    const actions = tr.querySelector(".actions");
    if (canContinueAnalysis(rec.status)) {
      const btn = document.createElement("button");
      btn.className = "btn btn-primary";
      btn.title =
        rec.status === "failed"
          ? "从最近完成的阶段继续处理（不会重跑已完成的阶段）"
          : "从上次中断处继续未完成的阶段";
      btn.textContent = "继续分析";
      btn.addEventListener("click", () => {
        continueAnalysis(rec.id, (job) => {
          btn.textContent = job.message || "处理中...";
          btn.disabled = job.status !== "completed" && job.status !== "failed";
          if (job.status === "completed" || job.status === "failed") {
            renderHistoryList(container, linkPrefix);
          }
        });
      });
      actions.appendChild(btn);
    }
    if (rec.status !== "new") {
      const link = document.createElement("a");
      link.className = "btn";
      link.href = `${linkPrefix}/edit.html?recording_id=${rec.id}`;
      link.textContent = "编辑";
      actions.appendChild(link);
    }
    const delBtn = document.createElement("button");
    delBtn.className = "btn btn-danger";
    delBtn.textContent = "删除";
    delBtn.addEventListener("click", async () => {
      if (!window.confirm(`确定删除录音 ${basename(rec.original_path)} 吗？将同时删除数据库记录和片段文件。`)) {
        return;
      }
      await apiDelete(`/api/recordings/${rec.id}`);
      renderHistoryList(container, linkPrefix);
    });
    actions.appendChild(delBtn);
    tbody.appendChild(tr);
  }
  container.appendChild(table);
}

export async function scanDirectory(path, listContainer) {
  if (typeof listContainer === "string") {
    listContainer = document.querySelector(listContainer);
  }
  listContainer.innerHTML = "<p>扫描中...</p>";
  const data = await apiPost("/api/scan", { path });
  listContainer.innerHTML = "";
  if (!data.files || data.files.length === 0) {
    listContainer.innerHTML = "<p>未找到音频文件</p>";
    return [];
  }
  const selected = new Set(data.files.map((f) => f.path));
  for (const file of data.files) {
    const label = document.createElement("label");
    label.className = "file-item";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = file.path;
    cb.checked = true;
    cb.addEventListener("change", () => {
      if (cb.checked) selected.add(file.path);
      else selected.delete(file.path);
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(` ${file.name}`));
    listContainer.appendChild(label);
  }
  return selected;
}

export async function startAnalyze(selectedFiles, onProgress, force = false) {
  const files = Array.from(selectedFiles);
  if (files.length === 0) {
    alert("请至少选择一个文件");
    return;
  }
  const data = await apiPost("/api/analyze", { files, force });
  const jobIds = data.job_ids || [];
  let completed = 0;
  let failed = 0;
  onProgress({
    status: "pending",
    message: `已创建 ${jobIds.length} 个分析任务`,
    progress: 0,
    total: jobIds.length,
    completed: 0,
    failed: 0,
  });
  for (const jobId of jobIds) {
    listenJobSSE(jobId, (job) => {
      if (job.status === "completed") completed++;
      if (job.status === "failed") failed++;
      onProgress({
        ...job,
        total: jobIds.length,
        completed,
        failed,
      });
    });
  }
}

export async function loadTranscription(recordingId) {
  return apiGet(`/api/recordings/${recordingId}/transcription`);
}

export async function loadEvaluations(recordingId) {
  return apiGet(`/api/recordings/${recordingId}/evaluations`);
}

export async function updateSpeaker(recordingId, segmentIndex, label) {
  return apiPut(`/api/recordings/${recordingId}/segments/${segmentIndex}/speaker`, {
    speaker_label: label,
  });
}

export async function updateText(recordingId, segmentIndex, text) {
  return apiPut(`/api/recordings/${recordingId}/segments/${segmentIndex}/text`, { text });
}

export async function startEvaluate(recordingId, onProgress, force = false) {
  const data = await apiPost(`/api/recordings/${recordingId}/evaluate?force=${force}`, {});
  listenJobSSE(data.job_id, onProgress);
  return data.job_id;
}

/** 继续处理一条未完成的录音（从最近完成的阶段接着跑） */
export async function continueAnalysis(recordingId, onProgress) {
  const data = await apiPost(`/api/recordings/${recordingId}/continue`, {});
  listenJobSSE(data.job_id, onProgress);
  return data.job_id;
}

/**
 * 直接向片段列表容器派发事件（不依赖当前焦点向上冒泡，
 * 避免焦点不在列表内时快捷键失效）.
 */
function _dispatch(name, detail) {
  const target = document.querySelector("#segments-list");
  if (!target) return;
  target.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
}

// 防止重复注册（如 Alpine 组件的 init 被自动调用又显式调用）
let _shortcutsBound = false;

export function setupKeyboardShortcuts() {
  if (_shortcutsBound) return;
  _shortcutsBound = true;
  document.addEventListener("keydown", (e) => {
    const active = document.activeElement;
    if (!active) return;
    const isEditable =
      active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable;

    if (e.key === "ArrowUp") {
      e.preventDefault();
      _dispatch("speaking:focus-prev", {});
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      _dispatch("speaking:focus-next", {});
    } else if (e.key === "x" && !isEditable) {
      e.preventDefault();
      _dispatch("speaking:toggle-speaker", {});
    } else if ((e.key === "s" || (e.ctrlKey && e.key === "s")) && !isEditable) {
      e.preventDefault();
      _dispatch("speaking:save", {});
    } else if (e.key === " " && !isEditable) {
      e.preventDefault();
      _dispatch("speaking:play-toggle", {});
    }
  });
}

// 兼容旧式 script 标签引入
window.SpeakingAPI = {
  apiGet,
  apiPost,
  apiPut,
  apiDelete,
  formatTime,
  formatDateTime,
  basename,
  statusText,
  canContinueAnalysis,
  canEvaluate,
  createAudioPlayer,
  listenJobSSE,
  renderHistoryList,
  scanDirectory,
  startAnalyze,
  continueAnalysis,
  loadTranscription,
  loadEvaluations,
  updateSpeaker,
  updateText,
  startEvaluate,
  setupKeyboardShortcuts,
};
