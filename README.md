# 货车识别与通道容量工作台

纯静态双机位工作台演示，无需构建。页面可直接打开，也可通过任意静态文件服务运行。

## 运行

推荐在仓库根目录执行：

```powershell
python -m http.server 4173 --bind 127.0.0.1
```

然后打开 `http://127.0.0.1:4173/`。

## 演示数据

- `data/demo_result.js`：20 个真实开发集采样帧的双机位人工计数。
- `assets/frames/`：真实北/南样帧。
- `assets/frames/crops/`：证据侧栏使用真实画面切片，不含虚构车辆框。

北/南数量只做“画面内合计”，不冒充跨机位去重唯一车辆数。容量默认值 8/6/4 明确标为“待用户确认”。

## 浏览器验证

```powershell
npm install
npm run ui:check
```

验证脚本要求本机安装 Google Chrome，并需要先启动 4173 静态服务。截图输出在 `assets/ui/`，验证日志与接口说明见 `coord/ui/STATUS.md`。

