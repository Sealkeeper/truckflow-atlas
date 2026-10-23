# 多模态模型实测结果（2026-10-23）

本页回答三件事：**现在最好的成绩是多少、用什么方案拿到的、为什么选这个模型。**

口径：`DEV_ONLY / 未盲测 / 开发集`。这些数字不是正式基线，也不是泛化结论。
正式基线仍是数量 10/15、身份 1/15，B-1 未测；本页不改变它们。

## 1. 当前最好成绩

单一模型、完整 15 个时刻、固定分母，没有缺失时刻：

| 指标 | 结果 | 比例 |
| --- | --- | ---: |
| 数量全对率（南/北/重合三项同时对） | **12 / 15** | 80.0% |
| 重叠身份全对率（pair 集合完全一致） | **11 / 15** | 73.3% |

- 模型：`doubao-seed-2-0-lite-260428`
- 口径标签：`CROSS_ROUND_SAME_PROTOCOL_HASH_VERIFIED`
- 合并说明：11 个时刻来自上一轮 v2 运行，4 个尾时刻（`t1800/t2100/t2400/t2600`）来自本轮实测；
  两次模型相同、prompt/schema/四图顺序/源 ticket 哈希一致，才允许合并。**不是单批运行**。
- 与上一轮同模型 11 时刻口径相比：数量 9/15 → 12/15，身份 8/15 → 11/15。

### 失败时刻

| 时刻 | 数量 | 身份 | 具体错在哪 |
| --- | --- | --- | --- |
| `t0005` | FAIL | FAIL | 多判一对 `sV3–nV5` |
| `t1113` | FAIL | FAIL | `nV3` 没有形成一对一映射 |
| `t1500` | PASS | FAIL | 漏 `sV1–nV1`，错配成 `sV4–nV1` |
| `t2600` | FAIL | FAIL | 漏 `sV3–nV2`（该时刻真实重叠为 2 辆） |

`t2600` 是四个新测尾时刻里唯一失败的：真实重叠 2 辆时模型只认了 1 对。
这类"重叠数 ≥ 2 时漏配"是目前最集中的身份错误形态，不是计数误差。

## 2. 方案：实例对协议（Q198 v2）

核心取舍是**让模型只做关系判断，不让它生成坐标**。坐标错误、框越界、重复框这些
历史失败模式因此在协议层被排除，而不是靠后处理补救。

1. **计数与实例根由代码生成**：用冻结 raw 与非学习型几何，得到每个时刻南/北各自的实例
   （`S01…`、`N01…`）和数量；模型不输出 bbox、不重新数车。
2. **每个请求固定 4 张图，顺序固定**：
   `south_contact_sheet → south_panorama → north_contact_sheet → north_panorama`。
3. **候选对是当刻南×北的完整笛卡尔积**，不是模型自行挑选；四个尾时刻共 33 对。
4. **模型只回答 `same / different / unknown` 并给证据串**，同一对不能重复、
   `same` 必须一对一。
5. **契约硬校验**：JSON schema 严格、pair 集合与候选集完全相等、crop 文件存在且 SHA 命中、
   `visible_area=1.0`、无退化框、无越界框。任一不满足即整包 FAIL，不猜坐标、不补 pair。
6. **评分口径固定**：数量 15、身份 15。缺失、超时、合同失败一律记失败，
   不缩小分母。

实时链路仍然**不使用 YOLO 类检测器**；离线教师/蒸馏属于研究路径，与本页成绩无关。

## 3. 模型选型

同一个 key、同一套协议下逐个实测，结论只针对"四图实例对"这个任务，不代表模型的其他能力。

| 模型 | 裁决 | 依据 | 用量 / 延迟 |
| --- | --- | --- | --- |
| `doubao-seed-2-0-lite-260428` | **选用** | 4/4 HTTP 200 且合同通过 | 31,639 tokens；33.5–54.6 s/次 |
| `doubao-seed-2-1-pro-260915` | 仅离线备用（太慢） | 300 s 超时；600 s 救援在 377.7 s 返回合同通过 | 16,662 tokens/次 |
| `doubao-seed-2-1-turbo-260628` | 不可用 | 300 s 与 600 s 两次读超时，均无响应 | 0 有效输出 |
| `deepseek-v4-1-flash-economy-261017` | 不可用 | 4/4 HTTP 200，但 completion 2,500 全被 reasoning 占满，正文为空 | 22,140 tokens，0 可用 |
| `deepseek-v4-1-flash-261017` | 不可用 | 2,500 与 6,000 两次都被 reasoning 吃满，正文为空 | 22,140 + 9,043 tokens，0 可用 |
| `doubao-seed-2-0-mini-260428` | 额度阻断 | 429 `SetLimitExceeded`（模型体验限额） | 未产生输出 |
| `doubao-seed-2-1-lite-260915` | 额度阻断 | 429 `SetLimitExceeded`（模型体验限额） | 未产生输出 |
| `doubao-seed-2-0-pro-260215` | 无端点 | 404 `InvalidEndpointOrModel.NotFound` | 未产生输出 |
| `doubao-seed-2-0-code-preview-260215` / `doubao-seed-character-260628` / `glm-5-3-flash-260828` | 未测 | 无可靠价格上界，按预算规则不发请求 | — |

选型结论：

- **生产候选只有 lite**：它是唯一在同一协议下稳定产出合法合同结果的模型。
- **pro 不能进实时链路**：单次约 6.3 分钟、16,662 tokens，只能做离线批处理或疑难复核。
- **turbo 不是"慢一点"**：300 s 和 600 s 窗口都不返回。
- **两个 DeepSeek 的 200 不等于可用**：可见正文为空，输出预算全被推理占用；
  它们的 prompt tokens（约 3.0k）明显低于豆包（约 5.8k），图像是否真正被摄入尚待验证，
  本页只把它列为待验证假设，不当结论。
- **key 本身没有欠费或鉴权失败**，账户级封锁与全局中止均未触发；被阻断的是两个模型的
  体验限额。当前不需要换 key；若后续 lite 也出现 429 或额度耗尽，再换。

## 4. 用量与费用

| 阶段 | 请求 | tokens | 按费率推算费用 |
| --- | ---: | ---: | ---: |
| 能力探针（8 个候选） | 8 次尝试 / 5 完成 | 6,797 | ¥0.033246 |
| 四尾主矩阵（5 模型 × 4 时刻） | 14 次尝试 / 12 次 200 | 82,716 | ¥0.353491 |
| 救援实验（t1800，3 个模型） | 3 次 | 25,705 | ¥0.413498 |
| 合计 | 25 次尝试 / 19 完成 | 108,421 | ¥0.766989 |

provider 未返回账单，以上费用全部是**按官方费率与实测 usage 推算**，不是实付账单。
本轮上限为 64 次请求 / 500,000 tokens / ¥20，均未触及；两次超时请求的 usage 未知，
仍按 16,384 tokens 挂账，没有记成 0。

## 5. 明确未达标

- 数量 12/15，不是 100%。
- 身份 11/15，不是 100%。
- 性能联合门：**FAIL / INCOMPARABLE**。凑不出两个模型的完整 15 时刻同协议结果，
  也没有同硬件、同并发的完整链路 A/B，因此不给 3× 吞吐或 tokens/帧减半的结论。
  4/15 的部分覆盖率不足以外推 tokens/帧。

下一步优先级：`t2600` 这类"重叠 ≥2 漏配"、`t0005` 多配、`t1113` 端点未映射，
都是关系层能否加集合约束/竞争消解的问题，而不是调 prompt 能解决的。

## 6. 证据与复现

全部原始响应、请求哈希、usage、延迟与账本在仓库内：

- 评测卡：`coord/optimization-20261022/sprint-20261023-multimodel/evaluation/scorecard-multimodel.json`
- 评分报告：`coord/optimization-20261022/sprint-20261023-multimodel/evaluation/REPORT.md`
- 四尾矩阵：`coord/optimization-20261022/sprint-20261023-multimodel/vision/tail-matrix.json`
- 救援矩阵：`coord/optimization-20261022/sprint-20261023-multimodel/vision/q198-rescue-matrix.json`
- 账本：`coord/optimization-20261022/sprint-20261023-multimodel/vision/ledger.json`
- 模型可用性：`coord/optimization-20261022/sprint-20261023-multimodel/vision/availability.json`
- 协议与映射：`coord/optimization-20261022/sprint-20261023-multimodel/instance-pair-vision/`
- 原始响应：`coord/optimization-20261022/sprint-20261023-multimodel/vision/q198-responses/`

关键封条（sha256，提交时点）：

| 对象 | SHA-256 |
| --- | --- |
| `evaluation/scorecard-multimodel.json` | `191E98832B0DC24DBB50D028C88CFC85F8214C27EAAA3850EF8B73051F6C2581` |
| `vision/tail-matrix.json` | `985A0D94C50C5BD85A0F8CFFDB5D8735B9B908AA1B108B0C1985E06CAB96F48E` |
| `vision/q198-rescue-matrix.json` | `B1C96B7D2DEDFCBB3977844BE23618FF586661F22505B3B80328B99748656C23` |
| `vision/ledger.json` | `E57842EA446DC5B5CD1C82E0C150FE5D752B0612883F45F9F04BE663606F98C3` |
| `vision/availability.json` | `BE7759A2932AB4FAD19D019ABEF44114619FD60FC4E92A71071AE2E1DAA9A493` |
| Q198 `READY.json`（修复后） | `44F8E6745ECEDD313C754C7E942944A39502332DD77A74E6E4ABC3AD1ABBF78F` |
| Q198 `ticket.json` | `DB2AE5BDEF724E0A0EDDF5AED341140694CFEC867E630C6645307ED5C45396E6` |

机器可读版本：[`2026-10-23-multimodel.json`](./2026-10-23-multimodel.json)。

## 7. 证据级复核层（`DEV_ONLY_POSTHOC_EVIDENCE_V4`）

在 §1 的单轮基线之上加了一层证据复核：只对候选对存在竞争的时刻追加一次请求，模型按线索族给出
`same/different/abstain` 与冲突线索；只有「至少两个独立线索族一致、无冲突线索、且接受边构成合法一对一」
才覆盖基线，否则整格回退。规则先冻结、后看结果。

| 口径 | 数量 | 重叠身份 | 正重叠身份 |
| --- | ---: | ---: | ---: |
| 证据复核后合并（基座=基线） | **14 / 15** | **13 / 15** | 12 / 14 |
| 同上，基座换成 v3 预测（对照） | 14 / 15 | 13 / 15 | 12 / 14 |
| 单轮基线（无复核） | 12 / 15 | 11 / 15 | 10 / 14 |

覆盖与实际结果：

| 时刻 | 来源 | 状态 | 说明 |
| --- | --- | --- | --- |
| `t0005` | 复核 | 覆盖 | 数量转对，身份仍错（多留一条错边） |
| `t0177` | 复核 | 回退 | 没有满足「两族一致」的边，按规则保留基线 |
| `t0470` | 复核 | 覆盖 | 与基线一致 |
| `t1113` | 复核 | 覆盖 | 首次传输失败（0 字节），重发一次后合同通过 |
| `t2600` | 复核 | 覆盖 | 修好「重叠≥2 漏配」 |
| `t1500` | 复核（gold-informed 补格） | 覆盖 | **反向**：把原本正确的数量判错 |
| `t1200` / `t1800` | 未跑 | 回退 | 按基线保留 |

必须一起读的三条：

1. 这是**开发集、事后合并**口径，标签 `DEV_ONLY_POSTHOC_EVIDENCE_V4`；不是盲测，不是 100%，也不能当作可外推的泛化成绩。
2. `t1500` 是按已知失败点事后补的一格（`SELECTION_PARTIALLY_GOLD_INFORMED`），不是无信息的选择规则；把它算进来后数量从 15 掉到 14，说明证据层会反向伤害计数。
3. 证据层没有解决「外观接近的两辆车」判别，只是把部分时刻的判错换成判对；这条能力边界比分数更重要。

证据与封条：

- 评分结果：`coord/optimization-20261022/sprint-20261023-2100/fusion-v4-scoring/fusion-v4-scoring-results.json`（`1F966BA87BC3FB4AAE055AA49447ADFA9A50E722A887AA052C2C58A7BCA2BEB0`）
- 评分器：`.../fusion-v4-scoring/score_fusion_v4.py`、`REPORT-fusion-v4-scoring.md`、`validation-fusion-v4-scoring.json`
- 复核包：`.../instance-fusion-v4/`（5 时刻）与 `.../instance-fusion-v4b/`（3 时刻，仅 `t1500` 实跑）；两包 `validation.json` 均 PASS（revision=2）
- 执行器：`.../vision/run_evidence_v4.py`（`0CB9EB0A363C3C7675556298C3FA945F83F9F0E28D8B8699AE23317FDBAB3202`）
- 红队 GO：`.../redteam/Q195_FUSION_GO.json`（`1A13568A64BDDAA34632E9472B1AD8DA803DF4C9A035DB3D6F8D6225FC851B8A`）
