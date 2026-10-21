# 部件路线 v2：车顶/顶面组成关系（冻结计划）

冻结时间：2026-10-21（北京时间）。负责：`part_relation_v2`。准确率第一，性能第二。工作目录仅 `sessions/part_relation_v2`，公共发布仅本目录；未读取其他 sessions。

本计划在首个付费请求之前发布。用户最新约束优先：只依据车顶、货厢顶面和顶部轮廓识别；下部车牌、轮胎、尾灯、车身侧面文字和不可见连接不得用于实体确认。依据 `coord/exploration/ROOF_ONLY_STEERING.md` 与 `coord/exploration/ROUND2_CENTRAL_REVIEW.md` 的执行边界。

## 1. 要解决的问题与旧路线差异

原目标是车头挂车误拆和远处货厢误合并。旧路线各自的做法：

| 旧路线 | 机制 | 与本路线的关系 |
|---|---|---|
| 单遍 B | 一张 aisle 图直接输出逐车完整框和总数；`counts.total=len(vehicles)` | 本路线不输出完整车框、不直接报总数；只输出顶面观察和顶面关系，确定性组装顶面单元 |
| 场景图 C | 整车节点 + 单父指针 `part_of` + `queue_index`；合并后仍按车辆节点计数 | 本路线是顶面级的成对证书（接缝/间隙/遮挡框），没有 `part_of` 父指针，也不把“整车队形”当关系 |
| 双机位联合 | 一次读南北双图，直接输出唯一集合和跨机位匹配 | 本路线单机位、单帧，不做跨机位身份 |
| identity-assembly-v2 | 冻结整车候选后的北×南二分匹配 | 本路线不做跨机位匹配，也不使用整车候选 |
| A′ 紧贴窗口 | 多窗口检测 + 整车候选对 `same_vehicle` 去重 | 本路线不检测/跟踪整车，不按窗口数相加；几何只生成概览和远景定位图 |
| 时序/事件账本 | 多帧持续证据更新集合 | 本路线不使用过去/未来帧，不做事件记忆 |
| 固定场景拓扑 | 3×12 区域 checked/unknown 覆盖表，按区域保证不漏扫 | 概览图的 10×10 网格只是坐标定位，不按格子计数，也不把格子当物理边界 |
| 跨机位保守几何 | 只做不可达配对的负向排除 | 本路线不做跨机位几何身份；只用固定裁剪和坐标映射准备输入 |

核心新机制：

1. VLM 只枚举可定位的顶部观察（`roof_bbox`/`roof_polygon`），不是完整车辆框。
2. VLM 对顶部观察对输出 `same_top_surface`、`separate_top_units`、`composition_unknown` 或 `ambiguous`，每条都带 `junction_bbox`、`gap_px` 和顶部可见证据。
3. 本地程序只按 `same_top_surface` 求连通分量，得到顶面单元；不采用模型自报总数。
4. 若存在 `composition_unknown`（例如车头顶与货厢顶分离但仅凭顶部不能确认是否同一物理车），不强行给点计数，而是输出计数范围 `[min,max]` 并送复核；只有所有关系都确定时才输出 `count_point`。
5. 两个 cargo/open-top/trailer 顶面有清晰间隙时，可作为不同顶面单元；车头顶与货厢顶即使顶面分离，也不得直接判成两辆。

## 2. 冻结输入

输入为公共精确 aisle JPEG 的确定性派生图；原图/概览/远景图 SHA-256 均写入 `frozen_inputs.json`。模型只看到派生图，不看到真值、B 输出、用户红框或本计划文字。

| 样本 | 原 aisle SHA-256 | 概览 SHA-256 | 远景 SHA-256 |
|---|---|---|---|
| `south_2100` | `d6d067dc76bf0b7d24ca7993637c3fa88fa45a0e68aa602e98c6d7dd55ae6901` | `5546bd7eeec303fbef4b12edf9bcf006d20b66b4cc415dd367f13e63f554ba46` | `18e499e51ce8e70a007e387ef1121843cad79474688429dc8e766278a87c5639` |
| `south_300` | `058c8b76e99edd8cf5a91286aeab311c0667062053a848c79fc7cd2382ac8cb4` | `734506338ef7534c1e21d43c80bea867ab43dc3f12a3b483ceb5c77bd0b5154b` | `449f09fba811abb7fba03d0b602a45be18b683a3eb84d5d8e99e03917ce80c9c` |
| `north_5` | `80362e5b92d7d64da310ca845711e25252ea3794cb30259483f052b010cefb3f` | `0df0dfa16580476ef93babc8a3f6bb42c444d70241e9bba0f56ee2d75f6dc8f7` | `f9f434ea1f3059eda13ce651cad29bdcaaf22e767f11dfe8d09d221c91cd275b` |
| `north_600` | `e5dead0bf6d26d76456b95191b84f06bc33762889da3adcce16f75f3eee3163f` | `3a65f223ccc9fac1ee497157498c95f20fd19a221f04428ac5d8a3ce21f2168f` | `c32a266afb8339b7a5f00d019f4e3921503f04a7836b7f350d3a6e40afe6eb56` |

- 概览：1040×1920；淡色 10×10 网格和黄色远景框，仅定位。
- 远景：概览归一化 `(0.06,0.00,0.94,0.56)` 裁剪，1.6× LANCZOS，1466×1720；黄框和独立网格。
- 每次请求固定两张图，顺序概览、远景；不重裁剪、不换图、不追加裁剪。
- 提示词文件 `prompt_roof_relation.txt`，请求文本 UTF-8 SHA-256：`00a5f55a95043fd41e136cdf832f4769a627f16d46cc304ee379d78936a91745`。

## 3. 模型、思考与传输

- 模型：`doubao-seed-2-1-lite-260915`（当前模型不变）。
- `temperature=0`，`max_tokens=12000`，单轮 user message，图像在文本前。
- Doubao `thinking` 字段：本实验**不显式发送**。官方 `volcengine-python-sdk` 的 `types/shared_params/thinking.py` 只证明 SDK 字段可取 `enabled|disabled|auto`，不能证明精确 Lite 型号在这个请求形状上支持或已启用；4 次预算不允许另做字段探针。实际响应中的 `reasoning_tokens`/`reasoning_content` 会逐样本报告，并明确“未验证字段级支持”。
- 中枢已按 `ROUND2_CENTRAL_REVIEW.md` 给本会话设置 high 思考档位，模型不变；这不等于豆包请求的 thinking 配置。
- HTTP 超时：连接 20 秒、读取 300 秒。每个样本 1 次主调用；全实验最多 1 次纯传输/429/5xx 重试。JSON/schema/推理错误不重试，不追问同一图。
- 并发：1（顺序执行）。预算：4 个主调用、每调用 2 张图、最多 5 次 HTTP attempt；0 次基于答案的补检。

## 4. 预注册诊断样本（不把真值送入模型）

选择依据是 B 已存原始输出与公共用户真值的对照，只用于事后评价；模型请求中没有样本名、真值、B 计数或失败描述。

| 样本 | B r1/r2/r3 | 用户真值 | 选的诊断角色 |
|---|---:|---:|---|
| `south_2100` | 4/4/4 | 3 | B 稳定多计；旧报告称车头/挂车误拆，但 B r1 原框显示第 4 个单位是远端/背景车，需同时审计组成与计区边界 |
| `south_300` | 5/4/4 | 4 | B r1 多计；第 5 框是前景挂车右侧的 trailer-only 重复片段，检验顶面重复合并 |
| `north_5` | 5/4/3 | 5 | 远端相邻顶面；B 有运行方差，检验顶面间隙/分界能否稳定分开 |
| `north_600` | 4/4/4 | 4 | B 稳定的正确远端货厢组，作为“不要过度拆分”的保持对照 |

四个样本是开发集中反复使用的帧，不是独立测试集。每个样本只跑一次；不因计数错误或 unknown 追加请求。

## 5. 输出与本地组装

模型输出 `tops[]`、`relations[]`、`top_unit_hypotheses[]`、`scope_notes`、`unresolved`。关键约束：

- `roof_bbox` 只框可见顶面/开口轮廓，不是完整车辆框；可用 `roof_polygon`。
- 敞口货厢：`kind=open_top`、`top_state=open`，使用可见开口/顶部边缘，不推断内部或底盘。
- 不允许使用下部连接、车牌、轮胎、尾灯、车身侧面文字作为证据。
- 本地只按 `same_top_surface` 合并顶面单元；`count_max=顶面单元数`。
- `composition_unknown`/`ambiguous` 边构成不确定性图：`count_min` 为把这些边全部视为可能同车后的连通分量数；`count_max` 为全部保留为不同顶面单元的数。
- 无 `composition_unknown`/`ambiguous` 且无其他复核阻断时，才输出 `count_point=count_max`。否则 `count_point=null`，只报区间并送复核。
- `cab_roof` 与 `cargo_roof/trailer_roof` 若被模型写成 `separate_top_units`，本地保守重解释为 `composition_unknown`，并在 `schema_warnings` 留痕；不能据此多算一辆。
- 两个顶面单元 bbox IoU≥0.5 只标记 `possible_duplicate_top_units`，不自动合并。

## 6. 评价与停止条件

只在全部请求结束后读取 `accuracy/reviewed/user-final-review-v2-2026-10-21.json`。评价口径：

- 固定分母 4；有效、失败、缺失单列。
- `resolved_count` 与 `resolved_coverage`：能给出点计数的样本数/占比。
- `exact_point_count`：只对有 `count_point` 的有效样本算精确计数；分母为 resolved。
- `mae_resolved`、漏/多计：只对 resolved 样本。
- `range_contains_truth_count`：真值落入 `[count_min,count_max]` 的样本数；明确这是校准诊断，不是点计数准确率。
- 同时列 B r1/r2/r3 原始计数作参照；B 是旧整车框路线，不是同一输入口径的新机制成绩。
- 报告每次调用/HTTP attempt、输入图数、prompt/completion/reasoning token、均值/p95/总耗时、失败和解析错误。
- 不报告身份、车型、OCR、跨机位准确率；没有完整逐车顶面/关系 gold，只做定性关系审计。

停止/决策：

- 首样本若出现 400/401/403 等非传输错误，停止后续付费请求并报告配置失败；不换 prompt/模型/字段后把结果混为本实验。
- 连续 2 个样本传输失败则停止；最多 1 次传输重试。
- JSON 解析失败或 schema 失败记录为样本失败，不重问同图；其余预注册样本可继续，但总调用不超过 4。
- 不以“计数碰巧正确”宣称顶面组成、框或身份正确；不以区间覆盖真值冒充点计数提升。
- 若 4 个诊断样本中顶面单元无法稳定区分远端相邻货厢，或车头顶/货厢顶全部落入不可判定，结论为当前 roof-only 组成配置不进入自动计数，保留证据与范围输出。

## 7. 预期产物

- `frozen_inputs.json`：模型、参数、prompt/输入哈希、预算、样本角色。
- `raw/*.json`：每个样本的完整 HTTP attempts、原始响应、思考/用量、耗时、解析结果和失败。
- `metrics.json`：固定 4 分母、resolved/区间、B 对照、成本、限制。
- `viz/*_roof_overview.jpg`、`*_roof_full.jpg`、`*_roof_vs_B.jpg`、`contact_sheet.jpg`：模型原始顶面框、顶面单元颜色、接缝/间隙框和 B 对照。
- `REPORT.md`：机制、实测、失败、结论和可复现命令。
- `run_part_relation.py`：prepare/run/evaluate/viz 可运行脚本；`run` 对已存在 raw 跳过，不重复计费。

## 8. 边界

- 全图像素仍输入模型；提示限制只使用顶部证据，不等于物理屏蔽非车顶像素，也不能声称已证明模型未看下部。
- 20 帧全回归未在本轮执行；本轮最多 4 个诊断样本，不能冒充全 20 或泛化成绩。
- 顶面观察 ID 与物理车 ID 分层；同色、同尺寸、同箱号不足以自动同车。
- 用户红框、用户终审文件和旧预测不进入模型输入；只在评价阶段读取计数真值。
