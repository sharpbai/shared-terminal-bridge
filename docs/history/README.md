# 历史、演进与调研

本目录回答“为什么这样设计、哪天改了什么”，不作为当前命令来源。当前使用从 [文档入口](../README.md) 开始。

## 按日演进

| 日期 | 内容 |
| --- | --- |
| 2026-10-19 | [任务接口、自发现和 v0.16.0 发布](changes/2026-10-19-model-api-release.md) |
| 2026-10-18 | [执行状态、授权、命令传输阶段记录](changes/2026-10-18-state-and-transport.md) |
| 2026-09 | [项目演进汇总](project-evolution-2026-09.md) |

配套 Adapter 的发现压缩与真实调用性能，统一见 [RDC 历史入口](../../../shared-terminal-bridge-rdc/docs/history/README.md)。

## 设计与调研

- [持久 SSH、历史和 STB 读取方案](research/persistent-shell-and-history.md)：ET/shpool 等复用方向，未验收建议不等于现有能力。
- [模型编排调研与早期规划](model-orchestration-research-and-plan.md)。
- [早期 API](api-v0.1.md)、[本地原型](local-bridge-prototype.md)。

## 记录约定

按日使用 `changes/YYYY-MM-DD-topic.md`；已完成专题调研进入 `research/`。同日同主题归并，跨日互链，保留当时测试和版本快照。最终结论明确区分已发布、已加载、已验证与仅建议；当前接口只在 guides/reference 维护。
