"""
现代 SaaS 仪表盘组件库

组件:
- KPICard: 数据指标卡片（图标+标签+数值+趋势）
- SpeedChart: 实时速度折线图（Canvas 手绘）
- RingProgress: 环形进度指示器
- StatRow: 统计数据行
"""

import math
import tkinter as tk
from collections import deque
from typing import Optional

# ─── 配色方案 ───────────────────────────────────────────

BLUE_PRIMARY = "#2563eb"       # 主蓝
BLUE_LIGHT = "#3b82f6"         # 浅蓝
BLUE_DARK = "#1d4ed8"          # 深蓝
BLUE_GLOW = "#60a5fa"          # 发光蓝
BG_DARK = "#0f172a"            # 深色背景
BG_CARD = "#1e293b"            # 卡片背景
BG_SIDEBAR = "#0c1222"         # 侧边栏
TEXT_PRIMARY = "#f1f5f9"       # 主文字
TEXT_SECONDARY = "#94a3b8"     # 次要文字
TEXT_MUTED = "#64748b"         # 暗淡文字
ACCENT_GREEN = "#10b981"       # 成功绿
ACCENT_RED = "#ef4444"         # 危险红
ACCENT_AMBER = "#f59e0b"       # 警告黄
BORDER = "#334155"             # 边框


class KPICard(tk.Frame):
    """
    KPI 数据卡片

    显示一个核心指标：图标、标签、数值、单位、可选趋势箭头。
    """

    def __init__(
        self,
        parent,
        icon: str = "📊",
        label: str = "指标",
        value: str = "--",
        unit: str = "",
        trend: Optional[float] = None,
        **kwargs,
    ):
        super().__init__(
            parent,
            bg=BG_CARD,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            **kwargs,
        )

        # 顶部蓝色色条
        self._accent_bar = tk.Frame(self, bg=BLUE_PRIMARY, height=3)
        self._accent_bar.pack(fill="x", side="top")

        # 内容区域
        content = tk.Frame(self, bg=BG_CARD)
        content.pack(fill="both", expand=True, padx=16, pady=12)

        # 图标 + 标签行
        header = tk.Frame(content, bg=BG_CARD)
        header.pack(fill="x")

        self._icon_label = tk.Label(
            header, text=icon, bg=BG_CARD, fg=TEXT_PRIMARY,
            font=("Segoe UI Emoji", 16),
        )
        self._icon_label.pack(side="left")

        self._label = tk.Label(
            header, text=label, bg=BG_CARD, fg=TEXT_SECONDARY,
            font=("Microsoft YaHei", 10), anchor="w",
        )
        self._label.pack(side="left", padx=8)

        # 趋势指示
        if trend is not None:
            trend_text = f"▲ {trend:+.1f}%" if trend >= 0 else f"▼ {trend:+.1f}%"
            trend_color = ACCENT_GREEN if trend >= 0 else ACCENT_RED
            tk.Label(
                header, text=trend_text, bg=BG_CARD, fg=trend_color,
                font=("Consolas", 9),
            ).pack(side="right")

        # 数值 + 单位
        value_row = tk.Frame(content, bg=BG_CARD)
        value_row.pack(fill="x", pady=(8, 0))

        self._value_label = tk.Label(
            value_row, text=value, bg=BG_CARD, fg=TEXT_PRIMARY,
            font=("Consolas", 28, "bold"),
        )
        self._value_label.pack(side="left")

        if unit:
            tk.Label(
                value_row, text=f" {unit}", bg=BG_CARD, fg=TEXT_SECONDARY,
                font=("Microsoft YaHei", 12),
            ).pack(side="left", pady=(12, 0))

    def set_value(self, value: str):
        """更新数值"""
        self._value_label.configure(text=value)

    def set_label(self, text: str):
        """更新标签"""
        self._label.configure(text=text)


class SpeedChart(tk.Canvas):
    """
    实时速度折线图

    使用 Canvas 手绘，无需 matplotlib。
    显示最近 N 个数据点，自动滚动。
    """

    def __init__(self, parent, max_points: int = 60, height: int = 180, **kwargs):
        super().__init__(
            parent,
            bg=BG_CARD,
            height=height,
            highlightthickness=1,
            highlightbackground=BORDER,
            **kwargs,
        )
        self._max_points = max_points
        self._data: deque[float] = deque(maxlen=max_points)
        self._chart_h = height
        self._margin_l = 40
        self._margin_r = 16
        self._margin_t = 20
        self._margin_b = 28

        # 初始填充 0
        for _ in range(min(20, max_points)):
            self._data.append(0.0)

        self._draw()

    def push(self, value: float):
        """添加新数据点并重绘"""
        self._data.append(value)
        self._draw()

    def _draw(self):
        """绘制折线图"""
        self.delete("all")
        w = self.winfo_width() or 400
        h = self._chart_h

        chart_w = w - self._margin_l - self._margin_r
        chart_h = h - self._margin_t - self._margin_b

        if not self._data:
            return

        values = list(self._data)
        min_v = min(values) * 0.9 if min(values) > 0 else 0
        max_v = max(values) * 1.1 if max(values) > 0 else 20
        if max_v - min_v < 1:
            max_v = min_v + 5

        # Y 轴网格线
        for i in range(5):
            y = self._margin_t + chart_h * i / 4
            self.create_line(
                self._margin_l, y, w - self._margin_r, y,
                fill="#1e3a5f", dash=(2, 4),
            )
            val = max_v - (max_v - min_v) * i / 4
            self.create_text(
                self._margin_l - 6, y, text=f"{val:.1f}",
                fill=TEXT_MUTED, font=("Consolas", 8), anchor="e",
            )

        # 渐变填充 (底部)
        points_bottom = []
        for i, v in enumerate(values):
            x = self._margin_l + chart_w * i / (len(values) - 1) if len(values) > 1 else self._margin_l + chart_w / 2
            ratio = (v - min_v) / (max_v - min_v) if max_v > min_v else 0.5
            ratio = max(0.0, min(1.0, ratio))
            y = self._margin_t + chart_h * (1 - ratio)
            points_bottom.append((x, y))
            points_bottom.append((x, self._margin_t + chart_h))

        if len(points_bottom) >= 6:
            # 渐变填充多边形
            fill_pts = []
            for i in range(len(values)):
                x = self._margin_l + chart_w * i / (len(values) - 1) if len(values) > 1 else self._margin_l + chart_w / 2
                ratio = (values[i] - min_v) / (max_v - min_v) if max_v > min_v else 0.5
                ratio = max(0.0, min(1.0, ratio))
                y = self._margin_t + chart_h * (1 - ratio)
                fill_pts.extend([x, y])
            fill_pts.extend([self._margin_l + chart_w, self._margin_t + chart_h])
            fill_pts.extend([self._margin_l, self._margin_t + chart_h])

            # 用半透明多边形模拟渐变
            flat = [coord for coord in fill_pts]
            self.create_polygon(
                *flat, fill=BLUE_PRIMARY, outline="", stipple="",
            )
            # 覆盖更透明的层
            self.create_polygon(
                *flat,
                fill="", outline="",
            )

        # 折线
        line_pts = []
        for i, v in enumerate(values):
            x = self._margin_l + chart_w * i / (len(values) - 1) if len(values) > 1 else self._margin_l + chart_w / 2
            ratio = (v - min_v) / (max_v - min_v) if max_v > min_v else 0.5
            ratio = max(0.0, min(1.0, ratio))
            y = self._margin_t + chart_h * (1 - ratio)
            line_pts.extend([x, y])

        if len(line_pts) >= 4:
            self.create_line(
                *line_pts, fill=BLUE_GLOW, width=2.5, smooth=True,
            )

        # 最后一点的光晕
        if values:
            last_x = line_pts[-2] if len(line_pts) >= 2 else self._margin_l + chart_w / 2
            last_y = line_pts[-1] if len(line_pts) >= 2 else self._margin_t + chart_h / 2
            r = 4
            self.create_oval(
                last_x - r, last_y - r, last_x + r, last_y + r,
                fill=BLUE_GLOW, outline=BLUE_PRIMARY, width=2,
            )

        # 标题
        self.create_text(
            self._margin_l, 8, text="Speed (km/h)",
            fill=TEXT_SECONDARY, font=("Microsoft YaHei", 9), anchor="nw",
        )

        # 当前值
        current = values[-1]
        self.create_text(
            w - self._margin_r, 8, text=f"{current:.1f} km/h",
            fill=BLUE_GLOW, font=("Consolas", 9, "bold"), anchor="ne",
        )


class RingProgress(tk.Canvas):
    """
    环形进度指示器

    显示距离完成百分比，带渐变蓝色弧线。
    """

    def __init__(self, parent, size: int = 160, **kwargs):
        super().__init__(
            parent,
            bg=BG_CARD,
            width=size,
            height=size,
            highlightthickness=1,
            highlightbackground=BORDER,
            **kwargs,
        )
        self._size = size
        self._progress = 0.0  # 0.0 - 1.0
        self._center_text = "0%"
        self._sub_text = ""

    def set_progress(self, pct: float, center: str = "", sub: str = ""):
        """设置进度 0.0-1.0"""
        self._progress = max(0.0, min(1.0, pct))
        self._center_text = center
        self._sub_text = sub
        self._draw()

    def _draw(self):
        """绘制环形"""
        self.delete("all")
        cx = cy = self._size // 2
        r = self._size // 2 - 24
        width = 14

        # 背景圆环
        self.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            outline="#1e3a5f", width=width,
        )

        # 进度弧线（用多个短弧线模拟渐变）
        if self._progress > 0.001:
            steps = 100
            for i in range(int(self._progress * steps)):
                start = 90 - (i / steps) * 360
                extent = -360 / steps
                # 颜色从浅蓝渐变到主蓝
                ratio = i / steps
                r_color = int(0x25 + ratio * (0x3b - 0x25))
                g_color = int(0x63 + ratio * (0x82 - 0x63))
                b_color = int(0xeb + ratio * (0xf6 - 0xeb))
                color = f"#{r_color:02x}{g_color:02x}{b_color:02x}"
                self.create_arc(
                    cx - r, cy - r, cx + r, cy + r,
                    start=start, extent=extent,
                    outline=color, width=width, style="arc",
                )

        # 中心文字
        self.create_text(
            cx, cy - 6, text=self._center_text,
            fill=TEXT_PRIMARY, font=("Consolas", 22, "bold"),
            anchor="center",
        )
        if self._sub_text:
            self.create_text(
                cx, cy + 18, text=self._sub_text,
                fill=TEXT_SECONDARY, font=("Microsoft YaHei", 9),
                anchor="center",
            )

        # 标题
        self.create_text(
            cx, self._size - 8, text="completion",
            fill=TEXT_MUTED, font=("Microsoft YaHei", 8),
            anchor="s",
        )


class StatRow(tk.Frame):
    """单行统计数据"""

    def __init__(self, parent, label: str = "", value: str = "", **kwargs):
        super().__init__(parent, bg=BG_CARD, **kwargs)

        tk.Label(
            self, text=label, bg=BG_CARD, fg=TEXT_SECONDARY,
            font=("Microsoft YaHei", 9), anchor="w",
        ).pack(side="left")

        tk.Label(
            self, text=value, bg=BG_CARD, fg=TEXT_PRIMARY,
            font=("Consolas", 9, "bold"), anchor="e",
        ).pack(side="right")
