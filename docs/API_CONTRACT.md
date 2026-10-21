# API 契约

本地服务默认 `http://127.0.0.1:8765`。

## 资源

### `POST /api/jobs`

`multipart/form-data`：

- `files`：1–2 个视频；
- `cameras`：JSON 数组，`[{name,start_time,offset_seconds}]`；
- `config`：JSON，采样间隔、容量、通道说明等。

返回 `202`：

```json
{"job_id":"job_...","status":"queued","created_at":"..."}
```

### `GET /api/jobs/{job_id}`

```json
{
  "job_id": "job_...",
  "status": "queued|running|needs_review|complete|failed",
  "progress": 0.42,
  "stage": "sampling",
  "message": "正在处理第 12/40 个时刻",
  "counts": {"total": 7, "small": 3, "medium": 3, "large": 1, "unknown": 0},
  "review_count": 2
}
```

### `GET /api/jobs/{job_id}/timeline`

返回按采样时刻排列的数组。每个点包含机位、视频时间、业务时间、计数、负载率、车辆列表、复核数。

### `GET /api/jobs/{job_id}/evidence/{evidence_id}`

返回证据元数据与可访问的裁剪图 URL。

### `GET /api/jobs/{job_id}/stream`

`text/event-stream`，事件为 `progress`、`timeline`、`review`、`done`、`error`。

### `POST /api/jobs/{job_id}/reviews/{review_id}`

```json
{"action":"confirm|delete|reclassify|merge|split|unknown","size":"large|medium|small","target_id":"T-001","note":"..."}
```

### `GET /api/jobs/{job_id}/export?format=csv|json`

导出已核验与待复核两套数据，二者不能混在一起冒充真值。

### `GET /media/{job_id}/{camera}/{file}`

支持 HTTP Range，用于视频拖动播放和截图。

## 前端兼容策略

- 无后端时加载 `data/demo_result.json`，所有交互可演示；
- 有后端时轮询 `GET /api/jobs/{id}` 和 `GET /timeline`；
- 前端不计算识别结果，只做展示、筛选、几何配置和复核提交。

