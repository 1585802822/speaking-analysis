# 提案：消除 favicon.ico 404 日志噪音（favicon-route）

## Why

启动服务后日志出现 `GET /favicon.ico 404 Not Found`，易被误认为故障。实为浏览器每次加载页面自动请求站点图标，而后端未提供该资源。`src/web/static/` 无 favicon 文件、13 个 HTML 均无 `<link rel="icon">`、`src/web/main.py` 无对应路由。

## What Changes

- `src/web/main.py` 新增 `/favicon.ico` 路由，返回 204 No Content（`include_in_schema=False`），彻底消除 404 日志噪音，不引入图标资源。
- `tests/test_web_api.py` 新增 `test_favicon` 断言返回 204。
- 版本 0.3.1 → 0.3.2，CHANGELOG / TODO 同步。
