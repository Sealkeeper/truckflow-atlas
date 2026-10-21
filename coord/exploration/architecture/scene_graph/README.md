# 路线 C：整帧通道场景图（已实测，最小说明）

负责人：`architecture_challenger`

代码 commit：`9df7986d06c8e4ff487e92d7a741bea447ebf77d`

状态：五帧诊断已跑完；**不作为独立计数架构继续**，只保留
`part_of` / `queue_index` 关系思路。本页供新路线做机制重叠核查。

## 1. 输入与预处理

- 输入：**一张整帧原图**（单机位单帧）。
- 预处理：无。没有网格叠加、没有透视标定、没有裁剪、没有缩放拼接。
- 输入图像数：每个主调用 1 张。

## 2. 调用结构

| 阶段 | 次数/帧 | 说明 |
|---|---:|---|
| 主场景图 | 1 | 整帧，`max_tokens=2800`，temperature 0，150 s 流式 deadline，2 次重试 |
| 候选对语义去重 | 0–N | 仅对几何提议的重叠/同窗相邻候选对调用；模型判 `same_vehicle` 才合并 |
| 车型复核 | 每个存活候选 1 次 | 单独裁剪，`max_tokens=500` |

五帧实测合计 **21 次调用、67,228 token、224.8 s**（平均约 4.2 次/帧）。
逐帧：`north_300` 3 次、`north_600` 3 次、`south_600` 5 次、
`north_1200` 4 次、`south_1200` 6 次。

## 3. 输出 schema（主调用）

```json
{
  "lanes": [
    {"lane_id": "L1", "description": "", "near_y": 0.0, "far_y": 0.0, "occlusions": ""}
  ],
  "vehicles": [
    {
      "vehicle_id": "V1",
      "lane_id": "L1",
      "queue_index": 0,
      "bbox": [0.0, 0.0, 0.0, 0.0],
      "center": [0.0, 0.0],
      "size": "large|medium|small|unknown",
      "visible": "full|partial_top|partial_side|trailer_only",
      "is_truck": true,
      "heading": "朝向镜头|背向镜头|横向|不确定",
      "cargo_color": "",
      "body_style": "",
      "occluded_by": "",
      "part_of": null,
      "identity_clues": "",
      "evidence": "",
      "uncertain": false
    }
  ],
  "scene_notes": ""
}
```

后处理：`part_of` 指向另一节点时，把子框并进父框并删除子节点；随后仍由
多模态 A/B 判定合并重复候选，最后逐候选做车型复核。几何从不直接决定合并。

完整 prompt：`SCENE_GRAPH_PROMPT.txt`。完整源码：`arch_scenegraph.py`。

## 4. 五帧实测（人工 v2 总数）

| 帧 | 人工 | 预测 | 误差 |
|---|---:|---:|---:|
| `north_300` | 3 | 2 | -1 |
| `north_600` | 4 | 2 | -2 |
| `south_600` | 4 | 4 | 0 |
| `north_1200` | 3 | 3 | 0 |
| `south_1200` | 5 | 4 | -1 |

合计：2/5 总数 exact、MAE 0.800、漏 4、多 0。它不乱加，而是把远端集装箱
队列整体当成背景；这正是“单次整帧结构化输出”最容易漏的部分。

## 5. 与“固定 3×4 空间参照图 + 逐区域 checked/unknown/vehicle_ids + 一次
全局对象集合”的重叠判断

**结论：目标相似，机制不完全相同；新路线不是本路线的重复实现，但必须显式
解决本路线暴露的覆盖失败。**

相同点：

- 都是一次整帧语义读取，而不是逐格/逐窗识别。
- 都要求先给出全局对象集合，再计数；都不按格数直接相加。
- 都依赖 `vehicle_ids` / 节点关系来避免同一辆车被重复计算。

不同点：

- C 没有任何固定空间参照，也没有“逐区域 checked/unknown”清单；模型可以
  完全不提远端队列而不被记录为遗漏。新路线的 3×4 参照和逐区域状态正好补这一点。
- C 的 `lane_id` / `queue_index` 是语义队列关系；新路线是固定空间网格上的
  覆盖状态。两者可以组合：网格保证覆盖，关系字段保证同一辆车只算一次。

建议新路线直接复用 C 的 `part_of` 语义判定，但把 C 的覆盖缺口作为必须监控的
失败模式：任何 `unknown` 区域都要单列，不能自动算作空。

## 6. 原始证据

五帧完整 run JSON（含 prompt、原始回答、reasoning、usage、失败）在私有
`research/architecture_challenge/runs/scene_graph/`；本次公共发布在
`../../raw/scene_graph/` 同步原始 JSON。
