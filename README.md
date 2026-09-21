# 日常录音分析工具

本地运行的日常录音分析工具，帮助用户通过分析自己的录音发现表达问题。

## 功能

- 文件夹监控：将录音放入 `data/input/`，自动生成报告到 `data/output/`
- 声纹注册：一次性录入本人声音，分析时锁定用户语音
- 音频预处理：VAD、降噪、按自然间断点切分，**并支持按声纹过滤目标说话人片段以减少下游大模型 token 消耗**
- 多维度分析：文本、音频特征、情感/语气、发音标准/正音
- 中英混合转写与报告
- 声纹纠偏：低置信度片段供用户确认/否认

## 安装

项目使用 [uv](https://docs.astral.sh/uv/) 管理依赖：

```bash
uv sync
```

> 若你尚未安装 uv，可参考 [uv 官方文档](https://docs.astral.sh/uv/getting-started/installation/) 安装。
> 首次运行会自动下载 faster-whisper、pyannote.audio、emotion2vec 等模型，需要足够磁盘空间和网络。
> 也可以改用 Model API Gateway（见下方「API 模式」），避免本地下载重型模型。
> 新增的 `noisereduce` 与 `silero-vad` 为可选依赖；未安装时会自动回退到内置的谱减法与能量 VAD。

## API 模式

工具支持将 ASR 转写和声纹嵌入交给统一的 Model API Gateway，本地仅保留预处理、规则分析、报告生成等轻量模块。

启用方式（`config.yaml`）：

```yaml
api:
  enabled: true
  base_url: https://your-ai-gateway.example.com
  api_key_env: AI_GATEWAY_API_KEY
  timeout: 120
  endpoints:
    asr: /v1/audio/transcriptions
    embed: /v1/audio/embeddings
```

- `api_key_env` 指定存放密钥的环境变量名。
- Gateway 需要实现的响应格式见 `src/model_api_client.py` 顶部注释。
- API 调用失败时会自动回退到本地模型/占位逻辑，流水线不会中断。
- 上传音频前请确认隐私策略；情感和正音目前仍保持本地处理。

## 使用

### 1. 声纹注册

```bash
python -m src.cli register sample.wav
```

### 2. 启动监控

```bash
python -m src.cli watch
```

### 3. 单次分析

```bash
python -m src.cli analyze meeting.mp3
```

## 目录结构

```
data/input/        # 放入待分析录音
data/output/       # 自动生成报告
data/voiceprint/   # 注册声纹数据
tests/fixtures/    # 测试音频
tmp/               # 临时处理文件
src/               # 源代码
tests/             # 自动化测试
scripts/           # 预处理/分离等辅助脚本
docs/              # 设计文档与计划
```

## 配置

编辑 `config.yaml` 调整目录、阈值、模型等参数。

### 预处理配置

`config.yaml` 中新增 `preprocessing` 段，可切换降噪/VAD 后端并调整说话人过滤阈值：

```yaml
preprocessing:
  denoise:
    backend: noisereduce  # noisereduce | rnnoise | spectral
  vad:
    backend: silero       # silero | energy
    threshold: 0.5
  speaker_filter:
    enabled: true
    similarity_threshold: 0.75
    low_confidence_threshold: 0.55
```

- `denoise.backend`：`默认 `noisereduce`（需安装）；失败时自动回退到 `spectral`（内置谱减法）。
- `vad.backend`：默认 `silero`（需安装），准确率更高；失败时自动回退到 `energy`。
- `speaker_filter`：对 VAD 得到的语音段按注册声纹过滤，只保留高置信度目标说话人片段。
- 任何后端加载失败时都会自动回退，不中断流水线。

## 开发

```bash
uv run pytest tests/
```

代码格式化使用 Ruff：

```bash
uv run ruff format src tests scripts
uv run ruff check --fix src tests scripts
```
