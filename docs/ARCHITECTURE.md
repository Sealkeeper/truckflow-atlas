# 架构

## 分层

```text
浏览器工作台
  ├─ 多机位播放器 / 时间轴 / 证据与复核
  └─ 本地 API
       ├─ Job 调度与 SSE 进度
       ├─ 视频索引 / Range 服务 / 抽帧
       ├─ 多模态识别与共识
       ├─ 评测与金标准回归
       └─ 结果存储（JSONL + 证据图）
```

## 识别服务

- 统一 OpenAI-compatible 客户端，支持 Doubao、智谱、Aibox 等视觉模型。
- 每个请求固定输入：图像、机位、时间、口径、输出 JSON Schema。
- 原始回答、耗时、错误、模型版本全部落盘，支持重放。
- 任何模型都不直接决定最终数；最终数由证据合并和复核门禁产生。

## 存储

```text
data/jobs/<job_id>/
  manifest.json
  frames/<camera>/<ts>.jpg
  raw/<camera>/<ts>/<model>.json
  crops/<evidence_id>.jpg
  timeline.json
  reviews.json
  exports/
```

## 资源策略

- 视频按需读取，不整段转码后再分析。
- 每帧按需裁成 2–4 个重叠视区；只向模型发送必要区域。
- 支持断点续跑：请求 key 由视频哈希 + 时间 + 模型 + 提示词版本组成。

## 安全

- `.env` 只在本机，API Key 不写前端、不入库。
- 上传文件按 job 隔离，文件名清洗，Range 服务仅允许 job 目录内文件。

