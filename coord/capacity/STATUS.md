# 通道容量与透视几何 · 会话状态

更新时间：2026-10-21 17:35（Asia/Shanghai）  
分支：`research/capacity-geometry`  
工作目录：`sessions/capacity_geometry`

PR：[#4 feat(capacity): 单应标定与容量不确定性](https://github.com/Sealkeeper/truckflow-atlas/pull/4)。  
该 PR 已由仓库所有者合并；本会话没有执行合并。`REPORT.md` 已进入 `origin/main`。

## 当前目标

为工作台提供可解释的通道几何标定与容量建议：

- 四角点选 + 单应反投影；
- 大/中/小型货车的占位、倒车余量与纵向/面积两种容量；
- 消失点、点选误差、镜头畸变与输入不确定性分析；
- 负载率严格按 `Σ(当前该型数量 / 该型容量)`；
- 在用户确认前，所有容量都标记为建议值。

## 已完成

- `research/capacity_geometry/capacity.js`：纯前端 UMD 几何与容量模块，无第三方依赖。
- `research/capacity_geometry/capacity.css` + `index.html`：可交互标定页。
- `research/capacity_geometry/test/capacity.test.js`：15 条 Node 断言，当前 **15/15 通过**。
- `research/capacity_geometry/analysis/run_samples.js`：北/南两张样帧的可复现实验。
- 样帧标定截图和俯视预览：
  - `research/capacity_geometry/assets/north_calibration.png`
  - `research/capacity_geometry/assets/south_calibration.png`
  - `research/capacity_geometry/assets/north_topdown.png`
  - `research/capacity_geometry/assets/south_topdown.png`
- `research/capacity_geometry/REPORT.md`：完整公式、假设、误差传导、样例与接入契约。

## 当前建议值（不是用户确认容量）

假设：通道宽 6.0 m、可见段长 55.0 m、尽端式、单车道、纵向净距 2.0 m、面积填充率 0.55。6.0 × 55.0 m 本身是待现场校正的展位模数假设。

| 车型 | 纵向容量建议 | 20,000 次 MC P05–P95 | 面积法参考 |
|---|---:|---:|---:|
| 大型 | 2 | 1–3 | 3 |
| 中型 | 4 | 3–5 | 6 |
| 小型 | 6 | 4–8 | 11 |

若大/中/小型各 1 辆，基线负载率为 `1/2 + 1/4 + 1/6 = 91.7%`；容量区间对应的负载率约为 65.8%–158.3%。

## 需要其他会话知道的事实

- 浏览器全局名：`window.TruckCapacity`；Node 可 `require("research/capacity_geometry/capacity.js")`。
- 关键接口：
  - `calibrate({ imagePoints, widthM, lengthM, imageSize })`
  - `calibrateFromReference({ imagePoints, knownSide, knownM, aspectRatio })`
  - `computeCapacities({ widthM, lengthM, model, vehicles })`
  - `monteCarloCapacity({ widthM, lengthM, model, trials, seed })`
  - `loadSummary(counts, capacities)`
- 四角顺序：近左、近右、远右、远左。
- 单应矩阵面积由米制 `W × L` 决定，像素面积只作诊断；不能把像素比例当米制。
- 工作台必须显示 `confirmed:false`、建议算法（移动通道默认 `longitudinal`）和 P05–P95，不能只拿“2/4/6”当最终容量。
- `computeCapacities()` 的容量是“整条通道全部放该车型”的口径，适合产品规格的 `Σ(N_i/C_i)`；不是混合车型同时装载的物理排布证明。
- 模块未做目标检测、跟踪或车辆计数。

## 阻塞与需要用户操作

1. 通道实际宽度（米）与可见段长度（米）需现场卷尺/CAD 校正；当前 6.0 × 55.0 m 是假设。
2. 需确认通行方式为直通式还是尽端式；样例按尽端式计算。
3. 需确认南侧样帧底边红色货厢是否位于通道有效长度内；当前只把它当作背景障碍，不参与容量公式。
4. 若需消除广角畸变，需提供相机型号/焦距/主点或镜头标定图；当前没有 EXIF 级参数，只给条件敏感性。
5. 用户未确认前，不得把建议值写入额定容量或对外称实测精度。

## 最近验证

```powershell
node --test research/capacity_geometry/test/capacity.test.js
# 15 tests, 15 pass

node research/capacity_geometry/analysis/run_samples.js
# 生成 analysis/sample-results.json
```

浏览器通过本地 HTTP 冒烟验证：

```text
http://127.0.0.1:8899/research/capacity_geometry/index.html?preset=north&capture=1
http://127.0.0.1:8899/research/capacity_geometry/index.html?preset=south&capture=1
```

两页均渲染 330.0 m²、三种车型容量卡片、敏感性表，并保持“建议值 · 待用户确认”。
