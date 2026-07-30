# 🏃 CampusRunner — 校园跑助手

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-blue" alt="version">
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-green" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="license">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey" alt="platform">
</p>

**CampusRunner** 是一款桌面端 GPS 位置模拟工具，专为雷电模拟器 9 设计。通过 ADB 向 Android 模拟器注入真实的 GPS 运动轨迹，配合 Keep 等运动 App 实现校园跑步模拟。

> ⚠️ **免责声明**：本工具仅供 GPS 定位技术学习和 Android 调试研究使用。请遵守学校规定和相关法律法规。

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 🗺 **交互式地图** | OpenStreetMap 全国地图，支持鼠标点击手绘跑步路线 |
| 🛰 **GPS 运动引擎** | OU 漂移算法、平滑变速、卫星星座仿真，模拟真实跑步 GPS 数据 |
| 📍 **高德路线搜索** | 接入高德 Web API，搜索真实道路步行/骑行路线 |
| 🎯 **配速联动** | 距离/配速/时间 三者联动，修改任意两个自动计算第三个 |
| 📊 **实时仪表盘** | KPI 数据卡片、速度折线图、路线完成进度环 |
| 📅 **打卡日历** | 深色对比日历组件，自动标记跑步打卡日期 |
| 📝 **历史记录** | 跑步历史列表，支持滚动查看，自动统计次数 |
| 💾 **路线持久化** | 保存/加载路线文件（JSON + GPX 格式） |
| 🔄 **循环模式** | 支持循环跑圈，跑完自动继续 |
| 🎨 **Soft UI** | 莫兰迪低饱和配色、奶米白底色、大圆角卡片、柔和阴影 |

---

## 📸 界面预览

```
┌─────────────┬──────────────────────────────────────────┐
│             │  👋 下午好, 开始今天的跑步吧         ● 已连接 │
│  🏃 Logo    ├──────────────────┬───────────────────────┤
│  CampusRunner│                  │   ┌────────────────┐  │
│             │  [ 交互式地图 ]   │   │  路线进度 62%   │  │
│  ⬤ 仪表盘   │                  │   │  ╭─────────╮   │  │
│    路线规划  │  🖱 点击手绘路线   │   │  3.1/5.0 km  │  │
│    打卡日历  │  🔍 高德搜索路线   │   └────────────────┘  │
│    设置      │  📂 加载/保存路线  │                       │
│             ├──────────────────┼───────────────────────┤
│  ● 已连接    │  实时速度折线图    │  📅 深色打卡日历      │
│             │  ╱‾‾‾╲   ╱╲      │  莫兰迪深蓝对比卡片   │
│  v1.0       │ ╱     ╲‾╱  ╲     │  已打卡日蓝色高亮     │
│             ├──────────────────┴───────────────────────┤
│             │ 目标[5.0]km 配速[6'00"] ≈30:00  ☑循环   │
│             │ [▶ 开始跑步] [⏸] [■] [生成][保存][加载] │
└─────────────┴──────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 环境要求

- **Windows 10/11**
- **Python 3.11 ~ 3.13**
- **雷电模拟器 9**（或其他 Android 模拟器）
- **ADB**（Android Debug Bridge）

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/CampusRunner.git
cd CampusRunner

# 2. 安装依赖
pip install customtkinter tkintermapview

# 3. 启动
python main.py
```

### 打包为 EXE

```bash
python build_exe.py
# 输出: dist/CampusRunner.exe (~37 MB)
```

---

## 📋 使用步骤

### 第一步：启动模拟器

1. 打开雷电模拟器 9
2. 确保已开启 **开发者选项** → **USB 调试**
3. 确保已安装 **Google Play Services**（雷电设置 → 其他设置 → 启用 Google Play 商店）

### 第二步：连接 CampusRunner

1. 双击 `CampusRunner.exe` 或运行 `python main.py`
2. 点击底部「连接模拟器」按钮
3. 连接成功后侧边栏显示「● 已连接」

### 第三步：规划路线

三种方式任选：

- **手绘路线**：地图工具栏点「✏ 绘制路线」→ 在地图上点击添加路径点 → 点「✓ 完成路线」
- **高德搜索**：底部控制栏输入起点和终点坐标 → 点「搜索路线」（需要配置 API Key）
- **快速生成**：点「生成跑道」自动创建 2km 校园跑道

### 第四步：设置目标

- 在底部控制栏输入目标**距离**（km）和**配速**（min/km）
- 预估时间自动计算并显示
- 速度折线图上会显示目标配速参考虚线

### 第五步：开始跑步

1. 在模拟器中打开 Keep App，进入跑步页面
2. 回到 CampusRunner，点「▶ 开始跑步」
3. 观察 KPI 面板实时更新：距离、时间、配速、速度
4. 折线图显示实时速度曲线，环形进度显示路线完成百分比

### 第六步：结束跑步

- 点「■」停止，自动在打卡日历上标记当天日期
- 跑步记录自动添加到历史列表

---

## ⚙ 配置说明

编辑 `config.json`：

```json
{
  "adb_path": "D:/op/adb.exe",          // ADB 路径
  "device_addr": "emulator-5554",       // 模拟器 ADB 地址
  "emulator_console_port": 5554,        // 控制台端口
  "ldplayer_path": "D:/leidian/LDPlayer9", // 雷电安装目录
  "amap_api_key": "",                   // 高德 API Key (可选)
  "center_lat": 39.9923,               // 默认地图中心纬度
  "center_lng": 116.3264,              // 默认地图中心经度
  "update_interval_ms": 1500,          // GPS 更新间隔(毫秒)
  "gps_jitter_meters": 2.0            // GPS 抖动幅度(米)
}
```

### 高德 API Key 申请

1. 访问 [高德开放平台](https://console.amap.com/dev/key/app)
2. 创建应用 → 选择「Web 服务」
3. 获取 Key → 填入 config.json 的 `amap_api_key`

---

## 🏗 项目结构

```
CampusRunner/
├── main.py                   # 入口 (GUI + CLI)
├── build_exe.py              # PyInstaller 打包脚本
├── pyproject.toml            # 项目元数据
├── config.json               # 用户配置
│
├── core/                     # 核心引擎
│   ├── adb_client.py         # ADB 连接管理
│   ├── location_injector.py  # GPS 注入策略 (3层)
│   ├── route_engine.py       # 路线生成/加载/插值
│   ├── simulator.py          # GPS 模拟主循环
│   ├── map_api.py            # 高德地图 API
│   ├── pace_calculator.py    # 配速联动计算器
│   └── gps_engine.py         # OU 漂移/平滑变速/卫星仿真
│
├── gui/                      # 用户界面
│   ├── soft_ui.py            # Soft UI 仪表盘 (v1.0 默认)
│   ├── dashboard.py          # 深色仪表盘 (v0.4)
│   ├── main_window.py        # 旧版界面 (v0.1)
│   ├── map_view.py           # 交互式地图组件
│   └── widgets.py            # UI 组件库
│
├── routes/                   # 路线文件
│   └── sample_campus.json    # 样例路线
│
└── release/                  # 发布目录
    ├── CampusRunner.exe      # 打包好的可执行文件
    ├── config.json           # 配置模板
    └── routes/               # 路线文件夹
```

---

## 🔧 命令行模式

```bash
# 测试 ADB 连接
python main.py --cli test-adb

# 测试 GPS 单点注入
python main.py --cli inject 39.9923 116.3264

# 生成路线预览
python main.py --cli route 39.9923 116.3264 --distance 2000

# 使用旧版 UI
python main.py --legacy
python main.py --classic
```

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing`)
5. 创建 Pull Request

---

## 📄 许可

MIT License © 2026 CampusRunner Contributors

详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

- [customtkinter](https://github.com/TomSchimansky/CustomTkinter) — 现代 Tkinter UI 框架
- [tkintermapview](https://github.com/TomSchimansky/TkinterMapView) — Tkinter 地图组件
- [LocationSpoofer](https://github.com/HuangZhuoRui/LocationSpoofer) — OU 漂移 + NMEA 仿真参考
- [Modify_Positioning](https://github.com/AuroraNest/Modify_Positioning) — 多 Provider 注入参考
- [FakeLocation](https://github.com/Lerist/FakeLocation) — 速度分级参考
- [高德开放平台](https://lbs.amap.com/) — 路线搜索 API
