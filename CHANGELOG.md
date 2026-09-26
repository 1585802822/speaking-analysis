# Changelog

本项目所有显著变更都会记录在此文件中。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)：修 bug 末位 +1，新功能中位 +1，破坏性大改首位 +1。

## [Unreleased]

### 新增

- ASR 切换为讯飞「录音文件转写大模型版」（Ifasr_llm）：新增 `iFlytekLlmASRClient` 与工厂 `build_llm_asr_client`，走 `上传音频获取 orderId → 轮询 getResult` 流程，HMAC-SHA1 签名；`api.iflytek.mode` 新增 `llm`。
- 发音评测新增讯飞「Spark VAA 语音分析」可选实现 `iFlytekVoiceInsightClient`（`src/iflytek_evaluation_client.py`），走 `创建任务 → 轮询结果` 流程，HMAC-SHA256 鉴权；`evaluation.mode` 新增 `voice_insight` 选项（默认仍为 `ise`）。
- 新增实测脚本 `scripts/test_iflytek_live.py`（Ifasr_llm + Spark VAA）与 `scripts/test_ise_live.py`（Ifasr_llm + ISE，已从流式版 ASR 切换为 Ifasr_llm）。

### 变更

- `config.yaml` 默认 `iflytek.mode: llm`、`language: autodialect`（中英+方言自动识别）；`evaluation.mode` 默认 `ise`（`model_code: xdeepseekv31` 为 voice_insight 备选）。
- `.env.example` 补充说明：app_id / api_key / api_secret 三者复用同一套凭证，服务器靠不同 host+path 区分服务。

### 说明

- Spark VAA 只接收音频外链 `audioFileURL`，本地文件需先转成公网可访问的 URL（普通内网机器需自行解决外链/内网穿透），故默认评测仍走 ISE。

## [0.2.0] - 2026-09-24

### 新增

- 接入讯飞开放平台 ASR（录音文件识别 / 流式听写），API 启用时失败直接报错、不回退本地模型。
- 新增讯飞语音评测（ISE）客户端 `src/iflytek_evaluation_client.py`，输出准确度/流利度/完整度量化分数。
- 新增 `src/separator.py` 与 `separate` CLI 命令，按声纹把录音切分为 `user.wav` / `other.wav`。
- 发音分析改为优先 ISE 打分（可配置 `standard_threshold` 判定是否标准），本地拼音/音标提示仅作回退。

### 变更

- `config.yaml` 启用讯飞 API 并补充 ISE 评测配置；`analysis.pronunciation.standard_threshold` 默认 80。
- 报告 `详细发现` 章节更名为 `发音评测结果`。
- `.env.example` 新增 `IFLYTEK_APP_ID` / `IFLYTEK_API_KEY` / `IFLYTEK_API_SECRET` 说明。

## [0.1.0] - 2026-09-01

### 初始版本

- 搭建录音分析流水线骨架（预处理、声纹、分离、转写、报告）。
