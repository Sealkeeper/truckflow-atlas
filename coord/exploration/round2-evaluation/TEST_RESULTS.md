# 评测器测试结果

日期：2026-10-21。

命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest .\tests -q -p no:cacheprovider
```

结果：

```text
.................                                                        [100%]
17 passed in 0.16s
```

测试文件：`tools/tests/test_core.py`。

## 覆盖

- 重复 `sample_id`、重复 `(time,camera)` 直接报错，不静默覆盖。
- 重复实例 ID 和“声明计数 ≠ 实例列表长度”使样本失败。
- `0–1` 与 `0–1000` 坐标分开处理；严格失败不因兼容口径被救回。
- overlap/unique 与 `N+S-overlap` 不一致时时刻失败。
- 缺失 truth 不按 0 填；valid、failed、refused、missing、label_missing 分开统计。
- 在线成本与历史初始化分开，缺少初始化时不用 0 冒充。
- roof-only 两个顶部观察可合并到一个物理车。
- uncertain 组不增加物理车数；0 个 confirmed + uncertain 是合法复核结构。
- roof observation 未归属或重复归属失败。
- 下部/外观证据标签失败。
- 单部件 `cab_roof`/`trailer_roof` 缺 `grouping_basis` 失败。
- unknown 顶面或 uncertain 存在时自动放行失败。

这些是评测器逻辑测试，不是模型准确率测试，也不替代公共原图、raw 和真值审计。
