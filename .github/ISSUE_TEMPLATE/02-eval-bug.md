---
name: 评测器漏洞
about: 能让错误预测拿到虚高分数的输入
title: "[评测] "
labels: ["evaluator", "high-priority"]
---

## 最小复现

```json
// gold 与 prediction 各给最小片段，能直接跑 run_audit / pytest
```

## 期望 vs 实际

- 期望：
- 实际：

## 影响

这个漏洞会让哪一类错误被掩盖？会给多少帧虚增分数？

## 复现命令

```bash
python -m pytest -q coord/evaluation-v3/tests
python coord/optimization-20261022/audit/run_audit.py
```
