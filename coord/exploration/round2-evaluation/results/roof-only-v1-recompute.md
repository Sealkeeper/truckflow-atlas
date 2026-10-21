# roof-only-v1 独立复算

**`roof_only_v1` 新口径；输入为完整 aisle 图，只有 prompt 限制使用车顶证据，未实施像素遮罩。旧 B / Mini / identity 不混算。**

- 固定 20 分母：**6/20**，valid 13、failed 7、refused 0、missing 0
- valid-only MAE：**0.846**；漏计 10 单位/6 帧，多计 1 单位/1 帧
- 原始数字 count 命中：**11/20**；无 uncertain 的 fully-resolved count：**11/20**
- schema 严格有效：**13/20**；其中计数命中 6/20；schema 失败但数字命中 5/20
- uncertain：6 个样本、8 组、12 个顶部观察
- 输入 hash：20/20；prompt：一致；raw manifest：80/80
- 禁用证据词只出现在 reasoning 的禁用指令复述/自检中：13 次提及，正向使用疑点 0 次；这不能证明像素层未使用下部证据。

| 项目 | 值 |
|---|---:|
| HTTP 尝试 / 成功 / 重试 | 20 / 20 / 0 |
| 图像提交 | 20 |
| tokens | 73983 |
| HTTP 均值 / p95 秒 | 15.427 / 23.967 |
| 样本 e2e 均值 / p95 秒 | 15.435 / 23.977 |
| workers=2 墙钟秒 | 160.229 |

## 判定

7 个机位输出因 `roof_kind` 输出为字面量 `cab_roof|cargo_roof` 而 schema 失败；这不是坐标换算或计数公式失败，也不能把其数字命中追认为严格有效。固定 20 分母只有 6/20 严格有效且计数正确，低于旧 B 的 18/20，当前配置应淘汰，不进入主链路。

顶部 bbox 语义、size 车型正确率、物理组成、跨机位身份和独立时段泛化均 `not measured`。数字命中不等于这些对象级结论。
