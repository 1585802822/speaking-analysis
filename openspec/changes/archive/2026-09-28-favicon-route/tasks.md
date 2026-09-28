# 任务清单：消除 favicon.ico 404 日志噪音（favicon-route）

## 需求

- 浏览器自动请求 `/favicon.ico` 返回 404，消除该日志噪音

## 实现阶段

- [x] Task 1: `src/web/main.py` 新增 `/favicon.ico` 路由返回 204（import Response） <!-- comet-task:b5715f98-e898-4b9e-a760-404acf4c5e7b -->
- [x] Task 2: `tests/test_web_api.py` 新增 `test_favicon` 断言 204 <!-- comet-task:6b00bc31-db7b-4981-87e3-9ef9dc1706a6 -->
- [x] Task 3: 版本 0.3.1 → 0.3.2，CHANGELOG / TODO 更新 <!-- comet-task:254d545a-8a9d-4b35-961c-f7290bdacf35 -->

## 验证阶段

- [x] `uv run pytest tests/test_web_api.py` 与全量 `pytest tests/` 通过 <!-- comet-task:31932bdd-9adc-45e4-a810-27918a5b4a21 -->
- [x] 实际启动服务后 `curl -i /favicon.ico` 返回 204，uvicorn 日志不再出现 404 <!-- comet-task:43b4aceb-109c-437e-b6ea-33934ca6d276 -->
