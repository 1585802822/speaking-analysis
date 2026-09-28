# 验证报告：消除 favicon.ico 404 日志噪音（favicon-route）

日期：2026-09-28

## 问题

启动服务后日志出现 `GET /favicon.ico 404 Not Found`。实为浏览器每次加载页面自动请求站点图标，后端未提供该资源（`src/web/static/` 无 favicon 文件、13 个 HTML 均无 `<link rel="icon">`、`main.py` 无对应路由）。非功能故障，但日志易被误认为报错。

## 验证项与结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| 单元测试 | `uv run pytest tests/test_web_api.py -q` | 通过（19 passed，含新增 test_favicon） |
| 全量回归 | `uv run pytest tests/ -q` | 通过（175 passed，exit=0，已录为 verify 检查） |
| 接口实测 | 启动服务后 `curl -i /favicon.ico` | 通过：`HTTP/1.1 204 No Content` |
| 首页未受影响 | `curl /` | 通过：200 |
| 日志确认 | 请求 favicon 后检查 uvicorn 日志 | 通过：日志显示 `GET /favicon.ico" 204 No Content`，无 404 条目 |

服务日志实测片段：

```
INFO:     127.0.0.1:12765 - "GET /favicon.ico HTTP/1.1" 204 No Content
INFO:     127.0.0.1:12771 - "GET /favicon.ico HTTP/1.1" 204 No Content
```

## 结论

404 日志噪音已彻底消除，浏览器请求改为收到 204 正常响应；首页与静态资源不受影响。验证通过。
