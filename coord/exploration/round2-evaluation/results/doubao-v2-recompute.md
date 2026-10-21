# doubao-v2 Mini 独立复算（旧整车口径）

**证据口径：`legacy_whole_vehicle`。Mini 和 B 已看过整车外观，不能追认为 roof-only。**

- 固定 20 分母计数：**18/20**，MAE 0.100，valid 20/20，失败 0，缺失 0
- 0–1000 兼容计数 valid_N：**20/20**；严格 0–1 schema valid_N：**6/20**；严格 schema 下计数 correct：**6/20**
- 输入 hash 20/20：**True**；prompt 与 B 一致：**True**
- 原始/attempt/started 文件 manifest：**80/80**
- Lite：**0/20 未运行**，无筛选或淘汰结论。
- 在线成本：20 调用、20 图、94306 tokens；均值 19.885 秒，p95 27.063 秒。

## 错误帧

- `north_600` 4→3
- `south_2100` 3→4

## 坐标口径勘误

冻结预注册勘误保留：B 兼容计数接受历史 0–1000 归一化；严格 0–1 schema 仍然失败，不能用兼容口径救回。原始分布：

- `raw_0_1`：6
- `raw_0_1000`：14

与路线 summary 一致：**True**。

**判定：旧整车口径模型对照；不是车顶准确率，不是泛化，unique/overlap/身份/自动放行均未测。**
