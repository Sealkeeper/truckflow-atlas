# 架构挑战路线：当前状态

更新时间：2026-10-21（北京时间）

负责人：`architecture_challenger`

分支 / commit：`research/architecture-challenge` / `9df7986`

PR：#10（公开，未合并）

## 本目录已发布内容

| 文件 | 内容 |
|---|---|
| `config.json` | A′ 冻结配置：窗口、prompt、模型 id、deadline、retries、融合规则 |
| `metrics.json` | 五帧 + 20 帧指标、两条基线、成本、路线判定 |
| `failures.md` | 基线漏计、A′ 全部错误帧、B/C/D 失败 |
| `raw_runs_manifest.json` | 40 个原始 run 的路径、大小、SHA-256 |
| `raw/` | 40 个原始 run JSON（prompt、回答、reasoning、usage、失败） |
| `scene_graph/README.md` | 路线 C 的最小方法说明、调用结构、schema、五帧实测 |
| `scene_graph/SCENE_GRAPH_PROMPT.txt` | C 的完整 prompt |
| `scene_graph/arch_scenegraph.py` | C 的完整源码 |
| `raw/scene_graph/` | C 的五帧原始 run JSON（prompt、回答、reasoning、usage） |
| `RUN_COMMANDS.md` | 复跑与重算指标命令 |

## 当前状态

- A′ 的 20 帧回归已完成（冻结配置，未调 prompt）：**13/20 exact、MAE 0.400、
  漏 3、多 5**，差于纯 aisle 基线 16/20、0.25 和整帧基线 16/20、0.300。
  186 次调用、511,742 token、均值 90.7 s/帧；20/20 有效、0 失败。
- 五帧诊断 A′ 4/5、MAE 0.200 只是开发子集结果，没有在 20 帧上复现。
- **路线判定（最终）**：A′ 不进入实现；生产主路径继续用纯 aisle 基线。
  A′ 的 far 窗口只作为远端取证；C 只保留 `part_of` / `queue_index` 关系思路；
  B、D 淘汰为独立架构。

## 给新路线的最小重叠提示

“固定 3×4 空间参照 + 逐区域 checked/unknown/vehicle_ids + 一次全局对象集合”
与 C 的相同点是单次整帧、全局对象集合、按 ID 去重；关键差异是 C **没有**
固定空间参照和逐区域覆盖清单，因此远端队列可以整段不被提及而不留痕迹。
详见 `scene_graph/README.md` 第 5 节。
