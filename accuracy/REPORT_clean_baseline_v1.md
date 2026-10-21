# 纯净评测基线 v1：单一 aisle 视图

日期：2026-10-21

## 结论

本报告只评测一个明确视图：`*_aisle.json`。`grid_aisle`、`grid_grid_aisle` 等视图全部排除，目录内每个样本只有一个文件。

| 指标 | 结果 |
|---|---:|
| N（人工真值分母） | 20 |
| graded | 20 |
| exact | **16/20** |
| exact rate | **80.0%**，不是 100% |
| MAE（graded） | **0.25** |
| 漏计 | **4** |
| 多计 | **1** |
| failed | **0** |
| missing | **0** |

四个错误帧：

| 样本 | 人工真值 | aisle 预测 | 误差 |
|---|---:|---:|---:|
| `north_300` | 3 | 2 | -1 |
| `north_5` | 5 | 4 | -1 |
| `north_600` | 4 | 2 | -2 |
| `south_2100` | 3 | 4 | +1 |

![四个错误帧](accuracy/evidence/clean_baseline/errors_contact.jpg)

旧 `accuracy/runs/aisle_doubao/` 混有多个视图。旧脚本在 payload 没有 `sample_id` 时按图片名前两段归并，后读到的文件会覆盖同名样本，因此混合目录的 `17/20` 不能作为验收值。

只取纯 `aisle` 且保留 `south_1200` 原始失败记录时，复现中枢的基线为 `N=20, graded=19, exact=15/19, MAE=0.263, 漏4, 多1, failed=1`。本会话按任务要求补跑 `south_1200` 的同款 aisle 裁剪，接口成功返回 5，故干净基线为 `16/20`。补跑没有改变任何人工真值。

## 目录组成

`accuracy/runs/aisle_clean/` 共 20 个样本文件：

`north_5`, `north_300`, `north_600`, `north_900`, `north_1200`, `north_1500`, `north_1800`, `north_2100`, `north_2400`, `north_2600`,
`south_5`, `south_300`, `south_600`, `south_900`, `south_1200`, `south_1500`, `south_1800`, `south_2100`, `south_2400`, `south_2600`。

- 19 个成功文件是 `accuracy/runs/aisle_doubao/*_aisle.json` 的逐字节副本。
- `south_1200_aisle.json` 使用同一裁剪几何补跑。
- 没有复制任何 `*grid*` 文件。
- `_provenance.json` 记录来源、裁剪几何、原始失败和补跑结果；评测脚本忽略下划线开头的文件，不把它当样本。
- `aisle` 裁剪几何：1280×960 原帧裁 `x=350..870, y=0..960`（520×960），放大 2 倍到 1040×1920。与仓库内现有 aisle 图的灰度相关性为 0.996。

## 真值来源与证据

人工真值文件：

- `accuracy/reviewed/user-final-review-v2-2026-10-21.json`
- SHA256 `735045af4055d2badae2c3bed1942c5a15c6a872ce548243cd52e6657fda971e`
- schema `truckflow-final-review-v2`，10 个时刻全部完成，每时刻拆 north/south 两个相机样本，合计 20 个相机样本。

用户逐车红框标注证据：

- `review/user-attachments-20261021/manifest.json`
- SHA256 `ca299359e0f31f390176610826712a256c57ecd43979bf4bfcfbd58bbd02c65b`
- 9 张 PNG、6 个时刻；manifest 中 9 条 SHA256 已逐文件复算一致。
- 这些图只作为人工真值来源证据，不参与模型输入或评测推理。

| 时刻 | 相机 | 红框车辆数 | 文件 | SHA256 |
|---|---|---:|---|---|
| 00:05 | north | 5 | `0005_1.png` | `964944f86bd1a00112fd66db5ee7def1984236a27026a9deaf054643aee8e7e1` |
| 00:05 | south | 3 | `0005_2.png` | `008f90c6bd0aa8dfd17d1466f235a98e12df499978639c7ce7ec52583f874701` |
| 05:00 | south | 4 | `0500_1.png` | `0123d0b46d89728c0a16e03afd89bab0b147bd7b1fd517dcb378b4fbce5b58fa` |
| 10:00 | south | 4 | `1000_1.png` | `ef7e66994b78a5652cec835ea40b786f03505f1e057f69644f6320a6262e12af` |
| 10:00 | north | 4 | `1000_2.png` | `8ab9c6c4c305b18f9b1db6ab53637088b1bb7cebaa539057f083fae0070a2817` |
| 15:00 | south | 5 | `1500_1.png` | `5c4e76d57bbc598714505a52a4034d33bee1bfb96dfe7cdc8c2950002ea9572d` |
| 20:00 | south | 5 | `2000_1.png` | `ec71a7a7be6001cb5e540753b2074e54f632b747d4a9091b8ae296b1ff90c19f` |
| 43:20 | south | 4 | `4320_1.png` | `dbc014927dab85a79079d91a521f2e4e544620c676d224cecd2a9d983e69d578` |
| 43:20 | north | 2 | `4320_2.png` | `8c9e14792b4aeb49d1013d753d975b87e7ff28e446a13c57f1cfefc083079c0b` |

未提供标注图的时刻：`25:00`、`30:00`、`35:00`、`40:00`。这些时刻仍保留用户 `camera_counts`，但没有逐框附件。

## 复现命令

重复评测（确定性，重复运行输出字节一致）：

```powershell
python accuracy/eval_clean.py `
  --review accuracy/reviewed/user-final-review-v2-2026-10-21.json `
  --runs accuracy/runs/aisle_clean `
  --view aisle `
  --json-out accuracy/reviewed/evaluation-clean-v1.json
```

重新生成错误证据图：

```powershell
python accuracy/build_clean_evidence.py
```

`south_1200` 补跑命令：

```powershell
python accuracy/model_probe.py accuracy/crops/south_1200_aisle.jpg `
  --models doubao `
  --out accuracy/runs/aisle_clean/south_1200_aisle.json `
  --max-tokens 3000
```

## 逐帧结果

| 样本 | 真值 | 预测 | 误差 | 状态 |
|---|---:|---:|---:|---|
| north_5 | 5 | 4 | -1 | ok |
| north_300 | 3 | 2 | -1 | ok |
| north_600 | 4 | 2 | -2 | ok |
| north_900 | 3 | 3 | 0 | ok |
| north_1200 | 3 | 3 | 0 | ok |
| north_1500 | 2 | 2 | 0 | ok |
| north_1800 | 2 | 2 | 0 | ok |
| north_2100 | 2 | 2 | 0 | ok |
| north_2400 | 3 | 3 | 0 | ok |
| north_2600 | 2 | 2 | 0 | ok |
| south_5 | 3 | 3 | 0 | ok |
| south_300 | 4 | 4 | 0 | ok |
| south_600 | 4 | 4 | 0 | ok |
| south_900 | 5 | 5 | 0 | ok |
| south_1200 | 5 | 5 | 0 | ok |
| south_1500 | 5 | 5 | 0 | ok |
| south_1800 | 4 | 4 | 0 | ok |
| south_2100 | 3 | 4 | +1 | ok |
| south_2400 | 3 | 3 | 0 | ok |
| south_2600 | 4 | 4 | 0 | ok |

## 失败与契约测试

`south_1200` 原始 run（补跑前）为失败：

- model `doubao` / `ep-20260828174616-dthpx`
- 1 次请求，150.5 秒
- `ProxyError: ... Remote end closed connection without response`

补跑成功：1 次请求，13.96 秒，`total=5`。

负向测试结果：

- 把原始失败记录放回 `south_1200`：`N=20, graded=19, exact=15/19, MAE=0.263, failed=1`，失败帧单列，未被丢弃。
- 删除 `north_600` 文件：`N=20, graded=19, exact=16/19, missing=1`，缺失帧单列。
- 混入 `north_600_grid_aisle.json`：契约错误，退出码 1。
- 两个文件声明同一 `sample_id`：契约错误 `duplicate sample_id: north_300 ...`，退出码 1。
- 同一评测命令重复运行：`evaluation-clean-v1.json` 字节完全一致，SHA256 为 `7f5aedd22da7de94fde7927c61e7621daf7069d9ad6a53da6900f04e2124e885`。

## 文件清单与哈希

评测输出：

| 文件 | SHA256 |
|---|---|
| `accuracy/reviewed/evaluation-clean-v1.json` | `7f5aedd22da7de94fde7927c61e7621daf7069d9ad6a53da6900f04e2124e885` |
| `accuracy/eval_clean.py` | `b12c8c30a36062fc78fc6b79c88935c0d7069b012ce1f8a7a218c71e61e61e6a` |
| `accuracy/build_clean_evidence.py` | `045af3e779b6e13a12e7c23fea8d12deec26886c454d11accbbc00c6709be33d` |
| `accuracy/evidence/clean_baseline/errors_contact.jpg` | `b55f529c9dd047ee2c03d523223e8e894b25799b802dc056afc5e07d06838570` |
| `accuracy/runs/aisle_clean/_provenance.json` | `ecfe2065e1994f68642abbd2f976c4a17525466e4a3c55c091aecd73c034079f` |

运行文件：

| 文件 | SHA256 |
|---|---|
| `north_1200_aisle.json` | `88563b76ce0003be36bcfbd0af79bf4ca43c4d0d8fb5851bfaff8cad014f2ef1` |
| `north_1500_aisle.json` | `ae05902eb8dc0c0f73904fec5ae8bd3af1b17a4c9f60ccf5f4d6a1c4cc59b723` |
| `north_1800_aisle.json` | `7fc9418580916ae158942d7383390252afdcc5bf68cf8377e7b558c17f4774ed` |
| `north_2100_aisle.json` | `3c2d99ea6929ab64d3e91c5004e408cb0e2ece976a9526da7682bbe962e72ddf` |
| `north_2400_aisle.json` | `5f9e8162d9400c5acc0998cccf230b5b283609aaecd32da68c30760edf833547` |
| `north_2600_aisle.json` | `a684f7c665a18420b5337c378abd1707aeef1eb96beaca1260cd138954795454` |
| `north_300_aisle.json` | `ce3cecc4c6555c1578eb5a9dea0e3d88b08e91aa5684ce95022007ec5c09994e` |
| `north_5_aisle.json` | `4aaea69b4f84d6cfc124f4ec2d3c7d5c9c7dafbb833a5ab7b1fd11c2afcdc125` |
| `north_600_aisle.json` | `73631e8ab81ffd26fa61ab471669212a1e071b75666410825b78a14c2c7f290b` |
| `north_900_aisle.json` | `2138e8eee740fb1e1a69fca669230dc8ad9adbc10914a6f2d3531b28ed142e80` |
| `south_1200_aisle.json` | `3fb509d49b65ec6e3f13b80b0c2bef05498f22a0d6c24b47aed89ffc14e57634` |
| `south_1500_aisle.json` | `d64f57539fc247bb295fe602b94f2c04f149dcf0f19ac39d80dfd0ea2a761fd2` |
| `south_1800_aisle.json` | `880c4d8a503d2c3ac353c67dadc1d2717017a6b491fd0bf0c97af722f17c5b75` |
| `south_2100_aisle.json` | `2ce17076b7383e37366c05947c1f08ce1273c810fe620271385d58d24439715e` |
| `south_2400_aisle.json` | `016f40c4b8e6bca5cee598fad5b52c7875ae93886c5c073b98a879e1258eb35e` |
| `south_2600_aisle.json` | `0031a4ffcd8d9b6b300a4b64c751addd5cd89547e6853dd21d377b05194357f3` |
| `south_300_aisle.json` | `6aa419f9ab91c1f8b7d06810ad48147da899422f5cf342f8c0224b13c5f3dea0` |
| `south_5_aisle.json` | `a68a9b24a2ee77edfd0801b56041a497b73b562d64ab0bb0042aa64d04c282df` |
| `south_600_aisle.json` | `3d652e7d2aa0c093add861088be55bc880eacde7684557e2d50128ced49ea7c7` |
| `south_900_aisle.json` | `2c686c1a32d36fe8f153a0d6b417f3dfd1e2a602d41ed4b1499495b7d0f8dc6b` |

## 计数口径审计

本节只审计，不修改 `user-final-review-v2`，也不修改任何模型输出。

用户红框标注已经说明：用户按**独立货厢/车体逐辆计数**，牵引车与其挂车没有被重复框选。因此此前“南侧 5 可能是 3 辆”的推断撤回。按当前用户真值与按物理车合并的差异如下：

| 样本 | 当前用户真值 | 若按物理车合并 | 差异 | 证据与边界问题 | 需要用户裁决 |
|---|---:|---:|---:|---|---|
| `south_600` | 4 | 4 | 0 | 10:00 红框图 4 个框；白车头+白厢、红车头+灰厢均未拆框 | 否 |
| `south_900` | 5 | 5 | 0 | 15:00 红框图 5 个框；含底边红色货厢 | 底边是否属于通道 |
| `south_1200` | 5 | 5 | 0 | 20:00 红框图 5 个框；含底边红色货厢 | 底边是否属于通道 |
| `south_1500` | 5 | 5 | 0 | 用户备注“最下方红车只露出一半也算”；无独立红框附件 | 底边是否属于通道 |
| `north_5` | 5 | 5 | 0 | 00:05 红框图 4 个远端独立货厢 + 1 辆近端红车 | 左侧货厢列是否全部在通道内 |
| `south_2600` | 4 | 4 | 0 | 43:20 红框图 4 个框；含底边红色货厢 | 底边是否属于通道 |

需要用户裁决的具体帧：

1. `north_5`：左侧货厢列（用户红框为 4 个远端独立货厢）是否全部属于要统计的通道。
2. `south_900`、`south_1200`、`south_1500`、`south_2600`：底边红色货厢是否在正式通道多边形内。当前用户真值都把它计入；如果正式边界排除它，这四帧的真值需要重算。

除通道边界外，不再存在“牵引车+挂车被拆成两辆”的配对口径差异。

## 限制

- 这是相机内可见车体计数，不是跨南北机位的唯一车辆集合；南北数量不能直接相加。
- 本次只评总数，不评车型。
- 用户逐框附件覆盖 9 个相机样本、6 个时刻；其余样本保留用户 `camera_counts`，没有逐框附件。
- `south_1200` 的补跑是一次新的 API 请求。原始失败记录仍保存在 `_provenance.json`；如果重跑接口失败，评测会按 failed 计入分母并单列。
