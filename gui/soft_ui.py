"""
CampusRunner v1.0 — Soft UI / 新拟态 设计系统

莫兰迪低饱和配色 · 奶米白底色 · 大圆角卡片 · 柔和朦胧阴影
面向大学生的干净简约校园跑助手界面
"""

import sys, os, json, math, time, threading, logging, random
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
from collections import deque

import tkinter as tk
from tkinter import filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 莫兰迪色板
# ══════════════════════════════════════════════════════════

class Colors:
    """莫兰迪低饱和色板"""
    BG           = "#F5F0EB"   # 奶米白底色
    CARD         = "#FCFAF7"   # 卡片白
    CARD_DARK    = "#3E4A59"   # 深色对比卡片
    CARD_DARK2   = "#4A5568"   # 深色卡片变体
    SIDEBAR      = "#EDE8E2"   # 侧边栏底色
    SHADOW_LIGHT = "#FFFFFF"   # 亮阴影
    SHADOW_DARK  = "#E0D8CD"   # 暗阴影
    TEXT         = "#5D5A58"   # 主文字
    TEXT_DIM     = "#A09D9A"   # 次要文字
    TEXT_LIGHT   = "#E8E4E0"   # 深色卡片上的文字
    ACCENT       = "#93B5C6"   # 柔和校园蓝
    ACCENT_DEEP  = "#6B95AA"   # 深校园蓝
    ACCENT_WARM  = "#C6A893"   # 暖棕
    GREEN        = "#A3C4A3"   # 柔和绿
    RED          = "#D4A3A3"   # 柔和红
    ORANGE       = "#D4BCA3"   # 柔和橙
    CALENDAR_DOT = "#93B5C6"   # 日历打卡点
    PROGRESS_BG  = "#EBE5DE"   # 进度条底色


# ══════════════════════════════════════════════════════════
# Soft UI 基础组件
# ══════════════════════════════════════════════════════════

class SoftCard(tk.Frame):
    """Soft UI 卡片 — 圆角 + 双层柔和阴影"""

    def __init__(self, parent, padding: int = 20, radius: int = 24, dark: bool = False, **kw):
        bg = Colors.CARD_DARK if dark else Colors.CARD
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, **kw)
        self._bg = bg
        self._dark = dark
        self._padding = padding
        self._radius = radius

    def render(self):
        """在父容器中渲染阴影 + 卡片"""
        # 外层阴影容器
        shadow_frame = tk.Frame(self.master, bg=Colors.BG, highlightthickness=0, bd=0)
        shadow_frame.place(relx=0.5, rely=0.5, anchor="center",
                           width=self.winfo_reqwidth() + 8,
                           height=self.winfo_reqheight() + 6)
        # 阴影通过 Canvas 实现
        canvas = tk.Canvas(shadow_frame, bg=Colors.BG, highlightthickness=0, bd=0,
                           width=self.winfo_reqwidth() + 8,
                           height=self.winfo_reqheight() + 6)
        canvas.place(x=0, y=0)
        # 右下方暗阴影
        r = self._radius + 4
        canvas.create_rectangle(6, 4, self.winfo_reqwidth() + 8,
                                self.winfo_reqheight() + 6,
                                fill=Colors.SHADOW_DARK, outline="",
                                stipple="gray25" if not self._dark else "")
        # 左上方亮阴影
        canvas.create_rectangle(0, 0, self.winfo_reqwidth() + 4,
                                self.winfo_reqheight() + 2,
                                fill=Colors.SHADOW_LIGHT, outline="")


def soft_shadow(widget, bg: str = Colors.BG):
    """给 widget 创建柔和双层阴影（放置于下层）"""
    shadow1 = tk.Frame(widget.master, bg=Colors.SHADOW_DARK, highlightthickness=0, bd=0)
    shadow2 = tk.Frame(widget.master, bg=Colors.SHADOW_LIGHT, highlightthickness=0, bd=0)
    # 存储引用防止被回收
    widget._shadows = (shadow1, shadow2)
    return shadow1, shadow2


def rounded_frame(parent, bg: str = Colors.CARD, radius: int = 20, **kw) -> tk.Frame:
    """创建圆角卡片（用 Canvas 模拟圆角）"""
    f = tk.Frame(parent, bg=bg, highlightthickness=0, bd=0, **kw)
    return f


# ══════════════════════════════════════════════════════════
# 气泡数据图表
# ══════════════════════════════════════════════════════════

class SoftSpeedChart(tk.Canvas):
    """实时速度折线图 — Soft UI 风格"""

    def __init__(self, parent, width: int = 600, height: int = 180, max_points: int = 60, **kw):
        kw.setdefault("bg", Colors.CARD)
        kw["width"] = width
        kw["height"] = height
        super().__init__(parent, **kw)
        self._w_px, self._h_px = width, height
        self._max_pts = max_points
        self._speeds = deque([0.0] * min(15, max_points), maxlen=max_points)
        self._dists = deque([0.0] * min(15, max_points), maxlen=max_points)
        self._pacing = 0.0  # 目标配速对应的速度

    def set_target_speed(self, kmh: float):
        self._pacing = kmh

    def push(self, speed_kmh: float, dist_km: float):
        self._speeds.append(speed_kmh)
        self._dists.append(dist_km)
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self._w_px, self._h_px
        ml, mr, mt, mb = 44, 16, 22, 28
        cw, ch = w - ml - mr, h - mt - mb

        # 标题
        self.create_text(ml, 10, text="实时速度", fill=Colors.TEXT,
                         font=("Microsoft YaHei", 11, "bold"), anchor="nw")

        speeds = list(self._speeds)
        dists = list(self._dists)
        if len(speeds) < 2:
            return

        all_v = list(speeds) + ([self._pacing] if self._pacing > 0 else [])
        min_v = max(0, min(all_v) * 0.85)
        max_v = max(all_v) * 1.15
        if max_v - min_v < 3:
            max_v = min_v + 5

        # 网格
        for i in range(5):
            y = mt + ch * i / 4
            self.create_line(ml, y, w - mr, y, fill=Colors.PROGRESS_BG, dash=(3, 5))
            self.create_text(ml - 5, y, text=f"{max_v - (max_v - min_v) * i / 4:.1f}",
                             fill=Colors.TEXT_DIM, font=("Consolas", 8), anchor="e")

        # 目标配速线
        if self._pacing > 0:
            y_pace = mt + ch * (1 - (self._pacing - min_v) / (max_v - min_v))
            y_pace = max(mt, min(mt + ch, y_pace))
            self.create_line(ml, y_pace, w - mr, y_pace, fill=Colors.ACCENT, dash=(6, 3), width=1.5)
            self.create_text(w - mr, y_pace - 8, text=f"目标 {self._pacing:.1f}",
                             fill=Colors.ACCENT, font=("Microsoft YaHei", 8), anchor="se")

        # 填充区域
        pts = []
        n = len(speeds)
        for i, v in enumerate(speeds):
            x = ml + cw * i / (n - 1) if n > 1 else ml + cw / 2
            ratio = (v - min_v) / (max_v - min_v) if max_v > min_v else 0.5
            ratio = max(0, min(1, ratio))
            y = mt + ch * (1 - ratio)
            pts.extend([x, y])
        # 填充多边形
        fill_pts = list(pts) + [ml + cw, mt + ch, ml, mt + ch]
        self.create_polygon(*fill_pts, fill=Colors.ACCENT, outline="", stipple="gray50")

        # 折线
        if len(pts) >= 4:
            self.create_line(*pts, fill=Colors.ACCENT_DEEP, width=2.5, smooth=True)

        # 当前值标签
        cur_v = speeds[-1]
        cur_x = pts[-2] if len(pts) >= 2 else ml + cw / 2
        cur_y = pts[-1] if len(pts) >= 2 else mt + ch / 2
        self.create_oval(cur_x - 5, cur_y - 5, cur_x + 5, cur_y + 5,
                         fill=Colors.ACCENT_DEEP, outline=Colors.CARD, width=2)
        self.create_text(w - mr, 10, text=f"{cur_v:.1f} km/h",
                         fill=Colors.ACCENT_DEEP, font=("Segoe UI", 11, "bold"), anchor="ne")

        # X 轴标签
        for i in range(5):
            x = ml + cw * i / 4
            idx = int(n * i / 4) if n > 0 else 0
            idx = min(idx, len(dists) - 1) if dists else 0
            label = f"{dists[idx]:.1f}km" if dists and idx < len(dists) else ""
            self.create_text(x, h - 6, text=label,
                             fill=Colors.TEXT_DIM, font=("Consolas", 8), anchor="n")


# ══════════════════════════════════════════════════════════
# 学期目标环形进度条
# ══════════════════════════════════════════════════════════

class SoftRingProgress(tk.Canvas):
    """当前路线完成进度环形条"""

    def __init__(self, parent, size: int = 180, **kw):
        kw.setdefault("bg", Colors.CARD)
        kw["width"] = size
        kw["height"] = size
        super().__init__(parent, **kw)
        self._size = size
        self._pct = 0.0       # 0.0 ~ 1.0
        self._current = 0.0   # km
        self._total = 0.0     # km
        self._remaining = 0.0 # km
        self._draw()

    def set_progress(self, pct: float, current_km: float = 0, total_km: float = 0, remaining_km: float = 0):
        self._pct = min(1.0, max(0.0, pct))
        self._current = current_km
        self._total = total_km
        self._remaining = remaining_km
        self._draw()

    def _draw(self):
        self.delete("all")
        cx = cy = self._size // 2
        r = self._size // 2 - 30
        width = 16

        # 底色弧（浅灰）
        self.create_arc(cx - r, cy - r, cx + r, cy + r,
                         outline=Colors.PROGRESS_BG, width=width, style="arc",
                         start=135, extent=270)

        # 进度弧（校园蓝）
        if self._pct > 0.001:
            extent = -270 * self._pct
            self.create_arc(cx - r, cy - r, cx + r, cy + r,
                             outline=Colors.ACCENT, width=width, style="arc",
                             start=135, extent=extent)
            # 端点圆
            angle = math.radians(135 - 270 * self._pct)
            ex = cx + r * math.cos(angle)
            ey = cy - r * math.sin(angle)
            self.create_oval(ex - 8, ey - 8, ex + 8, ey + 8,
                             fill=Colors.ACCENT, outline="")

        # 中心文字
        self.create_text(cx, cy - 14, text="路线进度",
                         fill=Colors.TEXT_DIM, font=("Microsoft YaHei", 9), anchor="center")
        self.create_text(cx, cy + 6, text=f"{self._pct*100:.0f}%",
                         fill=Colors.TEXT, font=("Segoe UI", 22, "bold"), anchor="center")
        self.create_text(cx, cy + 24, text=f"{self._current:.1f} / {self._total:.1f} km",
                         fill=Colors.TEXT_DIM, font=("Microsoft YaHei", 9), anchor="center")

        # 剩余
        self.create_text(cx, cy + 44, text=f"剩余 {self._remaining:.2f} km",
                         fill=Colors.ACCENT_DEEP, font=("Microsoft YaHei", 9, "bold"), anchor="center")


# ══════════════════════════════════════════════════════════
# 校园跑打卡日历
# ══════════════════════════════════════════════════════════

class SoftCalendar(tk.Frame):
    """校园跑打卡日历 — 深色卡片形成对比"""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=Colors.CARD_DARK, highlightthickness=0, bd=0, **kw)
        self._today = datetime.now()
        self._year = self._today.year
        self._month = self._today.month
        self._run_days: set[int] = set()  # 打卡日期
        self._build()

    def _build(self):
        # 月份标题
        header = tk.Frame(self, bg=Colors.CARD_DARK)
        header.pack(fill="x", padx=16, pady=(14, 8))

        self._month_label = tk.Label(
            header, text=f"{self._year}年 {self._month}月",
            bg=Colors.CARD_DARK, fg=Colors.TEXT_LIGHT,
            font=("Microsoft YaHei", 12, "bold"),
        )
        self._month_label.pack(side="left")

        # 导航
        nav = tk.Frame(header, bg=Colors.CARD_DARK)
        nav.pack(side="right")
        tk.Button(nav, text="〈", bg=Colors.CARD_DARK, fg=Colors.TEXT_LIGHT,
                  relief="flat", font=("", 10), bd=0, cursor="hand2",
                  command=self._prev_month).pack(side="left", padx=2)
        tk.Button(nav, text="〉", bg=Colors.CARD_DARK, fg=Colors.TEXT_LIGHT,
                  relief="flat", font=("", 10), bd=0, cursor="hand2",
                  command=self._next_month).pack(side="left", padx=2)

        # 星期头 — 用 grid 对齐网格列
        week_header = tk.Frame(self, bg=Colors.CARD_DARK)
        week_header.pack(fill="x", padx=10, pady=4)
        for i, d in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            week_header.grid_columnconfigure(i, weight=1, uniform="calcol")
            tk.Label(week_header, text=d, bg=Colors.CARD_DARK, fg=Colors.TEXT_DIM,
                     font=("Microsoft YaHei", 8)).grid(row=0, column=i)

        # 日期网格
        self._grid_frame = tk.Frame(self, bg=Colors.CARD_DARK)
        self._grid_frame.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        for i in range(7):
            self._grid_frame.grid_columnconfigure(i, weight=1, uniform="calcol")
        self._draw_grid()

    def _draw_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()

        # 当月第一天是周几
        first_day = datetime(self._year, self._month, 1)
        start_dow = first_day.weekday()  # 0=Mon

        # 当月天数
        if self._month == 12:
            days_in_month = (datetime(self._year + 1, 1, 1) - first_day).days
        else:
            days_in_month = (datetime(self._year, self._month + 1, 1) - first_day).days

        for i in range(42):  # 6 rows × 7 days
            row, col = i // 7, i % 7
            day = i - start_dow + 1

            if 1 <= day <= days_in_month:
                is_today = (day == self._today.day and self._month == self._today.month
                            and self._year == self._today.year)
                is_run = day in self._run_days

                cell = tk.Frame(self._grid_frame, bg=Colors.CARD_DARK,
                                width=32, height=32)
                cell.grid(row=row, column=col, padx=1, pady=1)
                cell.pack_propagate(False)

                # 今天高亮
                if is_today:
                    dot = tk.Label(cell, text="●", bg=Colors.CARD_DARK,
                                   fg=Colors.ACCENT, font=("", 8))
                    dot.place(relx=0.5, rely=0.15, anchor="center")

                day_bg = Colors.ACCENT if is_run else Colors.CARD_DARK
                day_fg = Colors.TEXT_LIGHT if is_run else Colors.TEXT_LIGHT
                lbl = tk.Label(cell, text=str(day), bg=day_bg, fg=day_fg,
                               font=("Segoe UI", 9, "bold" if is_run else "normal"),
                               width=3, height=1)
                lbl.place(relx=0.5, rely=0.55, anchor="center")
                if is_run:
                    lbl.configure(bg=Colors.ACCENT, fg="white")
            else:
                tk.Frame(self._grid_frame, bg=Colors.CARD_DARK, width=32, height=32
                         ).grid(row=row, column=col, padx=1, pady=1)

    def _prev_month(self):
        if self._month == 1:
            self._month = 12
            self._year -= 1
        else:
            self._month -= 1
        self._month_label.configure(text=f"{self._year}年 {self._month}月")
        self._draw_grid()

    def _next_month(self):
        if self._month == 12:
            self._month = 1
            self._year += 1
        else:
            self._month += 1
        self._month_label.configure(text=f"{self._year}年 {self._month}月")
        self._draw_grid()

    def mark_run(self, day: Optional[int] = None):
        """标记打卡日"""
        if day is None:
            day = self._today.day
        self._run_days.add(day)
        self._draw_grid()

    def set_run_days(self, days: list[int]):
        self._run_days = set(days)
        self._draw_grid()


# ══════════════════════════════════════════════════════════
# 跑步历史记录列表
# ══════════════════════════════════════════════════════════

class SoftHistoryList(tk.Frame):
    """跑步历史记录 — 可滚动列表"""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=Colors.CARD, highlightthickness=0, bd=0, **kw)
        self._runs: list[dict] = []
        self._item_count = 0

        # 标题
        self._header_frame = tk.Frame(self, bg=Colors.CARD)
        self._header_frame.pack(fill="x", padx=16, pady=(12, 8))
        self._title_label = tk.Label(self._header_frame, text="跑步记录", bg=Colors.CARD,
                                      fg=Colors.TEXT, font=("Microsoft YaHei", 11, "bold"))
        self._title_label.pack(side="left")
        self._count_label = tk.Label(self._header_frame, text="0 次", bg=Colors.CARD,
                                      fg=Colors.TEXT_DIM, font=("Microsoft YaHei", 9))
        self._count_label.pack(side="right")

        # 滚动列表 (Canvas + scrollbar)
        self._canvas = tk.Canvas(self, bg=Colors.CARD, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._list_frame = tk.Frame(self._canvas, bg=Colors.CARD)
        self._list_frame.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.create_window((0, 0), window=self._list_frame, anchor="nw")
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True, padx=8)
        scrollbar.pack(side="right", fill="y", pady=4)

        # 空状态
        self._empty_label = tk.Label(self._list_frame, text="还没有跑步记录\n开始你的第一次跑步吧 🏃",
                                      bg=Colors.CARD, fg=Colors.TEXT_DIM,
                                      font=("Microsoft YaHei", 10))
        self._empty_label.pack(pady=30)

    def add_run(self, date: str, dist_km: float, time_str: str, pace_str: str):
        self._item_count += 1
        self._runs.append({"date": date, "dist": dist_km, "time": time_str, "pace": pace_str})
        # 清除空状态
        if self._empty_label:
            self._empty_label.pack_forget()
            self._empty_label = None
        self._count_label.configure(text=f"{self._item_count} 次")
        self._draw_item(date, dist_km, time_str, pace_str)

    def _draw_item(self, date, dist, time_str, pace_str):
        row = tk.Frame(self._list_frame, bg=Colors.CARD, height=42)
        row.pack(fill="x", pady=1)
        row.pack_propagate(False)

        tk.Label(row, text=date, bg=Colors.CARD, fg=Colors.TEXT_DIM,
                 font=("Segoe UI", 10), width=7, anchor="w").pack(side="left", padx=6)
        tk.Label(row, text=f"{dist:.2f} km", bg=Colors.CARD, fg=Colors.TEXT,
                 font=("Segoe UI", 11, "bold"), width=9, anchor="e").pack(side="left")
        tk.Label(row, text=time_str, bg=Colors.CARD, fg=Colors.TEXT,
                 font=("Segoe UI", 10), width=8, anchor="center").pack(side="left")

        pk = tk.Label(row, text=pace_str, bg=Colors.ACCENT, fg="white",
                      font=("Segoe UI", 9, "bold"), padx=8)
        pk.pack(side="right", padx=10, pady=4)

        tk.Frame(self._list_frame, bg=Colors.PROGRESS_BG, height=1).pack(fill="x", padx=16)


# ══════════════════════════════════════════════════════════
# Soft UI 仪表盘主窗口
# ══════════════════════════════════════════════════════════

def _get_base_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


class SoftDashboard:
    """Soft UI 主仪表盘"""

    CONFIG_PATH = _get_base_path() / "config.json"

    def __init__(self):
        if not HAS_CTK:
            self._fallback()
            return

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("CampusRunner — 校园跑助手")
        self.root.geometry("1280x820")
        self.root.minsize(1100, 720)
        self.root.configure(fg_color=Colors.BG)

        # 状态
        self._config = self._load_config()
        self._adb: Optional[ADBClient] = None
        self._injector: Optional[LocationInjector] = None
        self._route: Optional[Route] = None
        self._simulator: Optional[Simulator] = None
        self._connected = False

        dp = 60.0 / self._config.get("default_speed_kmh", 10)
        self._pace_calc = PaceCalculator(distance_km=5.0, pace_min_per_km=dp)

        # 构建
        self._build_sidebar()
        self._build_main()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _fallback(self):
        self.root = tk.Tk()
        self.root.geometry("400x200")
        tk.Label(self.root, text="请安装: pip install customtkinter").pack(expand=True)

    # ══════════════════════════════════════════════════════
    # 侧边栏
    # ══════════════════════════════════════════════════════

    def _build_sidebar(self):
        sb = tk.Frame(self.root, bg=Colors.SIDEBAR, width=220, highlightthickness=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # Logo
        logo = tk.Frame(sb, bg=Colors.SIDEBAR)
        logo.pack(fill="x", pady=(28, 24))
        tk.Label(logo, text="🏃", bg=Colors.SIDEBAR, fg=Colors.TEXT,
                 font=("Segoe UI Emoji", 26)).pack()
        tk.Label(logo, text="CampusRunner", bg=Colors.SIDEBAR, fg=Colors.TEXT,
                 font=("Microsoft YaHei", 13, "bold")).pack()
        tk.Label(logo, text="校园跑助手", bg=Colors.SIDEBAR, fg=Colors.TEXT_DIM,
                 font=("Microsoft YaHei", 9)).pack()

        # 分隔
        tk.Frame(sb, bg=Colors.SHADOW_DARK, height=1).pack(fill="x", padx=28, pady=10)

        # 导航
        navs = [("📊  仪表盘", "dashboard"), ("🗺  路线规划", "routes"),
                ("📅  打卡日历", "calendar"), ("⚙  设置", "settings")]
        self._nav_btns = {}
        for text, pid in navs:
            btn = tk.Button(sb, text=text, bg=Colors.SIDEBAR if pid != "dashboard" else Colors.ACCENT,
                            fg="white" if pid == "dashboard" else Colors.TEXT,
                            font=("Microsoft YaHei", 12), relief="flat", anchor="w",
                            padx=22, pady=10, cursor="hand2", bd=0,
                            activebackground=Colors.ACCENT, activeforeground="white",
                            command=lambda p=pid: self._nav(p))
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_btns[pid] = btn

        # 底部状态
        tk.Frame(sb, bg=Colors.SIDEBAR).pack(fill="x", side="bottom", pady=14)
        tk.Label(sb, text="v1.0 · Soft UI", bg=Colors.SIDEBAR, fg=Colors.TEXT_DIM,
                 font=("Microsoft YaHei", 8)).pack(side="bottom", pady=4)
        self._sb_status = tk.Label(sb, text="○ 未连接", bg=Colors.SIDEBAR,
                                    fg=Colors.TEXT_DIM, font=("Microsoft YaHei", 9))
        self._sb_status.pack(side="bottom")

    def _nav(self, page: str):
        for pid, btn in self._nav_btns.items():
            btn.configure(bg=Colors.SIDEBAR if pid != page else Colors.ACCENT,
                          fg="white" if pid == page else Colors.TEXT)
        if page == "settings":
            self._settings_popup()

    # ══════════════════════════════════════════════════════
    # 主内容区
    # ══════════════════════════════════════════════════════

    def _build_main(self):
        main = tk.Frame(self.root, bg=Colors.BG, highlightthickness=0)
        main.pack(side="right", fill="both", expand=True)
        main.grid_columnconfigure(0, weight=2)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=0)
        main.grid_rowconfigure(1, weight=1)
        main.grid_rowconfigure(2, weight=0)

        # ── 顶部问候 ──
        greeting = tk.Frame(main, bg=Colors.BG)
        greeting.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(20, 8))
        tk.Label(greeting, text="👋 下午好, 开始今天的跑步吧",
                 bg=Colors.BG, fg=Colors.TEXT,
                 font=("Microsoft YaHei", 16, "bold")).pack(side="left")
        self._conn_dot = tk.Label(greeting, text="○", bg=Colors.BG, fg=Colors.TEXT_DIM,
                                   font=("", 14))
        self._conn_dot.pack(side="right")

        # ── 左侧：地图 + 气泡图 ──
        left_col = tk.Frame(main, bg=Colors.BG)
        left_col.grid(row=1, column=0, sticky="nsew", padx=(24, 8), pady=4)
        left_col.grid_rowconfigure(0, weight=3)
        left_col.grid_rowconfigure(1, weight=2)
        left_col.grid_columnconfigure(0, weight=1)

        # 地图卡片
        map_card = rounded_frame(left_col, bg=Colors.CARD)
        map_card.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        self._map_view = InteractiveMapView(
            map_card, width=600, height=340,
            default_lat=float(self._config.get("center_lat", 39.9923)),
            default_lng=float(self._config.get("center_lng", 116.3264)),
        )
        self._map_view.pack(fill="both", expand=True, padx=3, pady=3)
        self._map_view.set_on_route_finished(self._on_route)

        # 速度折线图卡片
        chart_card = rounded_frame(left_col, bg=Colors.CARD)
        chart_card.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self._speed_chart = SoftSpeedChart(chart_card, width=600, height=180)
        self._speed_chart.pack(fill="both", expand=True, padx=12, pady=8)

        # ── 右侧：环形进度 + 日历 + 历史 ──
        right_col = tk.Frame(main, bg=Colors.BG)
        right_col.grid(row=1, column=1, sticky="nsew", padx=(8, 24), pady=4)
        right_col.grid_rowconfigure(0, weight=1)
        right_col.grid_rowconfigure(1, weight=1)
        right_col.grid_rowconfigure(2, weight=2)
        right_col.grid_columnconfigure(0, weight=1)

        # 环形进度卡片
        ring_card = rounded_frame(right_col, bg=Colors.CARD)
        ring_card.grid(row=0, column=0, sticky="nsew", pady=(0, 4))
        self._ring = SoftRingProgress(ring_card, size=160)
        self._ring.pack(expand=True)

        # 日历卡片（深色对比）
        cal_card = rounded_frame(right_col, bg=Colors.CARD_DARK)
        cal_card.grid(row=1, column=0, sticky="nsew", pady=4)
        self._calendar = SoftCalendar(cal_card)
        self._calendar.pack(fill="both", expand=True, padx=3, pady=3)

        # 历史记录卡片
        hist_card = rounded_frame(right_col, bg=Colors.CARD)
        hist_card.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        self._history = SoftHistoryList(hist_card)
        self._history.pack(fill="both", expand=True, padx=3, pady=3)

        # ── 底部控制栏 ──
        ctrl_bar = tk.Frame(main, bg=Colors.CARD, height=64, highlightthickness=0)
        ctrl_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=24, pady=(10, 16))
        ctrl_bar.pack_propagate(False)

        # 目标设置行 — 大字体
        tk.Label(ctrl_bar, text="目标", bg=Colors.CARD, fg=Colors.TEXT_DIM,
                 font=("Microsoft YaHei", 10)).pack(side="left", padx=(20, 6))

        self._dist_entry = tk.Entry(ctrl_bar, bg=Colors.BG, fg=Colors.TEXT, relief="flat",
                                     width=7, font=("Segoe UI", 14, "bold"), justify="center",
                                     insertbackground=Colors.ACCENT)
        self._dist_entry.insert(0, "5.00")
        self._dist_entry.pack(side="left", padx=2)
        tk.Label(ctrl_bar, text="km  ", bg=Colors.CARD, fg=Colors.TEXT_DIM,
                 font=("Microsoft YaHei", 10)).pack(side="left")

        tk.Label(ctrl_bar, text="配速", bg=Colors.CARD, fg=Colors.TEXT_DIM,
                 font=("Microsoft YaHei", 10)).pack(side="left", padx=(16, 6))
        self._pace_e1 = tk.Entry(ctrl_bar, bg=Colors.BG, fg=Colors.TEXT, relief="flat",
                                  width=4, font=("Segoe UI", 14, "bold"), justify="center")
        self._pace_e1.insert(0, str(int(self._pace_calc.pace_min_per_km)))
        self._pace_e1.pack(side="left", padx=1)
        tk.Label(ctrl_bar, text="'", bg=Colors.CARD, fg=Colors.TEXT_DIM,
                 font=("Microsoft YaHei", 11)).pack(side="left")
        self._pace_e2 = tk.Entry(ctrl_bar, bg=Colors.BG, fg=Colors.TEXT, relief="flat",
                                  width=3, font=("Segoe UI", 14, "bold"), justify="center")
        self._pace_e2.insert(0, f"{int((self._pace_calc.pace_min_per_km % 1) * 60):02d}")
        self._pace_e2.pack(side="left", padx=1)
        tk.Label(ctrl_bar, text="\"/km  ", bg=Colors.CARD, fg=Colors.TEXT_DIM,
                 font=("Microsoft YaHei", 10)).pack(side="left")

        self._time_lbl = tk.Label(ctrl_bar, text=f"≈ {self._pace_calc.time_str}",
                                   bg=Colors.CARD, fg=Colors.ACCENT_DEEP,
                                   font=("Segoe UI", 12, "bold"))
        self._time_lbl.pack(side="left", padx=10)

        # 循环模式
        self._loop_var = tk.BooleanVar(value=False)
        self._loop_cb = tk.Checkbutton(ctrl_bar, text="循环", variable=self._loop_var,
                                        bg=Colors.CARD, fg=Colors.TEXT_DIM,
                                        font=("Microsoft YaHei", 10),
                                        selectcolor=Colors.CARD, activebackground=Colors.CARD)
        self._loop_cb.pack(side="left", padx=10)

        self._dist_entry.bind("<FocusOut>", lambda e: self._on_pace_change("dist"))
        self._pace_e1.bind("<FocusOut>", lambda e: self._on_pace_change("pace"))
        self._pace_e2.bind("<FocusOut>", lambda e: self._on_pace_change("pace"))

        # 右侧按钮组 — 大按钮
        btn_frame = tk.Frame(ctrl_bar, bg=Colors.CARD)
        btn_frame.pack(side="right", padx=16)

        self._start_btn = tk.Button(btn_frame, text="▶  开始跑步", bg=Colors.ACCENT, fg="white",
                                     font=("Microsoft YaHei", 13, "bold"), relief="flat", bd=0,
                                     command=self._start, cursor="hand2", padx=28, pady=10,
                                     activebackground=Colors.ACCENT_DEEP)
        self._start_btn.pack(side="left", padx=4)

        self._pause_btn = tk.Button(btn_frame, text="⏸", bg=Colors.CARD, fg=Colors.ORANGE,
                                     relief="flat", bd=0, command=self._toggle_pause,
                                     cursor="hand2", state="disabled", font=("", 16))
        self._pause_btn.pack(side="left", padx=4)

        self._stop_btn = tk.Button(btn_frame, text="■", bg=Colors.CARD, fg=Colors.RED,
                                    relief="flat", bd=0, command=self._stop,
                                    cursor="hand2", state="disabled", font=("", 16))
        self._stop_btn.pack(side="left", padx=4)

        # 快捷按钮
        tk.Button(ctrl_bar, text="生成跑道", bg=Colors.CARD, fg=Colors.TEXT,
                  relief="flat", bd=0, command=self._gen_route, cursor="hand2",
                  font=("Microsoft YaHei", 10)).pack(side="right", padx=6)
        tk.Button(ctrl_bar, text="保存路线", bg=Colors.CARD, fg=Colors.TEXT,
                  relief="flat", bd=0, command=self._save_route, cursor="hand2",
                  font=("Microsoft YaHei", 10)).pack(side="right", padx=6)
        tk.Button(ctrl_bar, text="加载路线", bg=Colors.CARD, fg=Colors.TEXT,
                  relief="flat", bd=0, command=self._load_route, cursor="hand2",
                  font=("Microsoft YaHei", 10)).pack(side="right", padx=6)

        # 连接按钮
        self._connect_btn = tk.Button(ctrl_bar, text="连接模拟器", bg=Colors.ACCENT_WARM, fg="white",
                                       relief="flat", bd=0, command=self._toggle_connect,
                                       cursor="hand2", font=("Microsoft YaHei", 10))
        self._connect_btn.pack(side="right", padx=6)

    # ══════════════════════════════════════════════════════
    # 业务逻辑
    # ══════════════════════════════════════════════════════

    def _load_config(self) -> dict:
        if self.CONFIG_PATH.exists():
            try:
                with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _toggle_connect(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        adb = self._config.get("adb_path", "D:/op/adb.exe")
        dev = self._config.get("device_addr", "emulator-5554")
        self._adb = ADBClient(adb_path=adb, device_addr=dev)

        def do():
            ok = self._adb.connect()
            self.root.after(0, lambda: self._on_conn(ok))
        threading.Thread(target=do, daemon=True).start()

    def _on_conn(self, ok):
        if ok:
            self._connected = True
            self._conn_dot.configure(text="●", fg=Colors.GREEN)
            self._sb_status.configure(text="● 已连接", fg=Colors.GREEN)
            self._connect_btn.configure(text="断开", bg=Colors.RED)
            self._injector = LocationInjector(
                adb_path=self._config.get("adb_path", "D:/op/adb.exe"),
                host="127.0.0.1",
                console_port=self._config.get("emulator_console_port", 5554),
                device_serial=self._config.get("device_addr", "emulator-5554"),
                ldplayer_path=self._config.get("ldplayer_path", "D:/leidian/LDPlayer9"),
            )
            def setup():
                self._injector.auto_connect()
                self.root.after(0, lambda: logger.info(f"GPS: {self._injector.active_injector_name}"))
            threading.Thread(target=setup, daemon=True).start()
            self._start_btn.configure(state="normal")
        else:
            self._conn_dot.configure(text="○", fg=Colors.RED)

    def _disconnect(self):
        if self._simulator:
            self._simulator.stop()
        if self._injector:
            self._injector.disconnect()
        if self._adb:
            self._adb.disconnect()
        self._connected = False
        self._conn_dot.configure(text="○", fg=Colors.TEXT_DIM)
        self._sb_status.configure(text="○ 未连接", fg=Colors.TEXT_DIM)
        self._connect_btn.configure(text="连接模拟器", bg=Colors.ACCENT_WARM)

    def _on_route(self, route: Route):
        self._route = route
        self._map_view.show_route(route)
        dkm = route.total_distance_m / 1000.0
        self._pace_calc.set_all(dkm, self._pace_calc.pace_min_per_km)
        self._update_pace_disp()
        self._speed_chart.set_target_speed(self._pace_calc.speed_kmh)

    def _on_pace_change(self, src):
        try:
            if src == "dist":
                self._pace_calc.set_distance(float(self._dist_entry.get()))
            else:
                pm, ps = float(self._pace_e1.get() or 0), float(self._pace_e2.get() or 0)
                self._pace_calc.set_pace(pm + ps / 60)
            self._update_pace_disp()
        except ValueError:
            pass

    def _update_pace_disp(self):
        pc = self._pace_calc
        self._dist_entry.delete(0, "end"); self._dist_entry.insert(0, f"{pc.distance_km:.2f}")
        self._pace_e1.delete(0, "end"); self._pace_e1.insert(0, str(int(pc.pace_min_per_km)))
        self._pace_e2.delete(0, "end"); self._pace_e2.insert(0, f"{int((pc.pace_min_per_km%1)*60):02d}")
        self._time_lbl.configure(text=f"  ≈ {pc.time_str}")

    def _gen_route(self):
        lat, lng = float(self._config.get("center_lat", 39.9923)), float(self._config.get("center_lng", 116.3264))
        self._on_route(RouteGenerator.generate_campus_default(lat, lng, 2000))

    def _load_route(self):
        p = filedialog.askopenfilename(filetypes=[("路线", "*.json;*.gpx")],
                                        initialdir=_get_base_path() / "routes")
        if p:
            r = RouteGenerator.load_from_file(p)
            if r:
                self._on_route(r)

    def _save_route(self):
        """保存当前路线到文件"""
        if self._route is None:
            messagebox.showwarning("提示", "请先生成或加载一条路线")
            return
        default_name = f"route_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = filedialog.asksaveasfilename(
            title="保存路线", defaultextension=".json",
            filetypes=[("JSON 路线", "*.json"), ("GPX 路线", "*.gpx")],
            initialdir=_get_base_path() / "routes",
            initialfile=default_name,
        )
        if filepath:
            if RouteGenerator.save_to_file(self._route, filepath):
                logger.info(f"路线已保存: {filepath}")
                messagebox.showinfo("成功", f"路线已保存到:\n{filepath}")

    def _settings_popup(self):
        popup = tk.Toplevel(self.root, bg=Colors.CARD)
        popup.title("设置"); popup.geometry("360x220")
        popup.transient(self.root)
        tk.Label(popup, text="连接设置", bg=Colors.CARD, fg=Colors.TEXT,
                 font=("Microsoft YaHei", 13, "bold")).pack(pady=(14, 8))
        fields = [("ADB 路径", "adb_path"), ("设备地址", "device_addr"), ("高德 Key", "amap_api_key")]
        for label, key in fields:
            r = tk.Frame(popup, bg=Colors.CARD); r.pack(fill="x", padx=20, pady=3)
            tk.Label(r, text=label, bg=Colors.CARD, fg=Colors.TEXT_DIM, width=9, anchor="w").pack(side="left")
            e = tk.Entry(r, bg=Colors.BG, fg=Colors.TEXT, relief="flat", width=28, font=("Consolas", 9))
            e.insert(0, self._config.get(key, "")); e.pack(side="left")
        tk.Button(popup, text="保存", bg=Colors.ACCENT, fg="white", relief="flat", bd=0,
                  command=popup.destroy, padx=24, pady=6).pack(pady=12)

    # ══════════════════════════════════════════════════════
    # 模拟控制
    # ══════════════════════════════════════════════════════

    def _start(self):
        if not self._route:
            messagebox.showwarning("提示", "请先生成路线")
            return
        if not self._injector:
            messagebox.showwarning("提示", "请先连接模拟器")
            return

        if self._simulator is None:
            self._simulator = Simulator(
                injector=self._injector, route=self._route,
                speed_kmh=self._pace_calc.speed_kmh,
                update_interval_ms=1500, jitter_meters=2.0,
                loop_mode=self._loop_var.get(),
            )
            self._simulator.on_progress(self._on_progress)
            self._simulator.on_state_change(self._on_state)
        else:
            self._simulator.route = self._route
            self._simulator.speed_kmh = self._pace_calc.speed_kmh
            self._simulator._loop_mode = self._loop_var.get()

        # 设置目标速度线
        self._speed_chart.set_target_speed(self._pace_calc.speed_kmh)

        if self._simulator.start():
            self._start_btn.configure(text="▶  跑步中...", state="disabled")
            self._pause_btn.configure(state="normal")
            self._stop_btn.configure(state="normal")
            logger.info(f"开始跑步: {self._pace_calc.speed_kmh:.1f} km/h, 循环={self._loop_var.get()}")

    def _toggle_pause(self):
        if self._simulator:
            self._simulator.toggle_pause()

    def _stop(self):
        if self._simulator:
            info = self._simulator.get_progress()
            self._simulator.stop()
        else:
            info = None
        self._start_btn.configure(text="▶  开始跑步", state="normal")
        self._pause_btn.configure(state="disabled")
        self._stop_btn.configure(state="disabled")
        # 打卡
        today = datetime.now()
        self._calendar.mark_run(today.day)
        # 添加历史记录
        if info and info.distance_m > 10:  # 至少跑了10米才记录
            elapsed = info.elapsed_sec
            m, s = int(elapsed // 60), int(elapsed % 60)
            pace = info.pace_min_per_km
            ps = f"{int(pace)}'{int((pace%1)*60):02d}\"" if pace > 0 else "--'--\""
            self._history.add_run(today.strftime("%m-%d"), info.distance_m / 1000,
                                  f"{m:02d}:{s:02d}", ps)

    def _on_progress(self, info: ProgressInfo):
        self.root.after(0, lambda: self._update_ui(info))

    def _update_ui(self, info: ProgressInfo):
        dkm = info.distance_m / 1000.0
        speed = info.current_speed_ms * 3.6
        self._speed_chart.push(speed, dkm)
        self._map_view.update_current_position(info.current_lat, info.current_lng)
        # 更新环形进度 → 当前路线完成度
        total = info.total_m / 1000.0 if info.total_m > 0 else dkm
        self._ring.set_progress(
            info.progress_pct / 100.0,
            current_km=dkm, total_km=total,
            remaining_km=info.remaining_m / 1000.0,
        )

    def _on_state(self, old, new):
        if new == RunState.PAUSED:
            self.root.after(0, lambda: self._pause_btn.configure(text="▶"))
        elif new == RunState.RUNNING:
            self.root.after(0, lambda: self._pause_btn.configure(text="⏸"))
        elif new == RunState.FINISHED:
            self.root.after(0, self._stop)

    def _on_close(self):
        if self._simulator and self._simulator.state == RunState.RUNNING:
            self._simulator.stop()
        if self._injector:
            self._injector.disconnect()
        if self._adb:
            self._adb.disconnect()
        self.root.destroy()

    def run(self):
        self.root.after(1000, self._connect)
        self.root.mainloop()
