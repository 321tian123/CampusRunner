# Changelog

## v1.0.0 (2026-07-30) — Soft UI 正式版

### 🎨 全新 Soft UI 设计系统
- 莫兰迪低饱和配色 · 奶米白底色 · 大圆角卡片 · 柔和阴影
- 左侧垂直侧边栏导航（仪表盘 / 路线 / 日历 / 设置）
- 朦胧气泡数据图表 → 实时速度折线图（含目标配速参考线）
- 深色打卡日历对比卡片
- 路线进度环形指示器
- 可滚动跑步历史记录列表
- 循环路线模式开关
- 保存/加载路线功能（JSON + GPX）

### ⚡ GPS 引擎优化 (v0.4)
- Ornstein-Uhlenbeck 过程模拟真实 GPS 漂移
- 平滑速度过渡（缓起缓停，cubic ease-in）
- 起步爆发注入（8 样本快速 GPS 定位）
- NMEA 卫星星座仿真数据
- 步频/步幅实时计算
- 多瓦片服务器支持（CartoDB Lite / OSM / OSM France）+ SQLite 离线缓存

### 🗺 核心功能
- 雷电模拟器 9 支持（ldconsole locate + ADB mock location）
- 高德地图 API 真实道路路线搜索
- OpenStreetMap 交互式全国地图
- 鼠标点击手绘跑步路线
- 配速/距离/时间 三者联动计算器
- Google Play Services 兼容适配

### 🛠 开发者工具
- PyInstaller 一键打包为单文件 .exe
- CLI 调试模式（`python main.py --cli`）
- 旧版 UI 保留下（`--legacy` / `--classic`）

---

## v0.4 (2026-07-30) — GPS 引擎 + GPX 导出

### 新增
- OU 漂移（Ornstein-UhlenbeckDrift）替代简单高斯噪声
- SmoothSpeedController 平滑速度过渡
- GPSInjectStrategy 起步爆发注入
- NMEASimulator 卫星数据仿真
- StepCadenceSimulator 步频计算
- GPX 导入/导出支持
- 实时 GPS 诊断面板（卫星数、精度、步频、步幅）

---

## v0.3 (2026-07-30) — 交互式地图 + 手绘路线

### 新增
- tkintermapview 集成 OpenStreetMap 全国地图
- 鼠标点击手绘跑步路线
- 搜索地址跳转
- 右键撤销、清除、完成路线
- 瓦片服务器切换（CartoDB Lite / OSM / OSM France）

---

## v0.2 (2026-07-30) — 高德地图 + 配速联动

### 新增
- 高德地图 Web API 路线搜索（步行/骑行/环形）
- PaceCalculator 配速/距离/时间 三者联动
- PyInstaller 一键打包脚本

---

## v0.1 (2026-07-30) — MVP 雏形

### 核心
- ADB 客户端连接管理
- 3 层 GPS 注入策略（Emulator Console / LDPlayer / ADB Shell）
- 路线引擎（圆形/矩形/折返/校园跑道生成）
- GPS 模拟主循环
- Tkinter GUI 控制面板
