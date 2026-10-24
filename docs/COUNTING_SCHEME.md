# 货厢顶面计数方案：`roof-count-v1`

这是当前货车项目采用的**数量方案**，也是后续方案比较的基准。它在 GitHub
`main` 分支的方案位置如下：

| 内容 | 位置 |
| --- | --- |
| 完整方案说明 | `docs/COUNTING_SCHEME.md`（本文件） |
| 参考实现 | `coord/optimization-20261022/roof-count-v1/roofs.py` |
| 单元测试 | `coord/optimization-20261022/roof-count-v1/test_roofs.py` |
| 冻结集双视区生成 | `coord/optimization-20261022/roof-count-v1/build_inputs.py` |
| 逐时刻对真值核验 | `tools/check_counting_truth.py` |
| 冻结真值 | `coord/optimization-20261022/review_bridge/quantity-truth-15.json` |
| 两次实跑证据 | `coord/optimization-20261022/roof-count-v1/evidence-runs.json` |
| 选错方案的事故复盘 | `coord/optimization-20261022/RETRO-scheme-selection-20261024.md` |

方案 ID：

```text
roof-count-v1/full+far55/lite-260915/absorb-0.55-0.15-0.02
```

方案 ID 回答的是“这次到底跑的是哪条配方”。任何一项改变——提示词、模型、
输入视区、吸收参数——都应产生新 ID，并重新在冻结集上实测。

## 一句话结论

**只让模型数货厢顶面，不数整车；同一挂车被模型拆出的窄顶片段，再按宽度比例
吸收回车体；吸收后剩几个单位就是几辆车。**

## 开发集成绩

冻结集包含 15 个时刻 × 南/北 2 个机位，共 30 个画面。真值来自人工复核。
两轮独立实跑的结果是：

| 轮次 | 运行 | 命中 | 结论 |
| --- | --- | --- | --- |
| 1 | `job_20261024T124725_f6e0fa90` | **29/30** | 唯一差异：t=1500 北多 1 |
| 2 | `job_20261024T130107_788a46eb` | **28/30** | 两处差异：t=900 南多 1；t=1021 北少 1 |

这两轮产生于 `counting_scheme` manifest 字段加入之前：manifest 已记录
`counting_mode=roof`、主模型、两个模型 ID、源图和帧哈希；车顶原始记录记录了
`prompt_version=roof-count-v1`。当前代码已把完整方案 ID 写进 manifest 的
`config.counting_scheme` 与车顶原始记录。重新运行时应以带完整方案 ID 的新
manifest 为准。

逐画面目标值（北 / 南）：

| 时刻 | 北 | 南 | 时刻 | 北 | 南 | 时刻 | 北 | 南 |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: |
| t=5 | 5 | 3 | t=177 | 3 | 3 | t=300 | 3 | 4 |
| t=470 | 4 | 4 | t=562 | 4 | 4 | t=600 | 4 | 4 |
| t=900 | 3 | 5 | t=1021 | 3 | 5 | t=1113 | 3 | 5 |
| t=1200 | 3 | 5 | t=1500 | 2 | 5 | t=1800 | 2 | 4 |
| t=2100 | 2 | 4 | t=2400 | 3 | 3 | t=2600 | 2 | 4 |

差异不是“模型整体不准”，而是 lite 在个别画面上的边界波动：

| 画面 | 第一轮 | 第二轮 | 人工真值 | 观察 |
| --- | ---: | ---: | ---: | --- |
| t=1500 北 | lite 3 / mini 2 | lite 2 / mini 2 | 2 | lite 第一轮多 1 |
| t=900 南 | lite 5 / mini 5 | lite 6 / mini 5 | 5 | lite 第二轮多 1 |
| t=1021 北 | lite 3 / mini 3 | lite 2 / mini 3 | 3 | lite 第二轮少 1 |

因此应报**两轮分别 29/30、28/30**，不能把最好一次写成稳定能力，也不能写成
“盲测 100%”。这是开发/回归集结果，不是跨场景泛化证明。跨机位同车身份也不是
本方案已经解决的问题；本方案只产生每个机位的数量，跨机位结果仍作为复核候选。

## 三层结构

### 第一层：模型只输出车顶和车体分组

每一帧发两张图给同一个模型：

1. **全景图**：原始完整画面；
2. **远景放大图**：全景上部 55%，缩放到宽度至少 1280 px。

模型必须输出 `roofs`、`vehicles`、`uncertain` 和 `count`。所有 `roof_bbox`
都只框可见顶面，坐标按**第一张全景图**归一化。`uncertain` 用来隔离“驾驶室顶
可能与货体有关、但现在拿不准”的情况，避免它直接多算一辆。

这一步不能用“整车框”替代。整车提示词会让模型先把挂车与窄顶片段合并，后面
的宽度吸收就没有输入，阈值再怎么调也无法恢复被模型提前丢掉的片段。

完整提示词就在参考实现的 `ROOF_PROMPT` 常量中，关键约束是：

- 每个可见货厢/挂车/敞顶货体只算一次；
- 没有牵引车，货体仍算一辆；
- 两个独立货体不能因为旁边有驾驶室而合并；
- 独立牵引车只有明确不挂货时才单独计数；
- 驾驶室归属不确定时进 `uncertain`，绝不直接加一辆；
- 必须扫完整画面，包括远端、两侧、暗处和部分遮挡；
- 排除叉车、轿车、面包车、人、设备、堆货和建筑；
- 不凭空补完全看不见的车。

### 第二层：窄顶片段按宽度吸收

先把模型给出的 roof 按 `vehicles` / `uncertain` 分组，每组取框的并集，得到
一个候选单位。对单位 `a`、`b`，设：

```text
w(a) = ax2 - ax1
w(b) = bx2 - bx1
gx(a,b) = max(0, bx1 - ax2, ax1 - bx2)
gy(a,b) = max(0, by1 - ay2, ay1 - by2)
```

当同时满足下面三项时，把窄的 `a` 吸收进宽的 `b`：

```text
w(a) / w(b) <= ratio_max
gx(a,b) / min(w(a), w(b)) <= 0.15
gy(a,b) <= y_gap_max
```

参数表：

| 分组情形 | `ratio_max` | `x_gap_fraction` | `y_gap_max` |
| --- | ---: | ---: | ---: |
| 普通 `vehicles` | 0.55 | 0.15 | 0.02 |
| 任一方为 `uncertain` | 0.60 | 0.15 | 0.06 |

吸收从最窄的单位开始，反复执行直到没有可吸收组合。`uncertain` 放宽的原因
是驾驶室顶可能离货体更远；放宽只影响“是否并回同一单位”，不会直接把不确定
组计成一辆。

### 第三层：计数

吸收结束后：

```text
Count(frame) = |surviving units|
FrameHit(frame) = 1[Count(frame) == Gold(frame)]
RunScore = sum(FrameHit(frame)) / number_of_frames
```

同一时刻的南、北分别核验，不用“唯一数 = 南 + 北 - 重合”去掩盖任一机位的
错误。唯一数公式仍然只作为结果一致性校验，不作为本方案的新增视觉指标。

## 模型与连接

| 角色 | 模型 | 用途 |
| --- | --- | --- |
| 主计数模型 | `doubao-seed-2-1-lite-260915` | 公布口径的计数来源 |
| 同帧交叉核对 | `doubao-seed-2-0-mini-260428` | 与 lite 并发调用；lite 失败时补位并用于观察分歧 |

请求参数：

| 项 | 值 |
| --- | --- |
| 端点 | `https://ark.cn-beijing.volces.com/api/plan/v3` |
| `temperature` | `0` |
| `max_tokens` | `2400` |
| 思考模式 | 模型默认，不额外关闭 |
| 单次超时 | 生产演示配置为 420 秒 |
| 重试 | 1 次；缓存必须关闭 |

旧端点 `/api/v3` 在当前账号/套餐下可能返回 401，不能用它判断模型能力。
换 key 或换模型后，必须重新检查端点、返回模型名、失败分母和 30 画面成绩。
不要把 API key 写进仓库、请求记录或日志。

## 如何接入

一次帧分析的输入、调用和输出契约：

1. 用 `build_inputs.py` 或等价逻辑生成全景图与上部 55% 放大图；
2. 两张图按顺序发送给主模型，使用 `ROOF_PROMPT`；
3. 保存返回的 `request_sha256`、`prompt_sha256`、两张输入图的 SHA-256、
   `returned_model`、token 用量和原始响应；
4. 用 `parse_payload()` 解析 JSON；
5. 用 `count_units()` 得到吸收后的单位和数量；
6. 把 `counting_mode`、`counting_primary`、`scheme_id`、prompt 版本和模型 ID
   写进运行 manifest；
7. 旁路模型失败不能静默丢弃；retry、fallback、超时和失败都进入失败分母。

运行时自证的最低要求是：从新运行的 manifest 能直接回答
`counting_mode=roof`、`counting_primary=doubao_lite`，并且能看到完整的
`roof-count-v1/...` 方案 ID。只看界面自称“用了最好方案”不算证据。

## 复现

在仓库根目录先配置 Python 与依赖：

```powershell
python -m pip install -r requirements-dev.txt
python coord/optimization-20261022/roof-count-v1/test_roofs.py
```

生成冻结集的 30 组双视区与输入哈希：

```powershell
python coord/optimization-20261022/roof-count-v1/build_inputs.py --out .roof-inputs
```

`build_inputs.py` 会逐张校验 `dataset-manifest-v1.json` 中记录的源图 SHA-256，
不匹配就停止。生成结果中的 `inputs-manifest.json` 记录全景图、放大图及各自
SHA-256。

对已有分析 job 逐画面核验：

```powershell
python tools/check_counting_truth.py path/to/job --primary doubao_lite
```

已知开发集基准的预期输出是 `MATCH 29/30` 或 `MATCH 28/30`；结果随模型响应
波动。要判断一次新运行，必须使用同一 30 个画面、同一真值和同一口径，并保存
manifest/timeline 或等价原始响应，不能只报界面上的最好一次。

当前两轮实跑使用的 job、manifest SHA-256、timeline SHA-256、逐画面预测和
模型分歧都在 `evidence-runs.json` 中。job 目录属于本地运行产物，不随仓库公开；
这里保留了足以核对分数和差异的逐画面证据。

## 已知边界

- lite 在少数边界画面会多 1 或少 1，当前观测波动是 28–29/30，不是 30/30；
- 这是人工复核的开发/回归集，已经被反复用于方案选择，**不是盲测**；
- 不能把这里的成绩表述为对其他场地、天气、车型或时间段泛化；
- 当前方案解决逐机位数量，不宣称跨镜同车身份已经全对；
- 吸收参数来自冻结开发集，换场景前应先做小规模回归，不要直接用界面成功截图
  代替真值核验；
- 如果模型更换或端点返回不同模型，旧方案 ID 立即失效，需要重新实测。

## 为什么保留这层“窄顶吸收”

模型偶尔把一个宽货体拆成“主顶面 + 窄顶片段”两个组。直接按组数计数会多算，
但用目标检测式的整车框又会提前丢掉片段。保留车顶级输出，并在几何层只做
“窄片段并回宽车体”这一件可控的事，既给模型保留了细节，又让后处理有明确、
可测试的输入。

这也是这次选型事故最重要的教训：**成绩必须绑定到具体提示词、输入表示、模型
和后处理，而不是绑定到仓库里名字听起来最像“pipeline”的那个程序。**
