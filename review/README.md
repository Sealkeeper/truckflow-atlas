# 视频复核台

用途：对 10 个开发集时刻 × 2 个机位做一次性终审。当前数量来自 AI 单标注者对抽帧的初标，不是人工金标准。

## 打开

主入口在仓库根目录工作台：打开 `http://127.0.0.1:4178/`，点击双机位画面右上角的
**复核画面**。模态内左南右北并排显示固定通道裁剪图，填写南、北、重合与去重总数；
每列可以单独留空，不确定的数字不会被自动猜出。

下方的“查看原图”会打开原图、`t−2s` 到 `t+2s` 五张连续帧，以及有争议时刻的
30 秒视频。标注截图可在本页预览并记录文件名，不会上传服务器。

旧的整页复核工作台仍保留在：

```powershell
python -m http.server 4178 --bind 127.0.0.1
```

`http://127.0.0.1:4178/review/`

## 每个时刻提供什么

- `t-2s / t-1s / t / t+1s / t+2s` 五张连续帧，点击可放大。
- 9 个通道边界有疑问的时刻另附 ±15 秒视频；页面会标明采样时刻在视频中的位置。
- 南机位单独提供“底边红色货厢”是否计入本通道的选择。
- 草稿保存在浏览器 localStorage；右下角可导出 JSON。
- 主工作台的“复核画面”导出 `truckflow-final-review-v2`，包含南/北计数、重合、
  去重总数、逐列说明、标注图文件名和完成状态。

## 终审完成后

把导出的 JSON 放到任意路径，然后运行：

```powershell
python accuracy/evaluate_reviewed.py `
  --review <导出的复核 JSON> `
  --runs accuracy/runs/count_v2/doubao_baseline_v1 `
  --runs accuracy/runs/count_v2/doubao `
  --runs accuracy/runs/count_v2/aibox `
  --runs accuracy/runs/corridor_v1 `
  --json-out accuracy/runs/reviewed_metrics.json
```

脚本兼容 `v1` 与 `v2`，只统计已确认的样本，并分别输出南/北机位的 exact、MAE、
漏计、多计和逐样本错误；去重总数单独列在 `unique_totals`。

## 重建证据

```powershell
python tools/build_review_crops.py
node review/build-review-data.mjs
node tools/capture-review-modal.mjs
```

帧与视频来自数据底座的只读源视频；不要把原始视频提交进仓库。
