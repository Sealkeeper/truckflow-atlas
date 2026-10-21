# 视频复核台

用途：对 20 个开发集时刻做一次性终审。当前数量来自 AI 单标注者对抽帧的初标，不是人工金标准。

## 打开

在仓库根目录启动静态服务后打开：

```powershell
python -m http.server 4178 --bind 127.0.0.1
```

`http://127.0.0.1:4178/review/`

## 每个时刻提供什么

- `t-2s / t-1s / t / t+1s / t+2s` 五张连续帧，点击可放大。
- 9 个通道边界有疑问的时刻另附 ±15 秒视频；页面会标明采样时刻在视频中的位置。
- 南机位单独提供“底边红色货厢”是否计入本通道的选择。
- 草稿保存在浏览器 localStorage；右下角可导出 JSON。

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

脚本只统计已勾选“我已复核此帧”的样本，并分别输出 exact、MAE、漏计、多计和逐样本错误。

## 重建证据

```powershell
node review/build-review-data.mjs
```

帧与视频来自数据底座的只读源视频；不要把原始视频提交进仓库。
