# Round 2 独立评测：冻结计划

冻结时间：2026-10-21（北京时间）。负责：`round2_evaluator`。

**2026-10-21 用户转向只识别车顶。** 新口径的冻结修订见
`ROOF_ONLY_AMENDMENT.md`；旧整车记录保留为独立的 legacy 对照，禁止覆盖或混算。

## 目标与边界

建立只读、可复现的离线评测器，独立复算已有单遍 B 三轮结果，并为
`doubao-v2-benchmark`、`identity-assembly-v2`、`part-relation-v2`、
`causal-memory-v2` 及后续独立人审输出提供显式 adapter。准确率第一，性能第二；
不把机位计数正确升级为框、实例集合、配对或身份正确。

本轮固定 **0 次模型调用、0 次数据底座写入、0 次真值修改、0 次其他路线写入**。
不读其他会话的 `sessions/` 目录或上下文，不修改主 UI，不执行旧 endpoint。

## 冻结来源

| 内容 | 路径 | SHA-256 / 约束 |
|---|---|---|
| 开发集真值 | `accuracy/reviewed/user-final-review-v2-2026-10-21.json` | 工作区字节 `c3fddc439da1574e74a6ceb7391297e1c65fedec109d3579da05cad05f34149d`；标签内容 canonical `78f255b1ae37463e2b36e15befb1ff8092ca87c2c6e946979d880f42cf0e5397`。字节 hash 与 Git/LF 序列化 hash 不混用。 |
| B 输入清单 | `coord/exploration/single-pass/INPUTS.json` | `e8775b0acaa1ee809c90517f5383f5065df5652f15f9709753ce24cfb9726e79` |
| 公共 aisle 图 | `coord/exploration/single-pass/inputs/aisle/*.jpg` | 20/20 实际 SHA-256 与 `INPUTS.json.samples[].aisle_sha256` 一致 |
| 冻结 prompt | `coord/exploration/single-pass/prompt_aisle.txt` | `52352ddb245a9bd98c20f5ca71e301d9aca5569366375635a130c42487baf2ab` |
| B 原始输出 | `coord/exploration/single-pass/raw/B_aisle/{r1,r2,r3}/*.json` | 每轮恰 20 个唯一 sample，保留原文件，不覆盖 |
| B manifest / index / attempts | `single-pass/RAW_MANIFEST.json`、`RUNS_INDEX.json`、`ATTEMPTS.json` | 分别 `bbb9c533…06f153`、`a42ef83b…a64628c`、`ba7496b8…29470f` |
| 用户逐车红框 | `review/user-attachments-20261021/` | 只作评估/解释；禁止进入模型输入、训练或检索记忆 |

固定开发分母：**20 个机位样本 = 10 时刻 × 南北**；unique / overlap 分母：**10 个时刻**。
同一 20 帧的三轮是重复运行，不得写成 60 个独立样本。

## 评测机制

1. **真值 adapter**：只接受显式 `--truth`。机位 count、overlap、unique 分别带完整性；
   缺失标签保持 `null`/`missing`，绝不以 0 或预测值回填。区分开发集和独立集。
2. **输出 adapter**：按显式 adapter 名称及坐标空间转换；原始框必须标注
   `aisle_norm_0_1`、`aisle_int_0_1000`、`full_pixel_1280x960` 等尺度。禁止猜尺度后
   静默修复，禁止用人工框回填。B 顶层 0–1 框与 `calls[].parsed` 混合尺度分别审计。
3. **唯一键与冲突**：重复 `sample_id`、重复 `(time,camera)`、重复实例 `id`、重复
   `(north_id,south_id)` 均报错并停止该文件计分；不允许最后一个结果覆盖。
4. **分母状态**：每个期望样本必须落入 `valid`、`failed`、`refused`、`missing` 之一。
   headline 恒用固定分母；MAE 只在 `valid` 上计算并单列 `valid_N`、失败、拒答、缺失。
5. **计数一致性**：报告 `reported_count`、顶层实例列表长度、parsed 实例列表长度，
   不一致列错误。相等只证明内部一致，不证明视觉框正确。
6. **独立指标**：机位 count exact/MAE/漏多单位与帧数；跨机位 overlap/unique
   exact/MAE；unique 不合法或标签缺失时不计算。重合数、唯一数、机位计数不互相代填。
7. **自动放行**：只有显式 `release_decision` 才计放行；报告放行数、其中计数正确/
   错误、覆盖率、复核率、拒答率。模型 `confidence`、`visibility=full`、自报
   `checked`、`possible_miss=false` 都不是可靠正确门禁，不用于证明自动放行安全。
8. **对象级指标**：没有逐车完整人工 gold 时，bbox、实例集合、车型、OCR、跨机位/
   跨时刻身份一律 `not measured`；不得给出 IoU、precision、recall、IDF1 或“提升”。
9. **性能**：分别报告离线初始化（含历史候选/B 输入与建库）和当前在线成本：
   calls、images、tokens、总墙钟、均值与 nearest-rank p95、并发、峰值内存。
   历史初始化不伪装成在线成本，但验收表同时给两部分与合计。
10. **输入证据**：输入图与声明 hash 不一致即不合格；prompt hash、模型 ID、
    输入顺序、view/run 必须显式冻结。未公开请求文件不能从其他 session 补读。

## 可证反例

- `south_2100` B r3：声明白车/“东风商用车”的记录框最大 `y2=0.45`，全部四个实例框都在
  画面上半部；前景白车主体未被这些框覆盖。该例证明“总数为 4”不证明对象—框—属性绑定。
  计数真值为 3，三 run 均报 4，另行作为稳定多计。
- `north_600` B r1：第 4 个远端独立车体标为黑色顶，但现有精确输入和用户标记支持浅蓝/
  紫灰顶；“总数 4 正确”不证明该颜色/属性已被核实。无颜色 gold，不计算颜色正确率。
- `north_600` 三 run 把同一 `JT62649` 写到两个不同货厢；较近货厢未见独立可读支持。
  这只能证明 OCR 来源/身份风险，不能宣布两个 OCR 都错，也不能以重复字符串作唯一键。
- `north_5` 三 run 为 5/4/3；r1 总数正确不等于三次稳定。不得只报 r1。

机器可检查的反例仅限字段与几何矛盾（如重复 ID、框越界、数量不一致、公式不一致）；
语义反例继续引用公共原图、原框和人工评估材料，不自动改框或猜标签。

## 全工作流接受条件

候选通过“机制实验验收”必须同时满足：

1. 固定分母完整；无重复 ID；无静默覆盖；所有输入 hash 与冻结清单一致。
2. 计数、实例列表长度、unique = N + S - overlap 等内部公式一致；坐标尺度已声明。
3. 真值、预测、失败、拒答、缺失完全分离；不允许“有效数分母”美化 headline。
4. 开发集机位 exact 不低于当前正式基线 16/20；unique/overlap 在 10 时刻有完整有效结果；
   与 overlap=0 对照有可复现净收益。若机位低于 B，不得仅凭 unique 提升进入主链路。
5. 自动放行对用户真值 **0 个计数错误**；任何误放行即禁止自动生产。高复核率或拒答率
   不算识别正确。
6. 全工作流审计通过：用户红框/答案未进模型或检索记忆；无未来帧；无无证据的数量续填；
   历史记忆仅用过去观察；失败未跳过。
7. 身份/框/属性只有在独立、完整且符合标签规范的 gold 到位后才可验收；计数对不替代。
8. 独立新时段标签未到位时，只能报“开发集回归”，泛化状态必须为 `not evaluated`。

任何硬门禁失败即 `REJECT_FOR_NOW`，即使 headline 更高；只有实验证据充分而生产门禁
未完成时标 `RESEARCH_ONLY`，不得称已上线或已泛化。

## 预算、停止与复现

- 模型/API：0 次，0 token，0 新图像调用。
- 计算：仅本地 CPU 读取公开 JSON/JPG、SHA-256、算术与测试；单次全量复算目标 < 60 秒。
- 新路线输出未到位：状态写 `awaiting_public_artifacts`，不重复同图调用、不向其他会话追问。
- 独立新时刻只有人审页/未完成标签：写 `labels_pending`，准备 adapter 与字段检查，
  不抽取新帧、不猜时序。
- 现有 B 三轮复算若与公共 summary 不一致：以原始文件独立结果为审计事实，列出差异，
  不改原报告与其他路线文件。
- 新路线产物到位后追加 adapter 与统一复算；同一路线改 prompt/输入/模型需新 run ID，
  不得覆盖旧 run 或混算。

所有脚本、测试、机器结果、差异清单和简明验收表发布在本目录；代码在
`sessions/round2_evaluator/`。只做精确路径提交，禁止 `git add .`，不触碰共享源码中
已有的未提交修改。
