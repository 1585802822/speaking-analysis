# Changelog

本项目所有显著变更都会记录在此文件中。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)：修 bug 末位 +1，新功能中位 +1，破坏性大改首位 +1。

## [Unreleased]

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
