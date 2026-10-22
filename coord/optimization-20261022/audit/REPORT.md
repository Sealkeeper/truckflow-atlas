# TruckFlow v3 评测器红队审计

审计日期：2026-10-22  
审计对象：`coord/evaluation-v3/evaluator.py`，SHA-256  
`5CF34805F37F68098E9DC0C374FAF468C8D5EFD79D4543EA1E46F352B61CE74F`  
协议：`3.0.1`，SHA-256  
`84922CF72275ABA34D4E6874D4BABD323D80DEB7D85F5D7A13362739A41FCDC8`

## 结论

**当前评测器不可用于 100% 放行。**

- 31 个红队用例中 **2 个 FAIL**，29 个 PASS。
- 最严重问题：机位 `status=ok` 时，`camera.count=null` 仍可让
  `quantity_all_correct_rate=1.0`、`identity_all_correct_rate=1.0`、
  `combined_all_correct_rate=1.0` 同时成立。即缺一个必填机位计数字段，
  评测器仍报整时刻 100%。
- 第二个问题：机位侧 `count=0/vehicles=[]` 与时刻侧
  `quantities.south=2` 自相矛盾时，数量主指标仍报 1.0。
- 两项缺陷都在数量结构检查 `_prediction_structure`，不影响本轮已通过的
  身份集合、重复边、跨镜 pair、部分真值、去重时刻、bbox 和匹配确定性结论。

审计期间 `evaluator.py`、`PROTOCOL.md` 和原测试被并行更新。本报告只对上面
固定哈希与协议 3.0.1 负责；如文件再变，必须重跑。

## 严重度排序的发现表

| 编号 | 严重度 | 攻击输入 | 实际结果 | 期望结果 | FAIL | 修复建议 | 对应测试 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F01 | Critical | `status=ok`、`objects_complete=true`、south `count=null`，车辆列表完整，`quantities.south=2` 且其余三项正确 | quantity `1/1=1.0`，identity `1/1=1.0`，combined `1/1=1.0`，`reasons=[]` | 协议 §5.1 要求 `objects_complete=true` 时 `count == len(vehicles)`；`null` 不等价于 2，数量必须失败，combined 不得为 1 | **是** | 在 `_prediction_structure` 中把“`count` 必须是非负整数”设为失败条件；再用 `count` 与 `quantities[camera]` 交叉校验 | `test_redteam.py::test_redteam_case[A14d-camera-count-null]`、`cases.py:451` |
| F02 | High | south `count=0`、`vehicles=[]`，但同一预测时刻 `quantities.south=2`、`north=2`、`overlap=1`、`unique=3` | quantity `1/1=1.0`；identity `0/1=0.0`；combined `0/1=0.0` | 两个机位数量表示互相矛盾，结构不自洽；数量主指标必须失败 | **是** | 在 `_prediction_structure` 中要求 `camera.count == quantities[camera]` | `test_redteam.py::test_redteam_case[A14e-camera-contradiction]`、`cases.py:465` |

### F01：缺失机位 count 仍得到整时刻 100%

输入相对“完美夹具”的差异：

```json
{
  "moment_id": "m1",
  "decision": "auto",
  "cameras": {
    "south": {
      "status": "ok",
      "count": null,
      "objects_complete": true,
      "vehicles": [
        {"id": "ps1", "bbox": [0.1, 0.1, 0.2, 0.2], "occlusion": "none"},
        {"id": "ps2", "bbox": [0.4, 0.1, 0.2, 0.2], "occlusion": "none"}
      ]
    },
    "north": {
      "status": "ok",
      "count": 2,
      "objects_complete": true,
      "vehicles": [
        {"id": "pn1", "bbox": [0.1, 0.1, 0.2, 0.2], "occlusion": "none"},
        {"id": "pn2", "bbox": [0.4, 0.1, 0.2, 0.2], "occlusion": "none"}
      ]
    }
  },
  "overlap_edges": [["ps1", "ps2"]],
  "cross_camera_pairs": [["ps1", "pn1"]],
  "quantities": {"south": 2, "north": 2, "overlap": 1, "unique": 3}
}
```

实际完整报告见 `actual-results.json` 的
`case_results[A14d-camera-count-null]`。关键输出：

```json
{
  "quantity": {"numerator": 1, "denominator": 1, "rate": 1.0},
  "identity": {"numerator": 1, "denominator": 1, "rate": 1.0},
  "combined": {"numerator": 1, "denominator": 1, "rate": 1.0},
  "reasons": []
}
```

根因：`_prediction_structure` 只在 `is_int(count)` 时比较
`count != len(vehicles)`；`None` 直接跳过检查。`_identity_for_moment` 又不
检查机位 `count` 字段，因此两个主指标同时放行。

### F02：机位计数与时刻计数矛盾，数量仍为 100%

输入差异：

```json
{
  "cameras": {
    "south": {
      "status": "ok",
      "count": 0,
      "objects_complete": true,
      "vehicles": []
    }
  },
  "quantities": {"south": 2, "north": 2, "overlap": 1, "unique": 3}
}
```

实际结果：quantity `1/1=1.0`、identity `0/1=0.0`。机位侧明确声明“0 辆、
0 个对象”，时刻侧却声明“2 辆”，数量主指标仍为 100%。

## 最小补丁建议

以下只是 diff 文本，**未修改** `coord/evaluation-v3/` 源文件。它保留协议
§5.1 的既有裁定：`objects_complete=false` 不否决数量维度。

```diff
--- a/coord/evaluation-v3/evaluator.py
+++ b/coord/evaluation-v3/evaluator.py
@@ -393,6 +393,9 @@ def _prediction_structure(prediction: Any) -> dict[str, Any]:
     problems: list[str] = []
     cameras = prediction.get("cameras") if isinstance(prediction, dict) else None
+    quantities = (
+        prediction.get("quantities") if isinstance(prediction, dict) else None
+    )
     for camera in CAMERAS:
         value = cameras.get(camera) if isinstance(cameras, dict) else None
         if not isinstance(value, dict):
@@ -402,6 +405,17 @@ def _prediction_structure(prediction: Any) -> dict[str, Any]:
         vehicles = value.get("vehicles")
         if not isinstance(vehicles, list):
             problems.append(f"{camera}_vehicles_not_array")
             continue
+        count = value.get("count")
+        if not is_int(count):
+            problems.append(f"{camera}_count_missing")
+        moment_count = (
+            quantities.get(camera) if isinstance(quantities, dict) else None
+        )
+        if (
+            is_int(count)
+            and is_int(moment_count)
+            and count != moment_count
+        ):
+            problems.append(f"{camera}_camera_count_quantity_mismatch")
         if value.get("objects_complete") is not True:
             # A quantity-only answer may carry a partial object list; only a
             # claim of completeness makes list/count agreement checkable.
@@ -412,7 +426,6 @@ def _prediction_structure(prediction: Any) -> dict[str, Any]:
         if any(not isinstance(identifier, str) or not identifier for identifier in ids):
             problems.append(f"{camera}_invalid_vehicle_id")
         elif len(set(ids)) != len(ids):
             problems.append(f"{camera}_duplicate_vehicle_id")
-        count = value.get("count")
         if is_int(count) and count != len(vehicles):
             problems.append(f"{camera}_count_list_mismatch")
     return {"valid": not problems, "problems": problems}
```

该补丁在 `verify_patch.py` 中通过运行时 monkeypatch 验证，未写源文件：

```text
patched preview: 31/31 PASS, 0 FAIL
```

## 九类攻击面实测

下表均为实际运行结果；“q/i”是数量全对率与身份全对率的分子/分母。

| 用例 | 攻击输入摘要 | q | i | 结论 |
| --- | --- | ---: | ---: | --- |
| A00-perfect | 完美 gold + 完美 predictions | 1/1 | 1/1 | PASS：两项均 1.0 |
| A01-overlap-duplicate | `[["ps1","ps2"],["ps1","ps2"]]` | 1/1 | 0/1 | PASS：`duplicate edge`，身份失败 |
| A02-overlap-mirror | `[["ps1","ps2"],["ps2","ps1"]]` | 1/1 | 0/1 | PASS：镜像归一化后仍判重复 |
| A03-overlap-self-loop | `[["ps1","ps1"]]` | 1/1 | 0/1 | PASS：`links a vehicle to itself` |
| A04-cross-duplicate | 同一 `["ps1","pn1"]` 两次 | 1/1 | 0/1 | PASS：重复 pair 拒绝 |
| A05-cross-multi | `ps1` 同时配 `pn1`、`pn2` | 1/1 | 0/1 | PASS：一对象多配拒绝 |
| A06-cross-wrong-camera | `[["ps1","ps2"]]` | 1/1 | 0/1 | PASS：`must connect south and north` |
| A07-cross-unknown-id | `[["ps1","ghost"]]` | 1/1 | 0/1 | PASS：悬空引用拒绝 |
| A08-duplicate-id-intra | south 两车 id 都是 `ps1` | 0/1 | 0/1 | PASS：数量结构也失败 |
| A09-duplicate-id-cross | north 车复用 south 的 `ps1` | 1/1 | 0/1 | PASS：身份拒绝；数量按计数维度独立保留 |
| A10-review | payload 正确，`decision=review` | 0/1 | 0/1 | PASS：不自动成功 |
| A11-abstain-moment | payload 正确，`decision=abstain` | 0/1 | 0/1 | PASS：不自动成功 |
| A12-invalid-moment | payload 正确，`decision=invalid` | 0/1 | 0/1 | PASS：不自动成功 |
| A13-missing-moment | 删除整个预测时刻 | 0/1 | 0/1 | PASS：固定分母仍为 1 |
| A14-camera-abstain | south `status=abstain`，手填正确 quantities | 0/1 | 0/1 | PASS：§2 机位门槛生效 |
| A14b-camera-missing | 删除 south 整个 camera | 0/1 | 0/1 | PASS：缺失机位不自动成功 |
| A14c-camera-objects-incomplete | south `objects_complete=false`，车框不完整 | 1/1 | 0/1 | PASS：按 §5.1，数量独立通过、身份失败 |
| A14d-camera-count-null | south `count=null`，列表完整 | 1/1 | 1/1 | **FAIL：F01** |
| A14e-camera-contradiction | south `count=0/vehicles=[]`，quantities 写 2 | 1/1 | 0/1 | **FAIL：F02** |
| A15-camera-invalid | south `status=invalid`，手填正确 quantities | 0/1 | 0/1 | PASS |
| A16-partial-truth | quantity truth=false 且 quantities 全 null；identity 完整 | 0/0 | 1/1 | PASS：只排除数量分母，quantity rate=`null` |
| A17-both-partial-null | 两项 truth=false 且 quantities 全 null | 0/0 | 0/0 | PASS：两分母均为 0，不抛错 |
| A18-bbox-nan | south 首车 bbox 宽为 `NaN` | 1/1 | 0/1 | PASS：NaN 框无效，身份失败 |
| A19-bbox-zero-area | south 首车 bbox 宽为 0 | 1/1 | 0/1 | PASS：零面积无效，身份失败 |
| A20-iou-exactly-0.5 | 两框 IoU 精确为 0.5 | 1/1 | 1/1 | PASS：闭区间 `IoU >= 0.5` 接受 |
| A21-bbox-tiny-oob | `x + width = 1.0000005` | 1/1 | 0/1 | PASS：明显越界框被判无效 |
| A22-count-right-identity-wrong | 数量全对，跨镜 pair 错 | 1/1 | 0/1 | PASS：两主指标正确分离 |
| A23-delete-failed-moment | 两个 gold，删除一个预测 | 1/2 | 1/2 | PASS：缺失时刻计失败，分母不缩 |
| A24-duplicate-gold-moment-id | gold 两个 `moment_id=m1` | — | — | PASS：`EvalError` |
| A25-duplicate-prediction-moment-id | prediction 两个 `moment_id=m1` | — | — | PASS：`EvalError` |
| A26-duplicate-time-s | `m2/m3` 都 `time_s=20`，重复正确时刻抬比例 | — | — | PASS：`EvalError: duplicate gold time_s` |
| A27-order-swap | 全并列 IoU，穷举 4 种列表顺序 | — | — | PASS：只有 1 种映射，重放稳定 |

### 1. 重叠边与自环

输入分别为：

```json
{"overlap_edges": [["ps1", "ps2"], ["ps1", "ps2"]]}
{"overlap_edges": [["ps1", "ps2"], ["ps2", "ps1"]]}
{"overlap_edges": [["ps1", "ps1"]]}
```

实际均得到 identity `0/1`，原因分别为 `contains a duplicate edge`、
`contains a duplicate edge`、`links a vehicle to itself`。数量指标仍可独立
为 1，这是协议定义的维度分离，不是身份放行。

### 2. 跨镜 pair

输入分别为：

```json
{"cross_camera_pairs": [["ps1", "pn1"], ["ps1", "pn1"]]}
{"cross_camera_pairs": [["ps1", "pn1"], ["ps1", "pn2"]]}
{"cross_camera_pairs": [["ps1", "ps2"]]}
{"cross_camera_pairs": [["ps1", "ghost"]]}
```

实际均得到 identity `0/1`，reason 分别覆盖重复 pair、同一车辆多配、同机位
pair、未知 id。schema 没有独立 `pair_id` 字段，因此“pair id 全局唯一”以
pair 内容去重和车辆一对一占用实现。

### 3. 预测 id 冲突

```json
{"south": {"vehicles": [{"id": "ps1"}, {"id": "ps1"}]}}
```

实际 quantity `0/1`、identity `0/1`。跨机位复用：

```json
{"south": {"vehicles": [{"id": "ps1"}]}, "north": {"vehicles": [{"id": "ps1"}]}}
```

实际 quantity `1/1`、identity `0/1`。身份维度不静默接受重复 id；数量维度
按自身计数结构独立保留。

### 4. review / abstain / missing / invalid

- moment 级 `review|abstain|invalid` 均使两项主指标 `0/1`。
- 删除 prediction moment 后两分母仍为 1，分子为 0。
- 机位级 `abstain`、缺失 camera、`invalid` 均使两项 `0/1`。
- `objects_complete=false` 依协议 3.0.1 §5.1：数量 `1/1`、身份 `0/1`。
- `count=null` 的缺口见 F01；机位与时刻数量矛盾见 F02。

### 5. 部分真值

```json
{
  "truth_complete": {"quantity": false, "identity": true},
  "quantities": {"south": null, "north": null, "overlap": null, "unique": null}
}
```

实际 quantity `0/0`（rate `null`）、identity `1/1`。两项 truth 都 false 时
两个分母都为 0，不再出现旧版的 `TypeError`，也不把 null 当正确。

### 6. bbox 与 IoU 边界

- `NaN`：identity `0/1`，框被判无效。
- 零宽：identity `0/1`，框被判无效。
- `x + width = 1.0000005`：identity `0/1`，明显越界被拒绝。
- IoU 精确 0.5：identity `1/1`，闭区间生效。
- 协议 §5.2 明定吸收 `1e-9` 表示误差；`is_bbox` 使用
  `x+width <= 1.0+1e-9`。这是已写明的数值容差，不作为 FAIL。

### 7. 一对一匹配确定性

两个 gold、两个预测框完全同位，所有 IoU 都是 1，穷举 gold 与预测列表的
4 种排列。所有排列的 `gold_to_pred` 都相同：

```json
{"g1": "p1", "g2": "p2"}
```

### 8. 数量与身份分离

数量四个字段全对、跨镜 pair 错：

```json
{"cross_camera_pairs": [["ps2", "pn1"]]}
```

实际 quantity `1/1`、identity `0/1`。没有用身份错误污染数量，也没有用数量
正确放行身份。

### 9. 分母篡改

- 删除失败时刻的 prediction：分母保持 2，结果 `1/2=0.5`。
- 重复 gold `moment_id`：`EvalError`。
- 重复 prediction `moment_id`：`EvalError`。
- 两个不同 `moment_id` 共用 `time_s=20`：`EvalError`，不再把重复时刻计入
  分母。

### 完美夹具

A00 使用两个时刻、南北各两车、一条同画面重叠边、一条跨镜 pair；预测逐项
完全相同。实际 quantity `1/1`、identity `1/1`、combined `1/1`，证明评测器
具备返回 100% 的能力，不是“永远不可能 100%”。

## 尚未完全确定的协议点

1. schema 的 camera `eligible` 当前不参与任何分母或合格性判断。协议没有
   定义它的语义；若它应表示“该机位不进入本时刻评估”，评测器尚未实现。
2. 跨机位预测车辆复用同一 id 时，数量指标仍可独立通过、身份失败。若协议
   要求 id 全局唯一且结构错误必须否决全部指标，需要再收紧。
3. 协议 §5.2 的 `1e-9` 与匹配的 `1e-12` 容差意味着“数学意义上的轻微越界/
   轻微不足 0.5”仍可能被接受；当前按已写协议记为可接受数值噪声。

## 一键复现

从项目目录 `D:\File\PROJECT\codex\codex-货车\codexcodex-货车` 执行：

```powershell
Set-Location coord\optimization-20261022\audit
python run_audit.py
python -m pytest -q test_redteam.py
python verify_patch.py
```

再核对原测试：

```powershell
Set-Location coord
python -m pytest -q evaluation-v3/tests/test_evaluator.py
```

本次结果：

```text
run_audit.py: failures=2（31 cases + determinism）
test_redteam.py: 33 passed, 2 xfailed
evaluation-v3/tests/test_evaluator.py: 21 passed
verify_patch.py: 31/31 PASS
```

零网络、零模型 API、零训练、零 git 提交。完整输入和逐用例实际报告保存在
`actual-results.json`，补丁预览结果保存在 `patch-preview-results.json`。

## 证据哈希

| 文件 | SHA-256 |
| --- | --- |
| `evaluator.py` | `5CF34805F37F68098E9DC0C374FAF468C8D5EFD79D4543EA1E46F352B61CE74F` |
| `PROTOCOL.md` | `84922CF72275ABA34D4E6874D4BABD323D80DEB7D85F5D7A13362739A41FCDC8` |
| `gold.schema.json` | `021627902B29D08B32218BF37BECBAB5200B88AA9913D700C77FC01EA2C1D1CC` |
| `predictions.schema.json` | `0AEC7FB6136AE4F74C599D9BBD66AEBD9A4F9D8A21DD57D4290E43226B132B9A` |
| `test_evaluator.py` | `F8887F310C37DF5EE1CC2D837705F6EBDEA190CB8034E9B4C02D6A2E164F2D95` |
| `cases.py` | `F4A5D7E53D0CBA782AF3AECC163A3FF1ABE3292835F66FB545D3D24E7538DDCA` |
| `actual-results.json` | `C5E8B5E51D2186578766E1511FC575BC34F37D48C251FCAB3402945BC5CCC788` |
| `patch-preview-results.json` | `8552AFBDD3C365902D2FE8BF8FB5E4663CC10B8FD87E5992C82B1202B6F531DE` |
