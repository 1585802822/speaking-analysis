# TODO

三栏清单：开工前先读，完工后更新。

## 待办

- [ ] force 重跑 test.WAV 全流程（新切分参数 + 双模型 ASR 生效；会清空 3 段人工修正与评测结果，60 分钟音频 + 本地 large-v3 转写耗时较长，建议夜间执行）
- [ ] 重跑后 SQL 验收：段数约 700 上下（远低于旧 2321）、user 句有真实文本（无占位、无大面积「转写结果为空」）、other 句 asr_source='local' 且有真实文本
- [ ] 六项体验修复分步提交（Ruff 格式化后小步提交，提交前与用户确认标题）

## 进行中

（无）

## 已完成

- [x] 修复 `scripts/start.bat` 双击报错（`scripts\scripts\launcher.py`）：中文注释改 ASCII + CRLF + 绝对路径 `%~dp0launcher.py`，新增 `TestStartBat` 防回归测试与 `.gitattributes`
- [x] 一键启动器：`scripts/launcher.py`（解耦、纯标准库、子进程拉起 web+watch+浏览器）+ `scripts/start.bat` 双击入口；12 个单元测试 + 实际启动/Ctrl+C 回收/start.bat 冒烟全部通过
- [x] 前端依赖本地化：Vue / Element Plus / Alpine 下载到 `src/web/static/vendor/`，移除 unpkg / jsdelivr CDN 引用
- [x] UI 修复：「继续分析」按钮收敛 + 说明提示；状态文案「待校对」；文件名去扩展名；时长/处理时间精简（formatTime / formatDateTime）
- [x] 说话人二分类 user / other（needs_review 不再产生，读取层归一化旧数据）
- [x] 句子切分修复：停顿阈值 0.7s、句边界取停顿终点、长句能量谷切分、相邻短句合并（test.WAV 实测 707 段、中位 4.12s、<1s 仅 4 段）
- [x] ASR 双模型：user 句走 API（失败/空回退本地），other 句本地 faster-whisper 懒加载
- [x] 快捷键修复：容器直派发事件、x 键翻转 user/other、Alpine init() 双重注册修复
- [x] 全部 160 个测试通过；4 套原型 headless 渲染验证通过
