# Implementation Plan: MVP 音频分离 + API 发音分析

## 目标

先做出一个最小可用程序：分离音频 + 分析普通话/英语发音是否标准。ASR 走讯飞开放平台 API，失败直接报错不降级；发音分析用讯飞 ISE 语音评测打分。

## Build

- [x] 修改 `src/transcriber.py` 支持讯飞 ASR <!-- comet-task:7f2ffcf8-33bd-4c18-afe0-ca0aacfd0d55 -->
- [x] 新建 `src/iflytek_evaluation_client.py` <!-- comet-task:93f30385-ebca-425b-9806-bc3487b41f92 -->
- [x] 新建 `src/separator.py` <!-- comet-task:710329e9-673f-4752-9220-64af823b28fb -->
- [x] 修改 `src/pipeline.py` 只保留发音分析 <!-- comet-task:2379833d-c29f-4e9e-a6b9-7952c033f212 -->
- [x] 修改 `src/pronunciation_analyzer.py` 接入 ISE 分数 <!-- comet-task:7c3eb275-4862-42d7-8389-da57c1cc185e -->
- [x] 修改 `src/cli.py` 新增 `separate` 命令 <!-- comet-task:60c62b82-bc1d-4c02-ad11-dd0b67454bf4 -->
- [x] 修改 `src/reporter.py` 简化报告 <!-- comet-task:efb342f0-315b-476b-9a07-d058041f2f86 -->
- [x] 修改 `config.yaml` 启用讯飞 API 并补充 ISE 配置 <!-- comet-task:58c0969e-09c6-4a3f-a103-39d6a5858a38 -->
- [x] 新增单元/集成测试 <!-- comet-task:a2125594-28ff-4841-9c13-4aeefc4069a5 -->

## Verify

- [x] 运行测试套件 <!-- comet-task:0317f314-88ba-4b39-a756-fd545e185120 -->
- [ ] 使用真实/测试音频验证 CLI 流程 <!-- comet-task:429447d1-0b33-4385-b98f-00f94cfa22c7 -->

## Archive

- [ ] 合并分支并归档 change <!-- comet-task:6f63f719-cb28-4975-ae93-1c6a3a754e9e -->
