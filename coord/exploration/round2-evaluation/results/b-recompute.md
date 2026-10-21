# 单遍 B 独立复算 v2

本轮 **0 次模型调用**，只读取公共 raw、输入图、prompt 和用户终审真值；未修改标签或原路线文件。

## 结论

- 三轮是否都为 18/20：**True**
- 每轮是否 20 valid / 20 调用 / 0 失败：**True / True / True**
- 计数与实例列表长度一致：**True**
- 输入 aisle hash：**20/20**；prompt hash：**True**
- 180 个公共 raw hash：**180/180**
- 自检 `possible_miss=true`：**6**；事后放行错误：**6**
- B 每次 parsed 框不在 0–1 的数量合计：**142**（顶层输出已归一化）

## 三轮固定分母

| run | exact | MAE | 漏单位/帧 | 多单位/帧 | valid | failed | refused | missing | 调用 | tokens | 均值秒 | p95秒 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| r1 | 18/20 | 0.100 | 0/0 | 2/2 | 20 | 0 | 0 | 0 | 20 | 94168 | 19.637 | 30.850 |
| r2 | 18/20 | 0.100 | 1/1 | 1/1 | 20 | 0 | 0 | 0 | 20 | 95705 | 20.533 | 25.810 |
| r3 | 18/20 | 0.150 | 2/1 | 1/1 | 20 | 0 | 0 | 0 | 20 | 90325 | 19.633 | 30.130 |

三轮是同一 20 帧的重复运行，不是 60 个独立样本。

## 错误帧

- r1: `south_300` 4→5, `south_2100` 3→4
- r2: `north_5` 5→4, `south_2100` 3→4
- r3: `north_5` 5→3, `south_2100` 3→4

## 自检放行复算（事后门禁，不是生产安全证明）

60 次运行样本中放行 54，正确 48，错误 6；复核 6；错误帧被复核捕获 0/6。

## 声明值差异

- 与 `summary.json`、`RUNS_INDEX.json` 的 exact/MAE/漏多/失败字段一致；MAE 差异仅来自声明的三位小数舍入。

## 可证反例与边界

- `south_2100_r3_binding`：机器断言 PASS。Count 4 does not prove object-box-attribute binding. This is also a stable overcount across all three runs, not evidence of correct objects.
- `north_600_r1_color_support`：机器断言 PASS。A correct total does not verify a deterministic color claim. Without an attribute gold set, no color accuracy rate is reported.
- `north_600_duplicate_ocr`：机器断言 PASS。Duplicate text is an identity/OCR risk, not proof that both readings are wrong. It cannot be used as a unique instance key.
- `north_5_instability`：机器断言 PASS。Report all runs 5/4/3. Do not select r1 after seeing the truth.

## 性能

三轮平均每轮 20.0 次调用、20.0 张图、93399.333 tokens；帧均值 19.934 秒。历史裁剪/初始化耗时未公开记录，合并不伪造为 0。

**判定：单遍 B 仍是计数研究候选，不是完整身份/框验收，也不是新时段泛化成绩。**
