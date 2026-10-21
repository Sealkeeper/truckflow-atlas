# 调试体验会话状态

更新时间：2026-10-21 17:45 +08:00
页面版本：`debug-lab@1.0.0`

## 当前目标

把“最新识别效果”做成可直接看的实测调试台：逐帧显示模型预测、人工计数、差值、原始候选框与同帧模型对照，并持续输出固定文件名的真实浏览器截图。

## 当前产物

- 调试台：`debug/viewer/lab.html`
- 数据构建：`debug/build-lab-data.mjs` → `debug/viewer/lab-data.json`
- 截图脚本：`debug/capture-lab.mjs`
- 桌面截图：`debug/shots/latest-desktop.png`，1440 × 1000
- 手机截图：`debug/shots/latest-mobile.png`，390 × 844
- 公共副本：`all-sessions-can-see/assets/live/latest-desktop.png`、`latest-mobile.png`
- 自动检查：`debug/shots/report.json`
- 时间戳归档：`debug/shots/archive/`

## 数据来源（全部为真实实验产物）

- 人工计数：`data/gold/camera_counts_v0.json`
- 整帧基线：`accuracy/runs/full_batch/*.json`（豆包，20 帧）
- 提示词对照：`accuracy/runs/promptv2_*.json`（豆包 / Aibox GLM-5.3-flash / 智谱 GLM-4.5V）

页面中的车辆框只读取模型返回的 `bbox`；没有返回框的样本明确显示“未返回可用框”，不补画、不生成推测位置。

## 当前实测数字

- 豆包整帧基线：15 / 18 帧完全正确（83.3%），MAE 0.22，累计漏计 4，多计 0，接口失败 2 帧。
- `north_600`：人工 4，基线预测 2（漏 2）；count_v2 下豆包 3、智谱 3、Aibox 4。
- `north_300`：人工 3，豆包 count_v2 预测 2。
- `south_600`：人工 5，豆包 count_v2 预测 4。
- 以上均为开发集实测，不是验收准确率，也不声称 100%。

## 复现

```powershell
cd D:\File\PROJECT\codex\codex-货车\sessions\debug_experience
node debug\build-lab-data.mjs
node debug\capture-lab.mjs
```

脚本会启动随机端口的本地静态服务器，用本机 Chrome 无头模式操作页面（切换模型与样本），截图后覆盖 `latest-*` 与 `report.json`，并复制到公共 `assets/live/`，同时写入时间戳归档。

## 最近验证

- 桌面 1440 × 1000、手机 390 × 844，均无横向滚动、文字裁切、图片失败、控制台错误或 HTTP 4xx/5xx。
- 默认展示 `north_600`：预测 2 / 人工 4，图上 2 个真实候选框。
- 切换 Aibox 模型后显示 4 / 人工 4，差值为 0；同帧对照区同时列出其他模型结果。
- 手机端将样本格、模型列表与详情改为单列/多列堆叠，不产生页面级横向溢出。

## 遗留问题

1. 跨机位唯一车辆仍未去重，页面不提供“唯一总数”。
2. 南机位底边红色货厢的通道归属仍待用户确认。
3. 候选框未经人工标注，不能计算 IoU；本页只用于目视核对。
4. Aibox 单样本正确不足以证明稳定提升，需要扩样复测。
5. 接口失败的 2 帧仍缺结果，准确率分母只含成功帧。
