"""
CampusRunner v0.4 — 现代 SaaS 仪表盘

customtkinter 驱动的现代 UI，包含：
- 侧边栏导航
- KPI 数据卡片
- 交互式地图
- 实时折线图 + 环形进度
- 蓝色主题
"""

import sys
import os
import json
import threading
import logging
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# customtkinter
try:
    import customtkinter as ctk
    HAS_CTK = True
except ImportError:
    HAS_CTK = False

from core.adb_client import ADBClient
from core.location_injector import LocationInjector
from core.route_engine import Route, RouteGenerator, Waypoint
from core.simulator import Simulator, RunState, ProgressInfo
from core.map_api import AmapRoutePlanner
from core.pace_calculator import PaceCalculator
from gui.map_view import InteractiveMapView
from gui.widgets import (
    KPICard, SpeedChart, RingProgress, StatRow,
    BG_DARK, BG_CARD, BG_SIDEBAR,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BLUE_PRIMARY, BLUE_LIGHT, BLUE_GLOW,
    ACCENT_GREEN, ACCENT_RED, ACCENT_AMBER,
    BORDER,
)

logger = logging.getLogger(__name__)


def _get_base_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


class AppDashboard:
    """主仪表盘窗口"""

    CONFIG_PATH = _get_base_path() / "config.json"

    def __init__(self):
        if not HAS_CTK:
            self._fallback()
            return

        # ── 窗口设置 ──
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("CampusRunner — 校园跑助手")
        self.root.geometry("1280x820")
        self.root.minsize(1024, 680)
        self.root.configure(fg_color=BG_DARK)

        # ── 状态 ──
        self._config = self._load_config()
        self._adb: Optional[ADBClient] = None
        self._injector: Optional[LocationInjector] = None
        self._route: Optional[Route] = None
        self._simulator: Optional[Simulator] = None
        self._amap_planner: Optional[AmapRoutePlanner] = None
        self._connected = False

        # 配速计算器
        self._default_pace = 60.0 / self._config.get("default_speed_kmh", 10)
        self._pace_calc = PaceCalculator(distance_km=5.0, pace_min_per_km=self._default_pace)

        # 配置变量
        self._adb_path = tk.StringVar(value=self._config.get("adb_path", "D:/op/adb.exe"))
        self._device_addr = tk.StringVar(value=self._config.get("device_addr", "127.0.0.1:5555"))
        self._console_port = tk.StringVar(value=str(self._config.get("emulator_console_port", "5554")))
        self._amap_key = tk.StringVar(value=self._config.get("amap_api_key", ""))
        self._loop_var = tk.BooleanVar(value=False)
        self._drawing_active = False

        # ── 构建 UI ──
        self._build_sidebar()
        self._build_main()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(500, self._auto_connect)

    def _fallback(self):
        """customtkinter 不可用时的降级"""
        self.root = tk.Tk()
        self.root.title("CampusRunner")
        self.root.geometry("400x200")
        tk.Label(
            self.root, text="请安装 customtkinter:\npip install customtkinter",
            font=("Microsoft YaHei", 12),
        ).pack(expand=True)

    # ═══════════════════════════════════════════════════
    # 侧边栏
    # ═══════════════════════════════════════════════════

    def _build_sidebar(self):
        """构建侧边栏"""
        sidebar = ctk.CTkFrame(self.root, width=200, fg_color=BG_SIDEBAR, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Logo
        logo_frame = tk.Frame(sidebar, bg=BG_SIDEBAR)
        logo_frame.pack(fill="x", pady=(20, 30))

        tk.Label(
            logo_frame, text="🏃", bg=BG_SIDEBAR, fg=TEXT_PRIMARY,
            font=("Segoe UI Emoji", 28),
        ).pack()

        tk.Label(
            logo_frame, text="CampusRunner", bg=BG_SIDEBAR, fg=TEXT_PRIMARY,
            font=("Microsoft YaHei", 14, "bold"),
        ).pack()

        tk.Label(
            logo_frame, text="校园跑助手 v0.4", bg=BG_SIDEBAR, fg=TEXT_MUTED,
            font=("Microsoft YaHei", 8),
        ).pack()

        # 分隔线
        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill="x", padx=16, pady=8)

        # 导航项
        nav_items = [
            ("📊  仪表盘", "dashboard"),
            ("🗺  路线规划", "routes"),
            ("⚙  连接设置", "settings"),
        ]

        self._nav_buttons = {}
        for text, page_id in nav_items:
            btn = tk.Button(
                sidebar,
                text=text,
                bg=BG_SIDEBAR if page_id != "dashboard" else "#1e3a5f",
                fg=TEXT_PRIMARY if page_id != "dashboard" else BLUE_GLOW,
                font=("Microsoft YaHei", 11),
                relief="flat",
                anchor="w",
                padx=20,
                pady=10,
                cursor="hand2",
                activebackground="#1e3a5f",
                activeforeground=BLUE_GLOW,
                borderwidth=0,
                command=lambda pid=page_id: self._nav_to(pid),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_buttons[page_id] = btn

        # 底部状态
        tk.Frame(sidebar, bg=BG_SIDEBAR).pack(fill="x", side="bottom", pady=16)

        self._sidebar_status = tk.Label(
            sidebar, text="⚫ 未连接", bg=BG_SIDEBAR, fg=TEXT_MUTED,
            font=("Microsoft YaHei", 8),
        )
        self._sidebar_status.pack(side="bottom", pady=4)

    def _nav_to(self, page: str):
        """导航切换"""
        for pid, btn in self._nav_buttons.items():
            if pid == page:
                btn.configure(bg="#1e3a5f", fg=BLUE_GLOW)
            else:
                btn.configure(bg=BG_SIDEBAR, fg=TEXT_PRIMARY)

        if page == "settings":
            self._settings_popup()

    # ═══════════════════════════════════════════════════
    # 主区域
    # ═══════════════════════════════════════════════════

    def _build_main(self):
        """构建主内容区域"""
        main = ctk.CTkFrame(self.root, fg_color=BG_DARK, corner_radius=0)
        main.pack(side="right", fill="both", expand=True)

        # ── KPI 卡片行 ──
        kpi_row = tk.Frame(main, bg=BG_DARK)
        kpi_row.pack(fill="x", padx=16, pady=(16, 8))

        self._kpi_distance = KPICard(kpi_row, icon="🛣", label="已跑距离", value="0.00", unit="km")
        self._kpi_distance.pack(side="left", fill="x", expand=True, padx=4)

        self._kpi_time = KPICard(kpi_row, icon="⏱", label="运动时间", value="00:00", unit="")
        self._kpi_time.pack(side="left", fill="x", expand=True, padx=4)

        self._kpi_pace = KPICard(kpi_row, icon="👟", label="当前配速", value="--'--\"", unit="/km")
        self._kpi_pace.pack(side="left", fill="x", expand=True, padx=4)

        self._kpi_speed = KPICard(kpi_row, icon="⚡", label="实时速度", value="0.0", unit="km/h")
        self._kpi_speed.pack(side="left", fill="x", expand=True, padx=4)

        # GPS 诊断行
        diag_row = tk.Frame(main, bg=BG_DARK)
        diag_row.pack(fill="x", padx=16, pady=(0, 4))

        diag_items = [
            ("🛰 卫星", "sat", "10"),
            ("📍 精度", "acc", "3m"),
            ("👣 步频", "cad", "160"),
            ("📏 步幅", "stp", "0.8m"),
        ]
        self._diag_labels = {}
        for icon, key, default in diag_items:
            frame = tk.Frame(diag_row, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER)
            frame.pack(side="left", padx=4, ipadx=8, ipady=2)
            tk.Label(frame, text=icon, bg=BG_CARD, fg=TEXT_MUTED,
                     font=("Microsoft YaHei", 8)).pack(side="left", padx=2)
            lbl = tk.Label(frame, text=default, bg=BG_CARD, fg=BLUE_GLOW,
                           font=("Consolas", 9, "bold"))
            lbl.pack(side="left", padx=2)
            self._diag_labels[key] = lbl

        # ── 地图 + 图表 区域 ──
        content_row = tk.Frame(main, bg=BG_DARK)
        content_row.pack(fill="both", expand=True, padx=16, pady=8)
        content_row.grid_rowconfigure(0, weight=2)
        content_row.grid_rowconfigure(1, weight=1)
        content_row.grid_columnconfigure(0, weight=3)
        content_row.grid_columnconfigure(1, weight=1)

        # 地图（跨两行）
        map_wrapper = tk.Frame(content_row, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER)
        map_wrapper.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 4))

        cfg = self._config
        self._map_view = InteractiveMapView(
            map_wrapper,
            width=700, height=460,
            default_lat=float(cfg.get("center_lat", 39.9923)),
            default_lng=float(cfg.get("center_lng", 116.3264)),
        )
        self._map_view.pack(fill="both", expand=True, padx=2, pady=2)
        self._map_view.set_on_route_finished(self._on_hand_drawn_route)

        # 折线图
        self._speed_chart = SpeedChart(content_row, max_points=60, height=180)
        self._speed_chart.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 4))

        # 环形进度 + 控制
        right_bottom = tk.Frame(content_row, bg=BG_DARK)
        right_bottom.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(4, 0))
        right_bottom.grid_columnconfigure(0, weight=1)
        right_bottom.grid_rowconfigure(0, weight=0)
        right_bottom.grid_rowconfigure(1, weight=1)

        # 环形进度
        ring_row = tk.Frame(right_bottom, bg=BG_DARK)
        ring_row.grid(row=0, column=0, sticky="ew")
        self._ring_progress = RingProgress(ring_row, size=150)
        self._ring_progress.pack(pady=4)

        # 控制按钮
        ctrl_card = tk.Frame(right_bottom, bg=BG_CARD, highlightthickness=1, highlightbackground=BORDER)
        ctrl_card.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        # 配速快速设置
        pace_row = tk.Frame(ctrl_card, bg=BG_CARD)
        pace_row.pack(fill="x", padx=12, pady=(10, 4))

        tk.Label(pace_row, text="目标设置", bg=BG_CARD, fg=TEXT_SECONDARY,
                 font=("Microsoft YaHei", 9, "bold")).pack(anchor="w")

        # 距离
        dist_row = tk.Frame(ctrl_card, bg=BG_CARD)
        dist_row.pack(fill="x", padx=12, pady=2)
        tk.Label(dist_row, text="距离", bg=BG_CARD, fg=TEXT_MUTED, width=5, anchor="w",
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self._dist_entry = tk.Entry(dist_row, bg="#0f1a2e", fg=TEXT_PRIMARY,
                                     insertbackground=TEXT_PRIMARY, relief="flat", width=8,
                                     font=("Consolas", 10), justify="right")
        self._dist_entry.insert(0, "5.00")
        self._dist_entry.pack(side="left", padx=4)
        tk.Label(dist_row, text="km", bg=BG_CARD, fg=TEXT_MUTED, font=("Microsoft YaHei", 8)).pack(side="left")
        self._dist_entry.bind("<FocusOut>", lambda e: self._on_pace_input("dist"))

        # 配速
        pace_row2 = tk.Frame(ctrl_card, bg=BG_CARD)
        pace_row2.pack(fill="x", padx=12, pady=2)
        tk.Label(pace_row2, text="配速", bg=BG_CARD, fg=TEXT_MUTED, width=5, anchor="w",
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self._pace_min_entry = tk.Entry(pace_row2, bg="#0f1a2e", fg=TEXT_PRIMARY,
                                         insertbackground=TEXT_PRIMARY, relief="flat", width=4,
                                         font=("Consolas", 10), justify="right")
        self._pace_min_entry.insert(0, str(int(self._default_pace)))
        self._pace_min_entry.pack(side="left")
        tk.Label(pace_row2, text="'", bg=BG_CARD, fg=TEXT_MUTED, font=("Consolas", 9)).pack(side="left")
        self._pace_sec_entry = tk.Entry(pace_row2, bg="#0f1a2e", fg=TEXT_PRIMARY,
                                         insertbackground=TEXT_PRIMARY, relief="flat", width=3,
                                         font=("Consolas", 10), justify="right")
        self._pace_sec_entry.insert(0, f"{int((self._default_pace % 1) * 60):02d}")
        self._pace_sec_entry.pack(side="left")
        tk.Label(pace_row2, text="\"/km", bg=BG_CARD, fg=TEXT_MUTED, font=("Microsoft YaHei", 8)).pack(side="left")
        self._pace_min_entry.bind("<FocusOut>", lambda e: self._on_pace_input("pace"))
        self._pace_sec_entry.bind("<FocusOut>", lambda e: self._on_pace_input("pace"))

        # 预估时间
        time_row = tk.Frame(ctrl_card, bg=BG_CARD)
        time_row.pack(fill="x", padx=12, pady=2)
        tk.Label(time_row, text="预计", bg=BG_CARD, fg=TEXT_MUTED, width=5, anchor="w",
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self._time_preview = tk.Label(time_row, text=self._pace_calc.time_str, bg=BG_CARD,
                                       fg=BLUE_GLOW, font=("Consolas", 11, "bold"))
        self._time_preview.pack(side="left", padx=4)

        # 大按钮
        btn_row = tk.Frame(ctrl_card, bg=BG_CARD)
        btn_row.pack(fill="x", padx=8, pady=(8, 10))

        self._start_btn = tk.Button(
            btn_row, text="▶  开始跑步", bg=BLUE_PRIMARY, fg="white",
            font=("Microsoft YaHei", 11, "bold"), relief="flat",
            command=self._start_simulation, cursor="hand2",
            padx=16, pady=8, borderwidth=0,
            activebackground=BLUE_LIGHT, activeforeground="white",
        )
        self._start_btn.pack(side="left", fill="x", expand=True, padx=2)

        self._pause_btn = tk.Button(
            btn_row, text="⏸", bg="#1e3a5f", fg=ACCENT_AMBER,
            font=("", 14), relief="flat",
            command=self._toggle_pause, cursor="hand2", state="disabled",
            padx=10, pady=8, borderwidth=0,
        )
        self._pause_btn.pack(side="left", padx=2)

        self._stop_btn = tk.Button(
            btn_row, text="■", bg="#3b1a1a", fg=ACCENT_RED,
            font=("", 14), relief="flat",
            command=self._stop_simulation, cursor="hand2", state="disabled",
            padx=10, pady=8, borderwidth=0,
        )
        self._stop_btn.pack(side="left", padx=2)

        # ── 底部快捷操作栏 ──
        quickbar = tk.Frame(main, bg=BG_CARD, height=44, highlightthickness=1, highlightbackground=BORDER)
        quickbar.pack(fill="x", side="bottom", padx=16, pady=(0, 12))
        quickbar.pack_propagate(False)

        # 高德搜索
        tk.Label(quickbar, text="高德路线:", bg=BG_CARD, fg=TEXT_SECONDARY,
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=(12, 4))
        self._amap_origin = tk.Entry(quickbar, bg="#0f1a2e", fg=TEXT_PRIMARY,
                                      insertbackground=TEXT_PRIMARY, relief="flat", width=16,
                                      font=("Microsoft YaHei", 9))
        self._amap_origin.pack(side="left", padx=2)
        self._amap_origin.insert(0, self._config.get("default_origin", ""))

        tk.Label(quickbar, text="→", bg=BG_CARD, fg=TEXT_MUTED, font=("", 10)).pack(side="left", padx=2)

        self._amap_dest = tk.Entry(quickbar, bg="#0f1a2e", fg=TEXT_PRIMARY,
                                    insertbackground=TEXT_PRIMARY, relief="flat", width=16,
                                    font=("Microsoft YaHei", 9))
        self._amap_dest.pack(side="left", padx=2)
        self._amap_dest.insert(0, self._config.get("default_destination", ""))

        tk.Button(
            quickbar, text="搜索路线", bg=BLUE_PRIMARY, fg="white",
            relief="flat", font=("Microsoft YaHei", 9), cursor="hand2",
            command=self._search_amap, borderwidth=0, padx=10,
        ).pack(side="left", padx=8)

        # 手动生成
        tk.Button(
            quickbar, text="生成跑道", bg="#1e3a5f", fg=TEXT_PRIMARY,
            relief="flat", font=("Microsoft YaHei", 9), cursor="hand2",
            command=self._quick_generate, borderwidth=0, padx=10,
        ).pack(side="left", padx=4)

        # 加载文件
        tk.Button(
            quickbar, text="加载路线", bg="#1e3a5f", fg=TEXT_PRIMARY,
            relief="flat", font=("Microsoft YaHei", 9), cursor="hand2",
            command=self._load_route_file, borderwidth=0, padx=10,
        ).pack(side="left", padx=4)

        tk.Button(
            quickbar, text="导出GPX", bg="#1e3a5f", fg=TEXT_SECONDARY,
            relief="flat", font=("Microsoft YaHei", 9), cursor="hand2",
            command=self._export_gpx, borderwidth=0, padx=8,
        ).pack(side="left", padx=4)

        # 循环模式
        self._loop_cb = tk.Checkbutton(
            quickbar, text="循环", variable=self._loop_var,
            bg=BG_CARD, fg=TEXT_SECONDARY, selectcolor=BG_CARD,
            font=("Microsoft YaHei", 9),
            activebackground=BG_CARD, activeforeground=TEXT_SECONDARY,
        )
        self._loop_cb.pack(side="right", padx=12)

        # 连接状态
        self._conn_indicator = tk.Label(
            quickbar, text="⚫", bg=BG_CARD, fg=TEXT_MUTED,
            font=("", 10),
        )
        self._conn_indicator.pack(side="right", padx=4)

    # ═══════════════════════════════════════════════════
    # 连接管理
    # ═══════════════════════════════════════════════════

    def _auto_connect(self):
        """自动尝试连接"""
        adb_path = self._adb_path.get().strip()
        if adb_path and os.path.exists(adb_path):
            self._connect()

    def _connect(self):
        """连接模拟器"""
        adb_path = self._adb_path.get()
        device = self._device_addr.get()

        self._adb = ADBClient(adb_path=adb_path, device_addr=device)

        def do_connect():
            success = self._adb.connect()
            self.root.after(0, self._on_connect_result, success)

        threading.Thread(target=do_connect, daemon=True).start()

    def _on_connect_result(self, success: bool):
        if success:
            self._connected = True
            self._conn_indicator.configure(text="🟢", fg=ACCENT_GREEN)
            self._sidebar_status.configure(text="🟢 已连接", fg=ACCENT_GREEN)

            # 初始化注入器
            self._injector = LocationInjector(
                adb_path=self._adb_path.get(),
                host="127.0.0.1",
                console_port=int(self._console_port.get()),
                device_serial=self._device_addr.get(),
            )

            def do_setup():
                ok = self._injector.auto_connect()
                if ok:
                    self.root.after(0, lambda: logger.info(f"GPS注入器: {self._injector.active_injector_name}"))

            threading.Thread(target=do_setup, daemon=True).start()

            self._start_btn.configure(state="normal")
            self._save_config()
            logger.info("模拟器已连接")
        else:
            self._conn_indicator.configure(text="🔴", fg=ACCENT_RED)
            self._sidebar_status.configure(text="🔴 连接失败", fg=ACCENT_RED)
            logger.error("连接失败")

    def _settings_popup(self):
        """连接设置弹窗"""
        popup = tk.Toplevel(self.root)
        popup.title("连接设置")
        popup.geometry("380x320")
        popup.configure(bg=BG_CARD)
        popup.transient(self.root)

        tk.Label(popup, text="连接设置", bg=BG_CARD, fg=TEXT_PRIMARY,
                 font=("Microsoft YaHei", 14, "bold")).pack(pady=(16, 12))

        fields = [
            ("ADB 路径", self._adb_path),
            ("设备地址", self._device_addr),
            ("控制台端口", self._console_port),
            ("高德 API Key", self._amap_key),
        ]

        for label, var in fields:
            row = tk.Frame(popup, bg=BG_CARD)
            row.pack(fill="x", padx=24, pady=4)
            tk.Label(row, text=label, bg=BG_CARD, fg=TEXT_SECONDARY,
                     font=("Microsoft YaHei", 9), width=10, anchor="w").pack(side="left")
            entry = tk.Entry(row, textvariable=var, bg="#0f1a2e", fg=TEXT_PRIMARY,
                             insertbackground=TEXT_PRIMARY, relief="flat", width=30,
                             font=("Consolas", 9))
            entry.pack(side="left", fill="x", expand=True)

        btn_row = tk.Frame(popup, bg=BG_CARD)
        btn_row.pack(fill="x", padx=24, pady=(16, 8))
        tk.Button(
            btn_row, text="保存并重连", bg=BLUE_PRIMARY, fg="white",
            relief="flat", command=lambda: [self._save_config(), self._connect(), popup.destroy()],
            cursor="hand2", borderwidth=0, padx=20, pady=6,
            font=("Microsoft YaHei", 10),
        ).pack(side="right")

    # ═══════════════════════════════════════════════════
    # 路线管理
    # ═══════════════════════════════════════════════════

    def _on_hand_drawn_route(self, route: Route):
        """手绘路线完成"""
        self._set_route(route)
        logger.info(f"手绘路线: {route.name}, {route.total_distance_m:.0f}m")

    def _search_amap(self):
        """高德搜索路线"""
        key = self._amap_key.get().strip()
        origin = self._amap_origin.get().strip()
        dest = self._amap_dest.get().strip()

        if not key:
            messagebox.showwarning("提示", "请先在设置中输入高德 API Key")
            return
        if not origin or not dest:
            messagebox.showwarning("提示", "请输入起点和终点")
            return

        self._amap_planner = AmapRoutePlanner(key)

        def do_search():
            route = self._amap_planner.plan_campus_run(origin, dest)
            if route:
                self.root.after(0, self._set_route, route)
                self.root.after(0, lambda: logger.info(f"高德路线: {route.name}, {route.total_distance_m:.0f}m"))
            else:
                self.root.after(0, lambda: logger.error("高德搜索失败"))

        threading.Thread(target=do_search, daemon=True).start()

    def _quick_generate(self):
        """快速生成跑道"""
        try:
            lat = float(self._config.get("center_lat", 39.9923))
            lng = float(self._config.get("center_lng", 116.3264))
        except (ValueError, TypeError):
            lat, lng = 39.9923, 116.3264

        route = RouteGenerator.generate_campus_default(lat, lng, total_distance_m=2000)
        self._set_route(route)
        logger.info(f"生成跑道: {route.total_distance_m:.0f}m")

    def _load_route_file(self):
        """从文件加载路线"""
        filepath = filedialog.askopenfilename(
            title="加载路线文件",
            filetypes=[("路线文件", "*.json;*.gpx"), ("所有文件", "*.*")],
            initialdir=_get_base_path() / "routes",
        )
        if not filepath:
            return

        route = RouteGenerator.load_from_file(filepath)
        if route:
            self._set_route(route)
            logger.info(f"加载路线: {route.name}")

    def _export_gpx(self):
        """导出路线为 GPX"""
        if self._route is None:
            messagebox.showwarning("提示", "请先生成或加载一条路线")
            return

        filepath = filedialog.asksaveasfilename(
            title="导出 GPX 路线",
            defaultextension=".gpx",
            filetypes=[("GPX 文件", "*.gpx"), ("所有文件", "*.*")],
            initialdir=_get_base_path() / "routes",
        )
        if filepath:
            if RouteGenerator.save_to_file(self._route, filepath):
                logger.info(f"GPX 已导出: {filepath}")
                messagebox.showinfo("成功", f"路线已导出到:\n{filepath}")

    def _set_route(self, route: Route):
        """设置路线"""
        self._route = route
        self._map_view.show_route(route)

        dist_km = route.total_distance_m / 1000.0
        self._pace_calc.set_all(dist_km, self._pace_calc.pace_min_per_km)
        self._update_pace_display()
        self._update_kpi_static()

    # ═══════════════════════════════════════════════════
    # 配速联动
    # ═══════════════════════════════════════════════════

    def _on_pace_input(self, source: str):
        """配速输入联动"""
        try:
            if source == "dist":
                dist = float(self._dist_entry.get())
                if dist > 0:
                    self._pace_calc.set_distance(dist)
            elif source == "pace":
                pm = float(self._pace_min_entry.get() or "0")
                ps = float(self._pace_sec_entry.get() or "0")
                pace = pm + ps / 60.0
                if pace > 0:
                    self._pace_calc.set_pace(pace)
            self._update_pace_display()
        except ValueError:
            pass

    def _update_pace_display(self):
        """更新配速显示"""
        pc = self._pace_calc
        self._dist_entry.delete(0, "end")
        self._dist_entry.insert(0, f"{pc.distance_km:.2f}")
        self._pace_min_entry.delete(0, "end")
        self._pace_min_entry.insert(0, str(int(pc.pace_min_per_km)))
        self._pace_sec_entry.delete(0, "end")
        self._pace_sec_entry.insert(0, f"{int((pc.pace_min_per_km % 1) * 60):02d}")
        self._time_preview.configure(text=pc.time_str)

    # ═══════════════════════════════════════════════════
    # 模拟控制
    # ═══════════════════════════════════════════════════

    def _start_simulation(self):
        """开始模拟"""
        if self._route is None:
            messagebox.showwarning("提示", "请先生成或加载路线")
            return
        if self._injector is None:
            messagebox.showwarning("提示", "请先连接模拟器")
            return

        if self._simulator is None:
            self._simulator = Simulator(
                injector=self._injector,
                route=self._route,
                speed_kmh=self._pace_calc.speed_kmh,
                update_interval_ms=self._config.get("update_interval_ms", 1500),
                jitter_meters=self._config.get("gps_jitter_meters", 2.0),
                loop_mode=self._loop_var.get(),
            )
            self._simulator.on_progress(self._on_progress)
            self._simulator.on_state_change(self._on_state_change)
        else:
            self._simulator.route = self._route
            self._simulator.speed_kmh = self._pace_calc.speed_kmh
            self._simulator._loop_mode = self._loop_var.get()

        if self._simulator.start():
            self._start_btn.configure(state="disabled", text="▶  运行中...")
            self._pause_btn.configure(state="normal")
            self._stop_btn.configure(state="normal")
            logger.info(f"开始跑步! 速度={self._pace_calc.speed_kmh:.1f}km/h")

    def _toggle_pause(self):
        if self._simulator:
            self._simulator.toggle_pause()

    def _stop_simulation(self):
        if self._simulator:
            self._simulator.stop()
        self._start_btn.configure(state="normal", text="▶  开始跑步")
        self._pause_btn.configure(state="disabled")
        self._stop_btn.configure(state="disabled")
        logger.info("跑步已停止")

    def _on_progress(self, info: ProgressInfo):
        """进度更新回调（模拟线程）"""
        self.root.after(0, self._update_ui, info)

    def _on_state_change(self, old, new):
        if new == RunState.PAUSED:
            self.root.after(0, lambda: self._pause_btn.configure(text="▶"))
        elif new == RunState.RUNNING:
            self.root.after(0, lambda: self._pause_btn.configure(text="⏸"))
        elif new == RunState.FINISHED:
            self.root.after(0, self._on_run_finished)

    def _on_run_finished(self):
        self._start_btn.configure(state="normal", text="▶  开始跑步")
        self._pause_btn.configure(state="disabled", text="⏸")
        self._stop_btn.configure(state="disabled")
        self._ring_progress.set_progress(1.0, "100%", "完成!")
        logger.info("跑步完成!")

    def _update_ui(self, info: ProgressInfo):
        """主线程更新 UI"""
        # KPI 卡片
        self._kpi_distance.set_value(f"{info.distance_m / 1000:.2f}")

        elapsed = info.elapsed_sec
        h, m, s = int(elapsed // 3600), int((elapsed % 3600) // 60), int(elapsed % 60)
        self._kpi_time.set_value(f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}")

        pace = info.pace_min_per_km
        if pace > 0:
            pm, ps = int(pace), int((pace % 1) * 60)
            self._kpi_pace.set_value(f"{pm}'{ps:02d}\"")
        else:
            self._kpi_pace.set_value("--'--\"")

        speed = info.current_speed_ms * 3.6
        self._kpi_speed.set_value(f"{speed:.1f}")

        # 折线图
        self._speed_chart.push(speed)

        # 环形进度
        pct = info.progress_pct / 100.0
        self._ring_progress.set_progress(
            pct,
            f"{info.progress_pct:.0f}%",
            f"{info.remaining_m / 1000:.2f} km left",
        )

        # 地图位置
        self._map_view.update_current_position(info.current_lat, info.current_lng)

        # GPS 诊断
        self._diag_labels["sat"].configure(text=str(info.satellites))
        self._diag_labels["acc"].configure(text=f"{info.gps_accuracy:.1f}m")
        self._diag_labels["cad"].configure(text=f"{info.cadence:.0f}")
        self._diag_labels["stp"].configure(text=f"{info.step_length:.2f}m")

    def _update_kpi_static(self):
        """静态 KPI 更新（路线加载后）"""
        if self._route:
            self._kpi_distance.set_label("目标距离")
            self._kpi_distance.set_value(f"{self._route.total_distance_m / 1000:.2f}")

    # ═══════════════════════════════════════════════════
    # 配置 & 生命周期
    # ═══════════════════════════════════════════════════

    def _load_config(self) -> dict:
        if self.CONFIG_PATH.exists():
            try:
                with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_config(self):
        config = {
            "adb_path": self._adb_path.get(),
            "device_addr": self._device_addr.get(),
            "emulator_console_port": self._console_port.get(),
            "amap_api_key": self._amap_key.get(),
            "default_origin": self._amap_origin.get(),
            "default_destination": self._amap_dest.get(),
            "default_speed_kmh": self._pace_calc.speed_kmh,
            "center_lat": self._config.get("center_lat", 39.9923),
            "center_lng": self._config.get("center_lng", 116.3264),
        }
        try:
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self):
        if self._simulator and self._simulator.state == RunState.RUNNING:
            if messagebox.askyesno("确认退出", "模拟正在运行中，停止并退出?"):
                self._simulator.stop()
            else:
                return
        if self._injector:
            self._injector.disconnect()
        if self._adb:
            self._adb.disconnect()
        self._save_config()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
