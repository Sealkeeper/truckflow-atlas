# TruckFlow v3 评测

本目录实现 2026-10-22 冻结的两个业务准确率指标：

1. 数量全对率；
2. 重叠车辆身份全对率。

定位 IoU 只用于内部一对一关联，不是独立业务门槛。面积和大小在缺少可信人工真值时不做准确率评分。

## 运行

```powershell
python coord/evaluation-v3/evaluator.py `
  --gold path/to/gold.json `
  --predictions path/to/predictions.json `
  --out path/to/report.json `
  --md path/to/report.md
```

评测器只读本地 JSON，不访问网络、不调用模型、不写入输入 gold。

## 文件

- `PROTOCOL.md`：冻结口径和统计边界。
- `gold.schema.json`：人工真值结构说明。
- `predictions.schema.json`：模型输出结构说明。
- `evaluator.py`：标准库实现。
- `tests/test_evaluator.py`：固定口径测试。

## 当前限制

截至 `REVIEW_READINESS_20261022.md` 的核验，新 30 张尚未全部完成，且没有身份关系 gold。因此当前不能产出任何 100% 或身份准确率结论。

