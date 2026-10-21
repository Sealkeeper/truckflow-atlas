# UI 第二套工作台 · 交付状态

更新日期：2026-10-21  
分支：`feat/web-workspace-v2`  
状态：静态工作台完成，浏览器验证通过，真实分析后端未在本次环境中运行。

## 运行

页面不依赖构建步骤。推荐从本 worktree 根目录启动静态服务：

```powershell
python -m http.server 4173 --bind 127.0.0.1
```

打开 `http://127.0.0.1:4173/`。

也可以直接打开 `index.html`；上传分析仍需要可访问的本地 API。

## 已实现

- 深色工业控制台视觉，1440×1000 桌面与 390px 窄屏布局。
- 北/南双画面、原画面/分析画面切换。
- 分析层读取归一化 `boxes`；当前金标准没有框时明确显示“框待后端返回”，不生成推测位置。
- 播放/暂停、时间拖动、上一样本/下一样本、速度切换、键盘空格与左右方向键。
- 0–44:19 时间轴和 20 个真实采样帧；播放时间始终显示最近采样帧及时间差，不做逐帧推断。
- 画面内合计、大/中/小/待定、单车型负载率、综合叠加负载率。
- “跨机位去重待复核”与“去重后负载不可计算”独立呈现，没有把南北数量相加冒充唯一车辆数。
- 容量抽屉、公式展开、待用户确认提示、localStorage 保存/恢复。
- 车辆证据侧栏，真实画面切片、机位、视频/业务时间、模型票数、状态与复核操作。
- 确认、删除、未知、合并、拆分、改判均写入 `truckflow.workspace.reviews.v1`。
- 周期统计 5 分钟/10 分钟/全时段，CSV 下载。
- 上传 1–2 段视频、机位名/起始时间/偏移、采样间隔、容量和通道说明。
- 上传契约：`POST /api/jobs`，随后轮询 `GET /api/jobs/{job_id}` 与 `GET /api/jobs/{job_id}/timeline`。
- 连接真实任务后，复核决定同时写本地并尝试 `POST /api/jobs/{job_id}/reviews/{review_id}`。
- 后端离线、数据缺失、证据筛选为空均有明确状态。

## 数据口径

`data/demo_result.js` 使用公共只读数据 `data/gold/camera_counts_v0.json` 的逐机位人工计数：

- 北：`3,3,4,3,3,2,2,2,3,2`
- 南：`3,4,5,5,5,5,4,4,3,3`

界面中的 20 个采样时刻由两机位列配对展示。`画面内合计`只代表两张画面中的可见辆次；跨机位唯一车辆集合仍为“待复核”。

检测框数量为 0。证据条目编号是为交互演示生成，裁剪来自真实样帧，但没有绑定后端目标框，因此页面不显示虚构 IoU 或坐标。

## 验证

先启动 4173 静态服务，再执行：

```powershell
npm install
npm run ui:check
```

最近一次检查结果：

```text
UI CHECK PASSED
- desktop layout 1440px
- mobile layout 390px
- backend-offline error state verified
- API mock: job → status → timeline → boxes → review POST verified
```

自动检查覆盖：

- 页面横向溢出与 DOM 滚动宽度。
- 图片加载失败、HTTP 404/5xx、请求失败。
- 浏览器控制台 error 与未捕获页面异常。
- 分析模式无虚假检测框。
- localStorage 复核写入。
- 容量默认值待确认文案。
- 播放推进、拖动时间轴、样本切换。
- 周期统计和 CSV 下载。
- 上传按钮在无文件时禁用。
- 后端离线错误提示。
- 契约 mock 覆盖 `POST /api/jobs`、任务轮询、timeline、JSON 框渲染与远程复核 POST。

## 截图

- `assets/ui/desktop-1440x1000.png`
- `assets/ui/desktop-full.png`
- `assets/ui/metrics-1440.png`
- `assets/ui/analysis-mode.png`
- `assets/ui/evidence-drawer.png`
- `assets/ui/capacity-drawer.png`
- `assets/ui/upload-modal.png`
- `assets/ui/narrow-390x844.png`
- `assets/ui/narrow-full.png`

## 仍需外部确认

- 真实分析 API 的 timeline 字段映射与 CORS 尚未在本环境联调；缺样帧或字段无法识别时会报错，不会复用演示图冒充任务结果。
- 通道有效区域、跨机位配对、容量 8/6/4 初始值都待用户/项目经理确认。
- 当前没有金标准检测框，未做框 IoU 或逐框验收。
