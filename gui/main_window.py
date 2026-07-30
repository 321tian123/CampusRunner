"""
校园跑助手 - Tkinter GUI 控制面板

布局：
┌──────────────────────────────────────────────┐
│  菜单栏: 文件 | 路线 | 帮助                     │
├───────────────────────┬──────────────────────┤
│                      │  [连接状态]            │
│   路线地图预览         │  ──────────────────   │
│   (Canvas)           │  速度: 10 km/h        │
│                      │  [=====o=====]        │
│   红色: 路线           │                       │
│   蓝点: 当前位置        │  已跑: 1.23 / 5.00 km│
│   灰线: 已跑轨迹        │  用时: 00:04:23       │
│                      │  配速: 05'30"/km       │
│                      │  圈数: 2               │
│                      │                       │
│                      │  [▶ 开始] [⏸ 暂停]   │
│                      │  [■ 停止] [↻ 重置]    │
│                      │                       │
│                      │  路线: 校园标准跑道      │
│                      │  [生成路线...]          │
│                      │  [加载路线...]          │
├───────────────────────┴──────────────────────┤
│  日志输出区域                                 │
└──────────────────────────────────────────────┘
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import logging
import json
import os
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.adb_client import ADBClient
from core.location_injector import LocationInjector
from core.route_engine import Route, RouteGenerator, Waypoint
from core.simulator import Simulator, RunState, ProgressInfo
from core.map_api import AmapRoutePlanner
from core.pace_calculator import PaceCalculator
from gui.map_view import InteractiveMapView


# ─── 日志处理器（将 logging 输出重定向到 GUI） ────────


class GuiLogHandler(logging.Handler):
    """将 Python logging 输出到 Tkinter 文本框"""

    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                             datefmt="%H:%M:%S"))

    def emit(self, record):
        msg = self.format(record)
        # Tkinter 不是线程安全的，使用 after 回到主线程
        try:
            self.text_widget.after(0, self._append, msg)
        except Exception:
            pass

    def _append(self, msg):
        try:
            self.text_widget.insert(tk.END, msg + "\n")
            self.text_widget.see(tk.END)
        except Exception:
            pass


# ─── 主窗口 ────────────────────────────────────────────


def _get_base_path():
    """获取项目根目录（兼容 dev 和 PyInstaller 打包）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


class MainWindow:
    """校园跑助手主窗口"""

    CONFIG_PATH = _get_base_path() / "config.json"
    ROUTES_DIR = _get_base_path() / "routes"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CampusRunner - 校园跑助手 v0.1")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)
        self.root.configure(bg="#1e1e1e")

        # 加载配置
        self._config = self._load_config()

        # 核心组件（延迟初始化）
        self._adb: Optional[ADBClient] = None
        self._injector: Optional[LocationInjector] = None
        self._route: Optional[Route] = None
        self._simulator: Optional[Simulator] = None

        # GUI 变量
        self._speed_var = tk.DoubleVar(value=self._config.get("default_speed_kmh", 10))
        self._update_interval_var = tk.IntVar(value=self._config.get("update_interval_ms", 1500))
        self._jitter_var = tk.DoubleVar(value=self._config.get("gps_jitter_meters", 3.0))
        self._loop_var = tk.BooleanVar(value=False)
        self._adb_path_var = tk.StringVar(value=self._config.get("adb_path", "D:/op/adb.exe"))
        self._device_addr_var = tk.StringVar(value=self._config.get("device_addr", "127.0.0.1:5555"))
        self._console_port_var = tk.IntVar(value=self._config.get("emulator_console_port", 5554))
        self._center_lat_var = tk.StringVar(value=str(self._config.get("center_lat", "39.9923")))
        self._center_lng_var = tk.StringVar(value=str(self._config.get("center_lng", "116.3264")))
        self._route_distance_var = tk.StringVar(value="2000")
        self._route_name_var = tk.StringVar(value="校园标准跑道")
        self._connected = False

        # 高德地图 API 变量
        self._amap_key_var = tk.StringVar(value=self._config.get("amap_api_key", ""))
        self._amap_origin_var = tk.StringVar(value=self._config.get("default_origin", ""))
        self._amap_dest_var = tk.StringVar(value=self._config.get("default_destination", ""))
        self._amap_mode_var = tk.StringVar(value="walking")
        self._amap_planner: Optional[AmapRoutePlanner] = None

        # 配速联动计算器
        default_pace = 60.0 / self._config.get("default_speed_kmh", 10)  # 10km/h → 6min/km
        self._pace_calc = PaceCalculator(
            distance_km=float(self._route_distance_var.get()) / 1000.0,
            pace_min_per_km=default_pace,
        )
        self._pace_distance_var = tk.StringVar(value=f"{self._pace_calc.distance_km:.2f}")
        self._pace_pace_min_var = tk.StringVar(value=str(int(self._pace_calc.pace_min_per_km)))
        self._pace_pace_sec_var = tk.StringVar(value=f"{int((self._pace_calc.pace_min_per_km % 1) * 60):02d}")
        self._pace_updating = False  # 防止联动递归

        self._build_ui()
        self._setup_logging()

        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── 配置管理 ──────────────────────────────────────

    def _load_config(self) -> dict:
        """加载配置文件"""
        if self.CONFIG_PATH.exists():
            try:
                with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_config(self):
        """保存配置"""
        config = {
            "adb_path": self._adb_path_var.get(),
            "device_addr": self._device_addr_var.get(),
            "emulator_console_port": self._console_port_var.get(),
            "default_speed_kmh": self._speed_var.get(),
            "update_interval_ms": self._update_interval_var.get(),
            "gps_jitter_meters": self._jitter_var.get(),
            "center_lat": self._center_lat_var.get(),
            "center_lng": self._center_lng_var.get(),
            "amap_api_key": self._amap_key_var.get(),
            "default_origin": self._amap_origin_var.get(),
            "default_destination": self._amap_dest_var.get(),
        }
        try:
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ─── UI 构建 ───────────────────────────────────────

    def _build_ui(self):
        """构建主界面"""
        # 配色
        bg_dark = "#1e1e1e"
        bg_panel = "#2d2d2d"
        fg_text = "#cccccc"
        accent = "#3498db"
        accent_green = "#2ecc71"
        accent_red = "#e74c3c"
        accent_yellow = "#f39c12"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=bg_dark)
        style.configure("TLabelframe", background=bg_dark, foreground=fg_text)
        style.configure("TLabelframe.Label", background=bg_dark, foreground=fg_text)
        style.configure("TLabel", background=bg_dark, foreground=fg_text)
        style.configure("TButton", background=bg_panel, foreground=fg_text)
        style.configure("TScale", background=bg_dark)

        # ── 主容器 ──
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        main_frame = ttk.Frame(self.root)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        main_frame.grid_columnconfigure(0, weight=3)  # 地图
        main_frame.grid_columnconfigure(1, weight=1)  # 面板
        main_frame.grid_rowconfigure(0, weight=1)

        # ── 左侧：地图预览 ──
        map_frame = ttk.LabelFrame(main_frame, text="路线预览")
        map_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        map_frame.grid_rowconfigure(0, weight=1)
        map_frame.grid_columnconfigure(0, weight=1)

        self._map_view = InteractiveMapView(
            map_frame, width=750, height=500,
            default_lat=float(self._center_lat_var.get()),
            default_lng=float(self._center_lng_var.get()),
        )
        self._map_view.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
        # 手绘路线完成回调 → 直接作为跑步路线
        self._map_view.set_on_route_finished(self._on_hand_drawn_route)

        # ── 右侧：控制面板 ──
        right_frame = ttk.Frame(main_frame)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.grid_rowconfigure(0, weight=0)  # 连接
        right_frame.grid_rowconfigure(1, weight=0)  # 路线
        right_frame.grid_rowconfigure(2, weight=0)  # 控制
        right_frame.grid_rowconfigure(3, weight=0)  # 统计
        right_frame.grid_columnconfigure(0, weight=1)

        row_idx = 0

        # 连接设置
        conn_frame = ttk.LabelFrame(right_frame, text="连接设置")
        conn_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 5))
        row_idx += 1

        ttk.Label(conn_frame, text="ADB 路径:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(conn_frame, textvariable=self._adb_path_var, width=28).grid(
            row=1, column=0, sticky="ew", padx=5, pady=1
        )
        ttk.Button(conn_frame, text="浏览...", command=self._browse_adb, width=8).grid(
            row=1, column=1, padx=2
        )

        ttk.Label(conn_frame, text="设备地址:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(conn_frame, textvariable=self._device_addr_var, width=28).grid(
            row=3, column=0, sticky="ew", padx=5, pady=1
        )

        ttk.Label(conn_frame, text="控制台端口:").grid(row=4, column=0, sticky="w", padx=5, pady=2)
        ttk.Spinbox(conn_frame, from_=1024, to=65535, textvariable=self._console_port_var, width=10).grid(
            row=5, column=0, sticky="w", padx=5, pady=1
        )

        self._conn_btn = tk.Button(
            conn_frame, text="🔗 连接模拟器", bg=accent, fg="white",
            font=("Microsoft YaHei", 10, "bold"), relief="flat",
            command=self._toggle_connection, cursor="hand2", height=2,
        )
        self._conn_btn.grid(row=6, column=0, columnspan=2, sticky="ew", padx=5, pady=8)

        self._conn_status = tk.Label(
            conn_frame, text="⚫ 未连接", bg=bg_dark, fg="#888888",
            font=("Microsoft YaHei", 9)
        )
        self._conn_status.grid(row=7, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # ── 路线搜索（高德地图 API）──
        amap_frame = ttk.LabelFrame(right_frame, text="路线搜索 (高德地图)")
        amap_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 5))
        row_idx += 1

        ttk.Label(amap_frame, text="API Key:").grid(row=0, column=0, sticky="w", padx=5, pady=1)
        key_row = tk.Frame(amap_frame, bg=bg_dark)
        key_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=1)
        ttk.Entry(key_row, textvariable=self._amap_key_var, width=22, show="*").pack(
            side="left", fill="x", expand=True
        )
        tk.Button(
            key_row, text="👁", bg=bg_panel, fg=fg_text, relief="flat",
            command=lambda: self._toggle_api_key_visibility(key_row.winfo_children()[0]),
            cursor="hand2", width=3, font=("", 8),
        ).pack(side="right", padx=2)

        ttk.Label(amap_frame, text="起点:").grid(row=2, column=0, sticky="w", padx=5, pady=1)
        origin_row = tk.Frame(amap_frame, bg=bg_dark)
        origin_row.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=1)
        ttk.Entry(origin_row, textvariable=self._amap_origin_var, width=20).pack(
            side="left", fill="x", expand=True
        )
        tk.Button(
            origin_row, text="📍", bg=bg_panel, fg=fg_text, relief="flat",
            command=self._pick_origin_from_map, cursor="hand2", width=3,
        ).pack(side="right", padx=2)

        ttk.Label(amap_frame, text="终点:").grid(row=4, column=0, sticky="w", padx=5, pady=1)
        dest_row = tk.Frame(amap_frame, bg=bg_dark)
        dest_row.grid(row=5, column=0, columnspan=2, sticky="ew", padx=5, pady=1)
        ttk.Entry(dest_row, textvariable=self._amap_dest_var, width=20).pack(
            side="left", fill="x", expand=True
        )
        tk.Button(
            dest_row, text="📍", bg=bg_panel, fg=fg_text, relief="flat",
            command=self._pick_dest_from_map, cursor="hand2", width=3,
        ).pack(side="right", padx=2)

        mode_row = tk.Frame(amap_frame, bg=bg_dark)
        mode_row.grid(row=6, column=0, columnspan=2, sticky="ew", padx=5, pady=3)
        ttk.Radiobutton(mode_row, text="步行", variable=self._amap_mode_var, value="walking").pack(side="left", padx=2)
        ttk.Radiobutton(mode_row, text="骑行", variable=self._amap_mode_var, value="cycling").pack(side="left", padx=2)
        ttk.Radiobutton(mode_row, text="环形", variable=self._amap_mode_var, value="loop").pack(side="left", padx=2)

        amap_btn_row = tk.Frame(amap_frame, bg=bg_dark)
        amap_btn_row.grid(row=7, column=0, columnspan=2, sticky="ew", padx=5, pady=4)
        tk.Button(
            amap_btn_row, text="🗺 搜索路线", bg="#e67e22", fg="white",
            font=("Microsoft YaHei", 9, "bold"), relief="flat",
            command=self._search_amap_route, cursor="hand2",
        ).pack(side="left", fill="x", expand=True, padx=1)
        tk.Button(
            amap_btn_row, text="🔄 反方向", bg=bg_panel, fg=fg_text, relief="flat",
            command=self._swap_origin_dest, cursor="hand2",
        ).pack(side="left", padx=1)

        self._amap_status = tk.Label(
            amap_frame, text="", bg=bg_dark, fg="#888888",
            font=("Microsoft YaHei", 8)
        )
        self._amap_status.grid(row=8, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # ── 目标设置（配速联动）──
        pace_frame = ttk.LabelFrame(right_frame, text="目标设置")
        pace_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 5))
        row_idx += 1

        # 距离
        dist_row = tk.Frame(pace_frame, bg=bg_dark)
        dist_row.pack(fill="x", padx=5, pady=2)
        tk.Label(dist_row, text="距离:", bg=bg_dark, fg=fg_text, width=6, anchor="w").pack(side="left")
        tk.Entry(dist_row, textvariable=self._pace_distance_var, width=8,
                 justify="right").pack(side="left", padx=3)
        tk.Label(dist_row, text="km", bg=bg_dark, fg="#888888").pack(side="left")
        self._pace_distance_var.trace_add("write", lambda *_: self._on_pace_param_changed("distance"))

        # 配速
        pace_row = tk.Frame(pace_frame, bg=bg_dark)
        pace_row.pack(fill="x", padx=5, pady=2)
        tk.Label(pace_row, text="配速:", bg=bg_dark, fg=fg_text, width=6, anchor="w").pack(side="left")
        tk.Entry(pace_row, textvariable=self._pace_pace_min_var, width=4,
                 justify="right").pack(side="left", padx=1)
        tk.Label(pace_row, text="'", bg=bg_dark, fg=fg_text).pack(side="left")
        tk.Entry(pace_row, textvariable=self._pace_pace_sec_var, width=3,
                 justify="right").pack(side="left")
        tk.Label(pace_row, text="\"/km", bg=bg_dark, fg=fg_text).pack(side="left")
        self._pace_pace_min_var.trace_add("write", lambda *_: self._on_pace_param_changed("pace"))
        self._pace_pace_sec_var.trace_add("write", lambda *_: self._on_pace_param_changed("pace"))

        # 时间（只读显示）
        time_row = tk.Frame(pace_frame, bg=bg_dark)
        time_row.pack(fill="x", padx=5, pady=2)
        tk.Label(time_row, text="时间:", bg=bg_dark, fg=fg_text, width=6, anchor="w").pack(side="left")
        self._pace_time_label = tk.Label(
            time_row, text=self._pace_calc.time_str, bg=bg_dark, fg=accent,
            font=("Consolas", 10, "bold"), width=10, anchor="e"
        )
        self._pace_time_label.pack(side="left", padx=3)
        tk.Label(time_row, text="", bg=bg_dark, fg="#888888").pack(side="left")

        # 速度显示
        speed_disp_row = tk.Frame(pace_frame, bg=bg_dark)
        speed_disp_row.pack(fill="x", padx=5, pady=2)
        tk.Label(speed_disp_row, text="速度:", bg=bg_dark, fg=fg_text, width=6, anchor="w").pack(side="left")
        self._pace_speed_label = tk.Label(
            speed_disp_row, text=self._pace_calc.speed_str, bg=bg_dark, fg=accent_green,
            font=("Consolas", 10, "bold")
        )
        self._pace_speed_label.pack(side="left", padx=3)

        # 路线设置
        route_frame = ttk.LabelFrame(right_frame, text="路线设置")
        route_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 5))
        row_idx += 1

        ttk.Label(route_frame, text="中心纬度:").grid(row=0, column=0, sticky="w", padx=5, pady=1)
        ttk.Entry(route_frame, textvariable=self._center_lat_var, width=14).grid(
            row=0, column=1, sticky="e", padx=5, pady=1
        )

        ttk.Label(route_frame, text="中心经度:").grid(row=1, column=0, sticky="w", padx=5, pady=1)
        ttk.Entry(route_frame, textvariable=self._center_lng_var, width=14).grid(
            row=1, column=1, sticky="e", padx=5, pady=1
        )

        ttk.Label(route_frame, text="距离(米):").grid(row=2, column=0, sticky="w", padx=5, pady=1)
        ttk.Entry(route_frame, textvariable=self._route_distance_var, width=14).grid(
            row=2, column=1, sticky="e", padx=5, pady=1
        )

        btn_row = tk.Frame(route_frame, bg=bg_dark)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

        tk.Button(
            btn_row, text="🎯 生成路线", bg=accent_green, fg="white",
            relief="flat", command=self._generate_route, cursor="hand2",
        ).pack(side="left", fill="x", expand=True, padx=1)

        tk.Button(
            btn_row, text="📂 加载路线", bg=bg_dark, fg=fg_text,
            relief="flat", command=self._load_route, cursor="hand2",
        ).pack(side="left", fill="x", expand=True, padx=1)

        # 控制面板
        ctrl_frame = ttk.LabelFrame(right_frame, text="运动控制")
        ctrl_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 5))
        row_idx += 1

        # 速度滑块
        speed_row = tk.Frame(ctrl_frame, bg=bg_dark)
        speed_row.pack(fill="x", padx=5, pady=5)

        tk.Label(speed_row, text="速度:", bg=bg_dark, fg=fg_text, font=("Microsoft YaHei", 9)).pack(side="left")
        self._speed_label = tk.Label(
            speed_row, text="10 km/h", bg=bg_dark, fg=accent,
            font=("Microsoft YaHei", 10, "bold")
        )
        self._speed_label.pack(side="right")

        self._speed_scale = tk.Scale(
            ctrl_frame, from_=2, to=20, resolution=0.5, orient="horizontal",
            variable=self._speed_var, bg=bg_dark, fg=fg_text,
            highlightthickness=0, troughcolor=bg_panel,
            command=self._on_speed_slider_changed,
        )
        self._speed_scale.pack(fill="x", padx=5)

        # 高级设置
        adv_frame = tk.Frame(ctrl_frame, bg=bg_dark)
        adv_frame.pack(fill="x", padx=5, pady=2)

        tk.Label(adv_frame, text="更新间隔:", bg=bg_dark, fg=fg_text, font=("Microsoft YaHei", 8)).pack(side="left")
        ttk.Spinbox(adv_frame, from_=500, to=5000, increment=100, textvariable=self._update_interval_var, width=6).pack(
            side="left", padx=3
        )
        tk.Label(adv_frame, text="ms", bg=bg_dark, fg="#888888", font=("Microsoft YaHei", 8)).pack(side="left")

        tk.Label(adv_frame, text="  抖动:", bg=bg_dark, fg=fg_text, font=("Microsoft YaHei", 8)).pack(side="left")
        ttk.Spinbox(adv_frame, from_=0, to=20, increment=0.5, textvariable=self._jitter_var, width=5).pack(
            side="left", padx=3
        )
        tk.Label(adv_frame, text="m", bg=bg_dark, fg="#888888", font=("Microsoft YaHei", 8)).pack(side="left")

        ttk.Checkbutton(adv_frame, text="循环", variable=self._loop_var).pack(side="right", padx=5)

        # 按钮
        btn_frame = tk.Frame(ctrl_frame, bg=bg_dark)
        btn_frame.pack(fill="x", padx=5, pady=8)

        self._start_btn = tk.Button(
            btn_frame, text="▶  开始跑步", bg=accent_green, fg="white",
            font=("Microsoft YaHei", 10, "bold"), relief="flat",
            command=self._start_simulation, cursor="hand2", height=2,
        )
        self._start_btn.pack(side="left", fill="x", expand=True, padx=1)

        self._pause_btn = tk.Button(
            btn_frame, text="⏸  暂停", bg=accent_yellow, fg="white",
            font=("Microsoft YaHei", 10, "bold"), relief="flat",
            command=self._toggle_pause, cursor="hand2", height=2, state="disabled",
        )
        self._pause_btn.pack(side="left", fill="x", expand=True, padx=1)

        self._stop_btn = tk.Button(
            btn_frame, text="■  停止", bg=accent_red, fg="white",
            font=("Microsoft YaHei", 10, "bold"), relief="flat",
            command=self._stop_simulation, cursor="hand2", height=2, state="disabled",
        )
        self._stop_btn.pack(side="left", fill="x", expand=True, padx=1)

        # 统计数据显示
        stats_frame = ttk.LabelFrame(right_frame, text="运动数据")
        stats_frame.grid(row=row_idx, column=0, sticky="ew")
        row_idx += 1

        self._stats_text = tk.Text(
            stats_frame, height=8, width=32, bg=bg_panel, fg=fg_text,
            font=("Consolas", 10), relief="flat", borderwidth=0,
            state="disabled", wrap="word",
        )
        self._stats_text.pack(fill="both", padx=5, pady=5)

        # ── 底部：日志 ──
        log_frame = ttk.LabelFrame(self.root, text="运行日志")
        log_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5))

        self._log_text = scrolledtext.ScrolledText(
            log_frame, height=6, bg="#111111", fg="#aaaaaa",
            font=("Consolas", 9), relief="flat",
        )
        self._log_text.pack(fill="both", expand=True, padx=3, pady=3)

    # ─── 日志设置 ──────────────────────────────────────

    def _setup_logging(self):
        """配置日志"""
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        # 清除现有 handler
        logger.handlers.clear()

        # GUI handler
        gui_handler = GuiLogHandler(self._log_text)
        logger.addHandler(gui_handler)

        # 初始日志
        logging.info("CampusRunner v0.1 已启动")
        logging.info(f"配置文件: {self.CONFIG_PATH}")

    # ─── ADB 连接 ──────────────────────────────────────

    def _toggle_connection(self):
        """切换连接/断开"""
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        """连接模拟器"""
        adb_path = self._adb_path_var.get().strip()
        device_addr = self._device_addr_var.get().strip()

        if not adb_path:
            messagebox.showwarning("警告", "请先设置 ADB 路径")
            return

        self._adb = ADBClient(adb_path=adb_path, device_addr=device_addr)

        # 在后台线程中连接
        def do_connect():
            success = self._adb.connect()
            self.root.after(0, self._on_connect_result, success)

        threading.Thread(target=do_connect, daemon=True).start()
        self._conn_btn.configure(text="⏳ 连接中...", state="disabled")

    def _on_connect_result(self, success: bool):
        """连接结果回调（主线程）"""
        if success:
            self._connected = True
            self._conn_btn.configure(text="🔌 断开连接", bg="#e74c3c", state="normal")
            self._conn_status.configure(text="🟢 已连接", fg="#2ecc71")

            # 获取设备信息
            if self._adb:
                android_ver = self._adb.get_android_version() or "Unknown"
                model = self._adb.get_device_model() or "Unknown"
                logging.info(f"已连接: {model} (Android {android_ver})")

            # 初始化注入器
            self._setup_injector()

            # 保存配置
            self._save_config()

            # 更新控制按钮
            self._start_btn.configure(state="normal")
        else:
            self._conn_btn.configure(text="🔗 连接模拟器", bg="#3498db", state="normal")
            self._conn_status.configure(text="🔴 连接失败", fg="#e74c3c")
            logging.error("连接失败，请检查 ADB 路径和模拟器是否启动")

    def _disconnect(self):
        """断开连接"""
        if self._simulator:
            self._simulator.stop()

        if self._injector:
            self._injector.disconnect()

        if self._adb:
            self._adb.disconnect()

        self._connected = False
        self._conn_btn.configure(text="🔗 连接模拟器", bg="#3498db")
        self._conn_status.configure(text="⚫ 未连接", fg="#888888")
        self._start_btn.configure(state="disabled")
        self._pause_btn.configure(state="disabled")
        self._stop_btn.configure(state="disabled")
        logging.info("已断开连接")

    def _setup_injector(self):
        """初始化 GPS 注入器"""
        self._injector = LocationInjector(
            adb_path=self._adb_path_var.get().strip(),
            host="127.0.0.1",
            console_port=self._console_port_var.get(),
            device_serial=self._device_addr_var.get().strip(),
        )

        # 在后台线程中连接
        def do_setup():
            success = self._injector.auto_connect()
            if success:
                self.root.after(0, lambda: logging.info(f"GPS 注入器就绪: {self._injector.active_injector_name}"))
            else:
                self.root.after(0, lambda: logging.warning("GPS 注入器连接失败，请检查模拟器设置"))

        threading.Thread(target=do_setup, daemon=True).start()

    # ─── 路线管理 ──────────────────────────────────────

    def _on_hand_drawn_route(self, route: Route):
        """手绘路线完成回调 - 将手绘路线设为当前跑步路线"""
        self._route = route

        # 更新中心坐标
        if route.waypoints:
            lats = [wp.lat for wp in route.waypoints]
            lngs = [wp.lng for wp in route.waypoints]
            self._center_lat_var.set(f"{(min(lats)+max(lats))/2:.6f}")
            self._center_lng_var.set(f"{(min(lngs)+max(lngs))/2:.6f}")

        # 同步距离到配速计算器
        dist_km = route.total_distance_m / 1000.0
        self._pace_calc.set_all(dist_km, self._pace_calc.pace_min_per_km)
        self._update_pace_display()

        self._update_stats()
        self._save_config()
        logging.info(f"手绘路线已就绪: {route.name}, {route.total_distance_m:.0f}m")

    def _generate_route(self):
        """生成校园路线"""
        try:
            center_lat = float(self._center_lat_var.get())
            center_lng = float(self._center_lng_var.get())
            distance = float(self._route_distance_var.get())
        except ValueError:
            messagebox.showwarning("警告", "请输入有效的经纬度数值")
            return

        self._route = RouteGenerator.generate_campus_default(
            center_lat=center_lat,
            center_lng=center_lng,
            total_distance_m=distance,
            name="校园标准跑道",
        )

        # 应用抖动
        jitter = self._jitter_var.get()
        if jitter > 0:
            self._route = RouteGenerator.add_gps_jitter(self._route, jitter_meters=jitter)

        self._map_view.show_route(self._route)
        logging.info(f"已生成路线: {self._route.name} (总长 {self._route.total_distance_m:.0f}m, "
                     f"{self._route.point_count} 个路径点)")

        # 同步距离到配速计算器
        dist_km = self._route.total_distance_m / 1000.0
        self._pace_calc.set_all(dist_km, self._pace_calc.pace_min_per_km)
        self._update_pace_display()

        self._update_stats()

    def _load_route(self):
        """从文件加载路线"""
        filepath = filedialog.askopenfilename(
            title="加载路线文件",
            filetypes=[
                ("路线文件", "*.json;*.gpx"),
                ("JSON 文件", "*.json"),
                ("GPX 文件", "*.gpx"),
                ("所有文件", "*.*"),
            ],
            initialdir=Path(__file__).parent.parent / "routes",
        )

        if not filepath:
            return

        route = RouteGenerator.load_from_file(filepath)
        if route is None:
            messagebox.showerror("错误", "加载路线文件失败，请检查文件格式")
            return

        self._route = route
        self._map_view.set_route(route)

        # 更新中心坐标
        if route.waypoints:
            center_lat = sum(wp.lat for wp in route.waypoints) / len(route.waypoints)
            center_lng = sum(wp.lng for wp in route.waypoints) / len(route.waypoints)
            self._center_lat_var.set(f"{center_lat:.6f}")
            self._center_lng_var.set(f"{center_lng:.6f}")

        logging.info(f"已加载路线: {route.name} ({route.point_count} 个路径点, "
                     f"总长 {route.total_distance_m:.0f}m)")

        # 同步距离到配速计算器
        dist_km = route.total_distance_m / 1000.0
        self._pace_calc.set_all(dist_km, self._pace_calc.pace_min_per_km)
        self._update_pace_display()

        self._update_stats()

    # ─── 模拟控制 ──────────────────────────────────────

    def _start_simulation(self):
        """开始模拟"""
        if self._simulator and self._simulator.state == RunState.RUNNING:
            return

        if self._route is None:
            messagebox.showwarning("警告", "请先生成或加载路线")
            return

        if self._injector is None:
            messagebox.showwarning("警告", "请先连接模拟器")
            return

        # 创建或重置模拟器
        if self._simulator is None:
            self._simulator = Simulator(
                injector=self._injector,
                route=self._route,
                speed_kmh=self._pace_calc.speed_kmh,  # 使用配速计算器的速度
                update_interval_ms=self._update_interval_var.get(),
                jitter_meters=self._jitter_var.get(),
                loop_mode=self._loop_var.get(),
            )
            # 注册回调
            self._simulator.on_progress(self._on_progress_update)
            self._simulator.on_state_change(self._on_simulator_state_change)
        else:
            self._simulator.route = self._route
            self._simulator.speed_kmh = self._pace_calc.speed_kmh

        # 更新循环模式
        self._simulator._loop_mode = self._loop_var.get()

        if not self._simulator.start():
            return

        logging.info(f"开始跑步! 路线={self._route.name}, 速度={self._speed_var.get()}km/h")

        # 更新按钮状态
        self._start_btn.configure(state="disabled")
        self._pause_btn.configure(state="normal", text="⏸  暂停")
        self._stop_btn.configure(state="normal")
        self._conn_btn.configure(state="disabled")

        # 禁用编辑
        self._speed_scale.configure(state="disabled")

    def _toggle_pause(self):
        """切换暂停/继续"""
        if self._simulator is None:
            return

        self._simulator.toggle_pause()

    def _stop_simulation(self):
        """停止模拟"""
        if self._simulator is None:
            return

        self._simulator.stop()
        logging.info("跑步已停止")

        # 恢复按钮
        self._start_btn.configure(state="normal")
        self._pause_btn.configure(state="disabled", text="⏸  暂停")
        self._stop_btn.configure(state="disabled")
        self._conn_btn.configure(state="normal")

        # 恢复编辑
        self._speed_scale.configure(state="normal")

    # ─── 回调处理 ──────────────────────────────────────

    def _on_progress_update(self, info: ProgressInfo):
        """进度更新（来自模拟线程）"""
        # 使用 after 回到主线程更新 UI
        self.root.after(0, self._update_ui_from_progress, info)

    def _on_simulator_state_change(self, old_state: RunState, new_state: RunState):
        """状态变化（来自模拟线程）"""
        self.root.after(0, self._update_ui_for_state, old_state, new_state)

    def _update_ui_from_progress(self, info: ProgressInfo):
        """主线程中更新 UI"""
        # 更新统计
        self._update_stats_display(info)

        # 更新地图位置
        if self._route:
            self._map_view.update_current_position(
                info.current_lat, info.current_lng
            )

    def _update_ui_for_state(self, old_state: RunState, new_state: RunState):
        """主线程中更新按钮状态"""
        if new_state == RunState.RUNNING:
            self._pause_btn.configure(state="normal", text="⏸  暂停")
        elif new_state == RunState.PAUSED:
            self._pause_btn.configure(text="▶  继续")
        elif new_state == RunState.FINISHED:
            self._start_btn.configure(state="normal")
            self._pause_btn.configure(state="disabled", text="⏸  暂停")
            self._stop_btn.configure(state="disabled")
            self._conn_btn.configure(state="normal")
            self._speed_scale.configure(state="normal")
            logging.info("🏁 跑步完成!")

    def _update_stats(self):
        """更新统计显示（静态）"""
        if self._route is None:
            return

        self._stats_text.configure(state="normal")
        self._stats_text.delete("1.0", tk.END)
        self._stats_text.insert(tk.END, f"路线名称: {self._route.name}\n")
        self._stats_text.insert(tk.END, f"总距离:   {self._route.total_distance_m:.0f} 米\n")
        self._stats_text.insert(tk.END, f"路径点数: {self._route.point_count}\n")
        self._stats_text.insert(tk.END, "\n等待开始...\n")
        self._stats_text.configure(state="disabled")

    def _update_stats_display(self, info: ProgressInfo):
        """实时更新统计显示"""
        self._stats_text.configure(state="normal")
        self._stats_text.delete("1.0", tk.END)

        # 格式化时间
        elapsed = info.elapsed_sec
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # 格式化配速
        pace = info.pace_min_per_km
        if pace > 0:
            pace_min = int(pace)
            pace_sec = int((pace - pace_min) * 60)
            pace_str = f"{pace_min}'{pace_sec:02d}\"/km"
        else:
            pace_str = "--'--\"/km"

        lines = [
            f"状态:     {'▶ 运行中' if info.state == RunState.RUNNING else '⏸ 已暂停' if info.state == RunState.PAUSED else '🏁 已结束'}",
            f"路线:     {info.distance_m:.0f} / {info.total_m:.0f} m",
            f"进度:     {info.progress_pct:.1f}%",
            f"用时:     {time_str}",
            f"速度:     {info.current_speed_ms * 3.6:.1f} km/h",
            f"配速:     {pace_str}",
            f"圈数:     {info.laps}",
            f"位置:     {info.current_lat:.6f}, {info.current_lng:.6f}",
        ]

        if info.state == RunState.RUNNING:
            bar_len = 20
            filled = int(info.progress_pct / 100 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.insert(0, f"[{bar}]")

        for line in lines:
            self._stats_text.insert(tk.END, line + "\n")

        self._stats_text.configure(state="disabled")

    # ─── 高德地图 API 方法 ──────────────────────────────

    def _toggle_api_key_visibility(self, entry_widget):
        """切换 API Key 显示/隐藏"""
        if entry_widget.cget("show") == "*":
            entry_widget.configure(show="")
        else:
            entry_widget.configure(show="*")

    def _pick_origin_from_map(self):
        """从地图面板获取当前中心坐标作为起点"""
        lat = self._center_lat_var.get()
        lng = self._center_lng_var.get()
        self._amap_origin_var.set(f"{lng},{lat}")
        logging.info(f"起点已设置为当前中心: {lng},{lat}")

    def _pick_dest_from_map(self):
        """从地图面板获取当前中心坐标作为终点"""
        lat = self._center_lat_var.get()
        lng = self._center_lng_var.get()
        self._amap_dest_var.set(f"{lng},{lat}")
        logging.info(f"终点已设置为当前中心: {lng},{lat}")

    def _swap_origin_dest(self):
        """交换起点和终点"""
        origin = self._amap_origin_var.get()
        dest = self._amap_dest_var.get()
        self._amap_origin_var.set(dest)
        self._amap_dest_var.set(origin)
        logging.info("已交换起点和终点")

    def _search_amap_route(self):
        """通过高德地图 API 搜索路线"""
        api_key = self._amap_key_var.get().strip()
        origin = self._amap_origin_var.get().strip()
        dest = self._amap_dest_var.get().strip()
        mode = self._amap_mode_var.get()

        if not api_key:
            messagebox.showwarning("提示", "请先输入高德地图 API Key\n\n"
                                    "申请地址: https://console.amap.com/dev/key/app\n"
                                    "选择「Web服务」类型即可")
            return

        if not origin or not dest:
            messagebox.showwarning("提示", "请输入起点和终点坐标\n\n"
                                    "格式: 经度,纬度 (如 116.3264,39.9923)\n"
                                    "或直接输入地址文本 (如 北京大学)")
            return

        self._amap_status.configure(text="搜索中...", fg="#f39c12")
        self._amap_planner = AmapRoutePlanner(api_key)

        # 在后台线程搜索
        def do_search():
            try:
                if mode == "loop":
                    route = self._amap_planner.plan_loop_route(
                        origin, radius_m=1000
                    )
                elif mode == "cycling":
                    route = self._amap_planner.plan_campus_run(origin, dest)
                else:  # walking
                    route = self._amap_planner.plan_campus_run(origin, dest)

                if route:
                    self.root.after(0, self._on_amap_route_ready, route)
                else:
                    self.root.after(0, self._on_amap_route_failed)
            except Exception as e:
                self.root.after(0, self._on_amap_route_failed, str(e))

        threading.Thread(target=do_search, daemon=True).start()

    def _on_amap_route_ready(self, route: Route):
        """高德路线搜索成功回调"""
        self._route = route
        self._map_view.set_route(route)

        # 更新中心坐标
        if route.waypoints:
            lats = [wp.lat for wp in route.waypoints]
            lngs = [wp.lng for wp in route.waypoints]
            self._center_lat_var.set(f"{(min(lats)+max(lats))/2:.6f}")
            self._center_lng_var.set(f"{(min(lngs)+max(lngs))/2:.6f}")

        self._amap_status.configure(
            text=f"获取成功! {route.total_distance_m:.0f}m, {route.point_count}点",
            fg="#2ecc71",
        )

        # 同步距离到配速计算器
        dist_km = route.total_distance_m / 1000.0
        self._pace_calc.set_all(dist_km, self._pace_calc.pace_min_per_km)
        self._update_pace_display()

        self._update_stats()
        self._save_config()
        logging.info(f"高德路线: {route.name}")

    def _on_amap_route_failed(self, error: str = ""):
        """高德路线搜索失败回调"""
        self._amap_status.configure(text=f"搜索失败: {error or '无结果'}", fg="#e74c3c")
        logging.error(f"高德路线搜索失败: {error or '无结果'}")

    # ─── 配速联动方法 ──────────────────────────────────

    def _on_pace_param_changed(self, source: str):
        """配速参数变化时的联动处理"""
        if self._pace_updating:
            return
        self._pace_updating = True

        try:
            if source == "distance":
                try:
                    dist = float(self._pace_distance_var.get())
                    if dist > 0:
                        self._pace_calc.set_distance(dist)
                except ValueError:
                    pass

            elif source == "pace":
                try:
                    pace_min = float(self._pace_pace_min_var.get() or "0")
                    pace_sec = float(self._pace_pace_sec_var.get() or "0")
                    pace_total = pace_min + pace_sec / 60.0
                    if pace_total > 0:
                        self._pace_calc.set_pace(pace_total)
                except ValueError:
                    pass

            self._update_pace_display()
            self._sync_pace_to_speed()
        finally:
            self._pace_updating = False

    def _update_pace_display(self):
        """更新配速面板的显示值"""
        self._pace_distance_var.set(f"{self._pace_calc.distance_km:.2f}")
        self._pace_pace_min_var.set(f"{int(self._pace_calc.pace_min_per_km)}")
        self._pace_pace_sec_var.set(f"{int((self._pace_calc.pace_min_per_km % 1) * 60):02d}")
        self._pace_time_label.configure(text=self._pace_calc.time_str)
        self._pace_speed_label.configure(text=self._pace_calc.speed_str)

    def _sync_pace_to_speed(self):
        """将配速计算器的速度同步到速度滑块"""
        speed = self._pace_calc.speed_kmh
        self._speed_var.set(speed)
        self._speed_label.configure(text=f"{speed:.1f} km/h")

    def _on_speed_slider_changed(self, value):
        """速度滑块变化 → 同步到配速计算器"""
        kmh = float(value)
        self._speed_label.configure(text=f"{kmh:.1f} km/h")
        if not self._pace_updating:
            self._pace_updating = True
            try:
                self._pace_calc.set_speed(kmh)
                self._update_pace_display()
            finally:
                self._pace_updating = False

    # ─── 辅助方法 ──────────────────────────────────────

    def _browse_adb(self):
        """浏览选择 ADB 路径"""
        filepath = filedialog.askopenfilename(
            title="选择 adb.exe",
            filetypes=[("ADB 可执行文件", "adb.exe"), ("所有文件", "*.*")],
        )
        if filepath:
            self._adb_path_var.set(filepath)

    def _on_close(self):
        """窗口关闭事件"""
        if self._simulator and self._simulator.state == RunState.RUNNING:
            if messagebox.askyesno("确认退出", "模拟正在运行中，要停止并退出吗?"):
                self._simulator.stop()
            else:
                return

        if self._injector:
            self._injector.disconnect()

        if self._adb:
            self._adb.disconnect()

        self._save_config()
        self.root.destroy()

    # ─── 启动 ──────────────────────────────────────────

    def run(self):
        """启动 GUI 主循环"""
        # 更新初始状态
        self._update_stats()

        # 如果配置中有 ADB 路径且存在，自动尝试连接
        adb_path = self._adb_path_var.get().strip()
        if adb_path and os.path.exists(adb_path):
            self.root.after(1000, self._connect)

        self.root.mainloop()
