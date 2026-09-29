-- 日常录音分析工具 SQLite 表结构

-- 录音
CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    original_path TEXT NOT NULL,
    sample_rate INTEGER,
    duration_sec REAL,
    processed_at TEXT,
    status TEXT,  -- 'new' | 'segmented' | 'diarized' | 'transcribed' | 'corrected' | 'evaluated' | 'failed'
    created_at TEXT,          -- 首次创建时间（重跑不覆盖）
    run_count INTEGER DEFAULT 0,  -- 切分阶段运行次数
    failed_reason TEXT        -- 最近一次失败原因
);

-- 句子片段
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    audio_path TEXT NOT NULL,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    duration_sec REAL NOT NULL,
    FOREIGN KEY (recording_id) REFERENCES recordings(id),
    UNIQUE(recording_id, segment_index)
);

-- 声纹分离结果
CREATE TABLE IF NOT EXISTS diarization (
    segment_id INTEGER PRIMARY KEY,
    speaker_label TEXT NOT NULL,  -- 'user' | 'other'（旧数据可能残留 needs_review，读取层归一化）
    confidence REAL,
    needs_review BOOLEAN,
    created_at TEXT,
    FOREIGN KEY (segment_id) REFERENCES segments(id)
);

-- ASR 结果
CREATE TABLE IF NOT EXISTS asr_results (
    segment_id INTEGER PRIMARY KEY,
    asr_source TEXT NOT NULL,  -- 'api' | 'local' | 'manual'
    text TEXT,
    words_json TEXT,  -- JSON list of {text, start, end}
    status TEXT,      -- 'success' | 'failed'
    error_message TEXT,
    created_at TEXT,
    is_manual INTEGER DEFAULT 0,  -- 1 表示人工修正文本，重跑时保护
    FOREIGN KEY (segment_id) REFERENCES segments(id)
);

-- 人工校正记录
CREATE TABLE IF NOT EXISTS speaker_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL,
    old_label TEXT NOT NULL,
    new_label TEXT NOT NULL,
    corrected_at TEXT,
    FOREIGN KEY (segment_id) REFERENCES segments(id)
);

-- 声纹更新记录
CREATE TABLE IF NOT EXISTS voiceprint_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    updated_at TEXT,
    positive_segment_ids TEXT,  -- JSON list
    negative_segment_ids TEXT,  -- JSON list
    old_embedding_hash TEXT,
    new_embedding_hash TEXT
);

-- 评测结果（未来）
CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL,
    eval_type TEXT,  -- 'ise' | 'vaa' 等
    result_json TEXT,
    status TEXT DEFAULT 'success',  -- 'success' | 'failed'
    error_message TEXT,
    created_at TEXT,
    FOREIGN KEY (segment_id) REFERENCES segments(id)
);

-- 便于同一片段同一评测类型覆盖更新
CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluations_segment_type
ON evaluations(segment_id, eval_type);

-- 运行历史：每次分析/评测各阶段的起止记录，用于断点续跑定位中断位置
CREATE TABLE IF NOT EXISTS run_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id TEXT NOT NULL,
    stage TEXT NOT NULL,   -- 'segment' | 'diarize' | 'asr' | 'evaluate'
    status TEXT NOT NULL,  -- 'started' | 'completed' | 'failed'
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT,
    FOREIGN KEY (recording_id) REFERENCES recordings(id)
);

CREATE INDEX IF NOT EXISTS idx_run_history_recording
ON run_history(recording_id, id);
