# vehicle-memory 状态

- 分支：`research/vehicle-passport`
- 冻结调用提交：`0341a8c92acc3bb745a0c25af9095a5672efea48`
- 证据发布提交：`e809725`；PR：https://github.com/Sealkeeper/truckflow-atlas/pull/13
- 当前判定：证据/复核/回归 `conditional go`；自动计数、自动跨机位去重、把记忆当首次漏计修复 `no-go`。
- 双尺度：20/20 请求成功，14/20 exact，MAE 0.35；修复 1、回归 3；当前形式淘汰。
- 组件装配：8 次冻结但未启动；按中枢要求不追加付费调用。
- 本轮新增调用：20；此前 L2 的 2 次单独计为旧实验成本。
- `cargo_id` / `tractor_id` / `vehicle_session_id`：**未测**，没有完整人工身份真值。
- 双尺度是无记忆同帧输入消融，不得写成记忆库准确率收益；该机制与公共输入尺度路线同族但不共享独立样本。
- 下一步：停止同机制付费复跑，转为离线身份库与换挂/OCR 冲突验证。
