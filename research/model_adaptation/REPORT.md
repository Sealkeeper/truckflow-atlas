# 固定场景模型适配 / 蒸馏：可行，但当前不启动训练

日期：2026-10-21；分支 `research/model-adaptation-v1`。这是一条改变模型参数的路线，不是事件账本重试，也不是提示词变体。**本报告所有本项目准确率、泛化、推理延迟、训练时长均为未测。新增付费模型调用 0，下载权重 0，安装包 0，训练任务 0。** 事件账本全部证据仍保留在其原分支和公共 `coord/exploration/event-ledger/`，本轮未追加该配置调用。

## 1. 中枢决策摘要

建议把“数据准备”列为 GO，把“立即训练/购买硬件”列为 NO-GO，原因是缺合规训练集、本机无 CUDA 独显、尚无训练预算或上传授权。不是认定训练无效，而是当前没有条件证明有效。

三个可执行候选中，先验证 A；在 A 达到准确率要求后才以 B 优化性能；若不自建 GPU 且同意上传训练数据，可改走 C。三者上线都可设计为**每机位图一次推理**，而非同一图反复核验。双机位唯一身份仍需单独监督和验证，不能从单图计数微调顺带声称解决。

| 候选 | 真正改变的能力 | 部署与成本边界 | 当前判定 |
|---|---|---|---|
| A：Qwen3-VL-4B-Instruct 场景 grounding + 组成语义 LoRA/SFT | 把远端独立厢体、车头/挂车组成、局部可见货车与棚顶等易混淆关系写入参数 | 自托管视觉语言模型；离线训练，在线一次生成车辆集合 | 数据准备 GO；训练暂 NO-GO |
| B：Qwen3-VL-8B 教师 → Qwen3-VL-2B 学生的离线响应蒸馏 | 由较大教师给训练图出草稿，人工改正后训练小模型；生产不调用教师 | 教师生成成本只在离线发生，学生在线一次推理；精度回退则淘汰 | A 未达标前不优先；不是免费准确率 |
| C：方舟 Seed-2.0-mini/lite 260428 托管视觉 SFT/LoRA | 直接形成任务定制参数产物，不是只开一个会话 | 本机不需训练 GPU，但需账号训练权限、数据上传许可和付费预算 | 产品能力有官方依据；本账号可用性未证实 |

## 2. 可用性、许可证与官方一手证据

### A：开源 LoRA/SFT

Qwen 官方训练框架提供 SFT、LoRA，以及 LLM/视觉编码器/projector 的可训练开关；训练记录可为 JSON/JSONL，含图像路径和 `human/gpt` conversations，支持多图、视频及 grounding 监督。不是“有推理 API 所以猜测能微调”。[官方训练框架](https://github.com/QwenLM/Qwen3-VL/blob/main/qwen-vl-finetune/README.md)

Qwen3 官方评测代码把 `bbox_2d` 的 0–1000 相对坐标还原到原图像素；本原型明确使用这一坐标约定。不能直接照搬 Qwen2.5-VL 的 resize 后绝对坐标：旧格式与新模型混用会把监督框教错。[官方坐标转换代码](https://github.com/QwenLM/Qwen3-VL/blob/main/evaluation/ODinW-13/run_odinw.py)

4B、2B、8B 的模型卡及公开元数据均标注 Apache-2.0；代码仓库也为 Apache-2.0。适配/部署应保留许可证和署名义务；这不覆盖业务视频、人工标注或第三方 API 输出的训练权。[4B 模型卡](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)、[2B 模型卡](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)、[8B 模型卡](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)、[代码许可证](https://github.com/QwenLM/Qwen3-VL/blob/main/LICENSE)

本次仅通过公开模型元数据读取 revision，未下载 tensor；精确版本见 `sources.json`。A 首轮建议仅训练语言侧 LoRA、保留视觉和 projector 冻结作为可解释起点；如果错误源是图像分辨率/视觉表征，语言侧适配不一定解决。之后可以做 projector/视觉高层解冻消融，但需更多数据与资源，不能把“LoRA 能训练”写成“必然提高召回”。

### B：小模型响应蒸馏

采用开源 8B 教师在**训练专用原图**上给结构化草稿，人工逐车增删改框、修正组成、类型与可见性，再把纠正后的最终 JSON 用同一官方 SFT 框架训练 2B 学生。这里是离线 response distillation，不声称已有跨模型 logits 蒸馏或在线强化学习实现。参数确实更新，生产只部署学生，教师不进入每图重复核验环路。教师、学生的具体 checkpoint 和权利来源单列，不能拿已存在的 Doubao raw 响应默认当可训练数据。[官方 2B 模型](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)、[官方 8B 模型](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)

教师只能给草稿：同模型漏车、框重叠、总数碰巧正确都不能自动成为金标准。保留 teacher 原响应和人工修订差异；不得让教师或学生看盲测答案，也不能由教师自己确认自己的伪标签。小模型更便宜/更快只是待测假设，不用参数量替代性能实测。

### C：托管视觉精调

方舟 2026-10-17 更新的精调概述列出 `doubao-seed-2-0-mini/lite` 260428 支持文本、图片及 SFT/LoRA，最终以控制台可选项为准；官方建议 SFT 积累数百条样本。列出的 LoRA 按 token 推理为基模的 2 倍价格，所以**精调并不自动省钱**。[方舟精调概述](https://console.volcengine.com/ark/region:cn-beijing/docs/fine-tuning-overview)

官方多模态格式索引示例为一行一个 `messages` JSON，user content 混排 text/image_url，assistant 为目标文本；图像引用有 base64 或打包本地文件形式。该动态页面未完整渲染，因此未实现或验证 Ark 导出/上传，必须在获授权后用所选模型完整规范校验，不拿图片生成模型的格式冒充视觉理解格式。[语言及多模态理解精调格式](https://docs.volcengine.com/docs/ark/multimodal-fine-tuning-data-format?lang=zh)

已有 endpoint `ep-20260828174616-dthpx` 不能据 ID 推断底层基模或可微调。当前 Aibox `deepseek-v4.1-flash`、`glm-5.3-flash` 可用于智能体工作，也不构成其视觉输入、训练接口、权重访问或训练许可的证据。本轮未读取密钥、未查询私有账号、更未创建训练任务。

### 额外核查但不优先：InternVL

官方 InternVL3.0 文档有 SFT/LoRA 和 JSONL grounding 格式，2×32/40GB 为示例配置，不是绝对最低配置；不能把它迁移为 InternVL3.5 已验证的训练方案。InternVL3-2B 模型卡头部 Apache-2.0 与正文项目 MIT、组件 Apache-2.0 存在表述差异，精确 LICENSE 文件地址又返回 404，因此首轮不选它，待固定 checkpoint 的许可义务厘清再用。[训练指南](https://internvl.readthedocs.io/en/latest/internvl3.0/finetune.html)、[grounding 数据格式](https://internvl.readthedocs.io/en/latest/get_started/chat_data_format.html)、[模型卡](https://huggingface.co/OpenGVLab/InternVL3-2B)

## 3. 本机资源与最低条件

只读硬件检查：Core Ultra 5 125H（14 核/18 线程）、物理内存 33,945,935,872 字节，约 31.6 GiB；只观察到 Intel Arc 集显和虚拟显示设备，`nvidia-smi` 不存在。D 盘当时约 257 GB 可用。Win32 报告的集显 AdapterRAM 数值**不是已验证训练显存**，不能把共享内存当作 CUDA VRAM。见 `hardware.json`。

因此当前笔记本适合抽帧、人工复核、数据检验和小规模 CPU 工具，不具备官方 CUDA/FlashAttention/DeepSpeed 训练路线的即用条件。不能说 CPU/Intel 后端理论上完全不可能；只是本项目未安装、未验证该训练后端，性能优先级下不作为本轮可执行训练环境。

- 硬下界而非可运行保证：N 参数 BF16 权重约 `2N` 字节，4B 约 8 GB、2B 约 4 GB、8B 教师约 16 GB；还没包括视觉模块实际参数、激活、KV cache、梯度、优化器、运行库等。LoRA 降低可训练参数，不会让整个基模和图像激活消失。
- 全量训练还需梯度和优化器状态，不能按“4 GB 学生权重”估算全部训练显存。量化可改变下界，但 QLoRA 的具体视觉模块/后端兼容性本轮未验证，不承诺随便一张低显存卡就能训。
- A 的**资源申请候选**：Linux/CUDA 环境、单卡 48 GiB、主机 RAM 64 GiB、保留原始 1280×960 输入和 batch=1 的一次显存 dry-run。此为保守规划起点，不是官方 4B 最低配置或已测能跑保证；先测峰值再定长期采购。
- B 的学生可复用 A 训练环境，教师单独离线跑；不能为省资源把远端车图像缩到不可辨。C 无本地 GPU 门槛，但有平台训练/推理库存、计费、账号权限和数据出域约束。
- 本轮未启动 dry-run，因为它仍需要下载权重、环境安装与 GPU。具体卡型、GPU 小时和租用报价必须由用户决定后再验证，未擅自租用。

## 4. 现有数据究竟能监督什么

统一约定保留的 20 机位计数图是反复使用的开发回归集，不是独立验收。9 张用户红框图覆盖 6 时刻，公开 `review/user-attachments-20261021/manifest.json` 记录了上传来源、尺寸、SHA-256 和人工车辆数；没有完整的原图框坐标、类型、逐车跨机位/跨时刻 ID 或截图到原图的几何映射。截图尺寸不同于原视频，不能直接线性猜框。

| 数据 | 当前允许派生 | 不能凭空派生 |
|---|---|---|
| 20 机位人工数量 | 开发回归计数指标、错误类型清单 | 每辆 bbox、车型、对应身份、事件标签 |
| 9 张红框图 | 保留用户计数与可见独立对象证据；可人工转录“待验证”的截图框，用于解释/复核 | 把红框图作为识别输入；假装已获原图精确框；由红框颜色猜车型/ID |
| 对应原视频 | 经授权提取未标注原帧、记录来源/帧号/同步偏移；新时段可进入待标队列 | 相邻帧复制框/计数/ID 当人工真值；完全遮挡车辆的“当前可见”框 |
| AI raw/教师草稿 | 主动选样和需人工校验的建议 | 未确认训练权即导入；伪标签自评为金标准 |

**当前 9 红框图按契约仅评估/解释，训练导出器拒绝它们。** 如果以后用户明确决定退役这套回归、重新划归训练，需另立数据版本和实验契约；使用相应无红框原帧并人工确认映射/逐车标签，所有邻近片段和派生裁剪同样退出盲测。本原型故意没有“强行允许旧测试集训练”开关。新框标签的最小可靠做法是让用户在原帧上标，保留红框图作来源证据。放大、裁剪和 JPEG 变化不会把 9 张相关图变成独立训练样本。

## 5. 数据与标注设计：先隔离，再标注和训练

### 原子分组与防泄漏

1. 按真实同步拍摄 session/日期先分组，同一时刻南北图、原图与裁剪/增强必须同一 split。优先用不同日期/独立记录分别作 train、dev、blind；仅有同一小时视频时只能声明“该视频内”验证，泛化证据弱。
2. 在 session 内以完整车辆出现/消失的占用 episode 划时间块，不随机逐帧切分。每例记录覆盖的 `context_start_s/end_s`；任何时序上下文、裁剪来源、教师输入均纳入块边界。
3. 起始可设 60 秒跨 split 缓冲，但这不是独立性保证。长时间停放同一辆车可能跨数十分钟：通过人工 vehicle_session_id、近重复图簇和来源派生根进行传递合并；一个连通组必须整体同 split，不能切几分钟后换标签绕过隔离。若合并后只剩一个组，就需要新视频，不能硬凑三份数据。
4. SHA-256 只抓精确重复；近重复分组另做受控图像审计，低分辨率感知哈希只能召回可疑对，不能决定车辆身份。导出器要求 `near_duplicate_audited=true` 和组号，但无法验证填写者是否诚实，必须保留审计记录。
5. 盲测在采样/标注后封存，开发智能体与教师不看图、不看答案；训练 loader 只获 train，选 epoch/阈值只用 dev。基模和微调模型在同一新盲测一次对照，开盲后若再改模型，该集降为回归并重新采集盲测。

### 标签粒度

- 单帧全对象：每辆当前可见、可确认货车的原图 bbox（说明框住可见区域还是整体范围，统一口径）、局部 observation_id、可见性、货车确认、组成关系、人工可见证据；全图完整性标记，不能只框“容易的车”。货车未知/不可确认区域要单独记录，不造确定标签。
- 类型：large/medium/small/unknown、判断证据及人工确认；不能按框像素大小直接定车型。未确认就 unknown，不拿计数标签补类型标签。
- 身份：vehicle_session_id 及 tractor/trailer/cargo 部件关系；跨机位 same/different/unknown 配对、实际时间偏移和证据；跨时刻可见、遮挡、重现和进入/离开事件。不能由同色、近距离或数量相等伪造配对。永久车牌身份非必需，视频会话内身份即可，但要能回滚。
- 标注流程：两名独立人员看原帧/短片，分歧另行裁决，保留版本、标注者和时间；当前用户红框提供重要依据，但不伪造第二标注者。本轮代码里的 reviewer 名称均为**合成测试字符串**，不是现实人员或真标签。

### 数量与最小下一步

不存在能保证完全准确的“最低张数”。建议先做**新选 20 个同步时刻（40 原帧）**的小批标注/格式试点，只验流程和标签一致性，不启动训练、不报告新准确率。时间块与车型/遮挡/远端/边界样本清单需在标注前冻结。

若标签可重复且分组足够，再申请一个可增量的试验规模，例如 train 300 帧、dev 100 帧、blind 200 帧（每组同步机位、独立 episode，不含旧20帧）；这是人力/算力规划数，不是统计充分性或模型要求。先用同一协议跑未微调基模，再做 A；B 必须与学生未蒸馏版和 A 对照，不能只对大教师讲速度。

## 6. 不训练的可运行交付

`dataset_gate.py` 是离线数据门禁与 Qwen JSONL 导出原型：没有网络调用、模型加载或训练代码。输入一行一个 canonical 样本，至少含：

```text
sample_id, split(train/dev/blind/regression), capture_session_id, camera,
time_block, context_start_s/end_s, near_duplicate_group, near_duplicate_audited,
derivation_root(若有), image, image_kind=raw_unannotated, sha256, width, height,
source_set, training_rights_confirmed, evaluation_only, label_source,
review_status, reviewers, all_visible_trucks_labeled, count, vehicles[]
vehicles: observation_id, bbox_px, type, type_human_confirmed(已知车型必需),
          visibility(full/partial), evidence, vehicle_session_id
```

教师修订样本还需 `teacher_output_training_rights_confirmed=true`。只允许 human 或 teacher_human_corrected 标签，拒绝 teacher_only。拒绝跨 split 的同 SHA、近重复组、派生根、时间块、车辆组和时间缓冲冲突；拒绝红框/生成输入、未确认类型、框越界/退化、漏标完整性、数目/对象清单不符和旧回归集训练。所有 split 共同审计，但**只导出 train/dev，永不导出 blind/regression 到训练目录**。

默认仅检查元数据；显式导出时对 manifest 指定图逐个检查 media-root 边界、文件 SHA 和真实图像尺寸。不会扫描目录；无法凭代码证明图片真的没画框、人工审计真的发生或物理身份正确。检查通过只代表数据结构/声明符合规则，不是准确率。

```powershell
python research/model_adaptation/test_dataset_gate.py
python research/model_adaptation/dataset_gate.py canonical.jsonl
# 仅在获得真实、审定的新训练标签后，生成一个尚不存在的目录：
python research/model_adaptation/dataset_gate.py canonical.jsonl --media-root D:/authorized/raw --export-dir D:/authorized/new-export
```

真实数据验证/导出用到现有 Pillow，只读精确指定图片；13项合成测试全部通过，无需模型、GPU或付费接口。本轮未导出任何真实训练样本。

## 7. 准确率优先的 go/no-go 门槛与成本

训练前：需要数据权确认、独立 train/dev/blind 分组、两人标签审计、可用训练环境和明确预算。任何一项缺失，都不启动训练。本轮这些生产条件尚未满足，不是训练效果负面结论。

A 的首轮对照冻结同一输入像素/模型 revision/输出协议/自动覆盖：未微调 4B vs 4B-LoRA，仅在 dev 选 checkpoint；最终盲测报机位计数 exact/MAE/漏多计、对象召回与误报、类型/身份有真值才测、唯一数、误放行、覆盖和复核。训练 loss 降低、JSON 合法、开发20帧全对都不能替代独立验收。

B 只有在**同一自动覆盖下无新增识别错误**，并经相同盲测支持准确率目标后，才比较速度/成本；小模型若漏远端、类型或身份退化就 NO-GO。项目目标仍是验收集完全准确，但有限样本零错也不能宣称任意视频100%。

离线成本分别计：抽帧/标注工时、教师请求/图数/token（B）、训练GPU小时/峰值显存/失败重跑、模型存储、数据上传与服务部署。自托管每次生成不收第三方 token 费，不等于零成本：`总成本 = 标注 + 教师生成 + 训练/失败 + 在线GPU小时 + 存储运维`；摊到长期正确自动处理帧再比较，低流量下闲置GPU可能比API贵。

在线固定记录每机位一次推理的图数、视觉/输出token、分辨率、batch/并发、冷启动与暖态均值/p95、峰值RAM/VRAM、拒答/失败、人工升级率。唯一数若还需双机位另一次调用必须单列，不能只报单图成本。适配后的短JSON可能更快只是待测；LoRA模型的托管token价可能更高，不能凭“少了提示词”承诺费用下降。

## 8. 需要用户具体决定的事项

1. **数据使用范围**：是否允许用另选视频时段作训练，是否能提供新日期/新记录作盲测？现有9红框图保持评估，不建议消耗它们充当训练；如要改用途需显式退役旧回归并重建评估契约。
2. **逐车标签人力**：能否先做20个新同步时刻的框/车型未知/身份关系试点，并指定第二独立标注者或裁决人？不能虚构第二复核者。
3. **训练位置和费用上限**：选A/B的自有CUDA设备或经批准GPU租用，还是C的托管精调？请给一次试验GPU小时/金额硬上限；当前未购买、未租用、未下载。
4. **出域与权限**：若选C，是否同意原帧和标签上传方舟、账号是否有mini/lite相应精调/推理权限、允许的数据地域/保留规则？当前推理密钥不代替这些批准。

即使尚未决定 GPU，本路线仍可推进：先冻结采样与标注规范，用数据门禁检查新标签。待上述选择明确再申请最小下载与 dry-run，而不是现在花钱训练20张反复见过的截图。
