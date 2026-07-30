"""
交互式地图组件 - 基于 OpenStreetMap 的全国地图

功能:
- 显示全国/全球可缩放地图（无需 API Key）
- 点击加点绘制跑步路线
- 右键撤销最后一个点
- 显示路线预览 + 实时位置标记
- 地址搜索跳转

依赖: tkintermapview (pip install tkintermapview)
"""

import tkinter as tk
from tkinter import ttk
import logging
from typing import Optional, Callable
from pathlib import Path

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.route_engine import Route, Waypoint, haversine_distance

try:
    from tkintermapview import TkinterMapView
    HAS_MAPVIEW = True
except ImportError:
    HAS_MAPVIEW = False
    TkinterMapView = None

logger = logging.getLogger(__name__)


class InteractiveMapView(tk.Frame):
    """
    交互式地图视图

    封装 tkintermapview，提供路线绘制和实时位置显示功能。

    操作:
    - 左键点击: 添加路径点
    - 右键点击: 撤销最后一个点
    - 滚轮: 缩放
    - 左键拖拽: 平移
    - 搜索框: 地址搜索跳转
    """

    def __init__(
        self,
        parent,
        width: int = 700,
        height: int = 500,
        default_lat: float = 39.9923,
        default_lng: float = 116.3264,
        default_zoom: int = 15,
    ):
        """
        Args:
            parent: 父容器
            width, height: 地图尺寸
            default_lat, default_lng: 默认中心坐标
            default_zoom: 默认缩放级别 (1-19)
        """
        super().__init__(parent, width=width, height=height)

        if not HAS_MAPVIEW:
            self._show_fallback()
            return

        # 尺寸
        self._width = width
        self._height = height
        self._default_lat = default_lat
        self._default_lng = default_lng
        self._default_zoom = default_zoom

        # 绘制状态
        self._drawing_mode = False
        self._draw_points: list[Waypoint] = []
        self._draw_markers: list = []       # 地图标记
        self._draw_path_id: Optional[int] = None  # 路径 ID

        # 路线显示
        self._route_path_id: Optional[int] = None
        self._current_marker = None
        self._start_marker = None
        self._end_marker = None

        # 回调
        self._on_drawing_changed: Optional[Callable] = None
        self._on_route_finished: Optional[Callable[[Route], None]] = None

        # 多种瓦片源 (用户可按需切换)
        self._tile_servers = [
            ("CartoDB Lite", "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"),
            ("OSM 官方", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
            ("OSM France", "https://a.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png"),
        ]
        self._current_tile_idx = 0  # 默认 CartoDB Lite (最轻量最快)

        # 构建 UI
        self._build_map()

    def _show_fallback(self):
        """地图库不可用时的降级提示"""
        label = tk.Label(
            self, text="⚠ 地图组件不可用\n\n请安装: pip install tkintermapview",
            font=("Microsoft YaHei", 14), fg="#888888", bg="#2d2d2d",
        )
        label.place(relx=0.5, rely=0.5, anchor="center")

    def _build_map(self):
        """构建地图控件"""
        # 顶部工具栏
        toolbar = tk.Frame(self, bg="#2d2d2d", height=36)
        toolbar.pack(fill="x", side="top")
        toolbar.pack_propagate(False)

        # 搜索框
        tk.Label(toolbar, text="搜索:", bg="#2d2d2d", fg="#cccccc",
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=(5, 2))

        self._search_var = tk.StringVar()
        search_entry = tk.Entry(
            toolbar, textvariable=self._search_var, width=20,
            bg="#3d3d3d", fg="#ffffff", insertbackground="#ffffff",
            relief="flat", font=("Microsoft YaHei", 9),
        )
        search_entry.pack(side="left", padx=2, pady=4)
        search_entry.bind("<Return>", lambda e: self.search_address())

        tk.Button(
            toolbar, text="🔍", bg="#3498db", fg="white", relief="flat",
            command=self.search_address, cursor="hand2",
            font=("", 9), width=3,
        ).pack(side="left", padx=2)

        # 分隔
        ttk.Separator(toolbar, orient="vertical").pack(side="left", padx=8, fill="y")

        # 绘制模式按钮
        self._draw_btn = tk.Button(
            toolbar, text="✏ 绘制路线", bg="#2d2d2d", fg="#cccccc",
            relief="flat", command=self.toggle_drawing_mode,
            cursor="hand2", font=("Microsoft YaHei", 9),
        )
        self._draw_btn.pack(side="left", padx=2)

        # 绘制操作按钮
        self._undo_btn = tk.Button(
            toolbar, text="↩ 撤销", bg="#2d2d2d", fg="#cccccc",
            relief="flat", command=self.undo_last_point,
            cursor="hand2", font=("Microsoft YaHei", 9), state="disabled",
        )
        self._undo_btn.pack(side="left", padx=2)

        self._clear_btn = tk.Button(
            toolbar, text="✖ 清除", bg="#2d2d2d", fg="#cccccc",
            relief="flat", command=self.clear_drawing,
            cursor="hand2", font=("Microsoft YaHei", 9), state="disabled",
        )
        self._clear_btn.pack(side="left", padx=2)

        self._finish_btn = tk.Button(
            toolbar, text="✓ 完成路线", bg="#27ae60", fg="white",
            relief="flat", command=self.finish_drawing,
            cursor="hand2", font=("Microsoft YaHei", 9, "bold"), state="disabled",
        )
        self._finish_btn.pack(side="left", padx=2)

        # 状态提示
        self._draw_status = tk.Label(
            toolbar, text="", bg="#2d2d2d", fg="#f39c12",
            font=("Microsoft YaHei", 8),
        )
        self._draw_status.pack(side="left", padx=8)

        # 点数显示
        self._point_count_label = tk.Label(
            toolbar, text="", bg="#2d2d2d", fg="#888888",
            font=("Microsoft YaHei", 8),
        )
        self._point_count_label.pack(side="right", padx=5)

        # 瓦片切换按钮
        ts_name = self._tile_servers[self._current_tile_idx][0]
        self._tile_btn = tk.Button(
            toolbar, text=f"🗺 {ts_name}", bg="#2d2d2d", fg="#94a3b8",
            relief="flat", command=self._cycle_tile_server,
            cursor="hand2", font=("Microsoft YaHei", 8),
        )
        self._tile_btn.pack(side="right", padx=4)

        # 地图主体
        map_frame = tk.Frame(self, bg="#1e1e1e")
        map_frame.pack(fill="both", expand=True, side="bottom")

        # 离线瓦片缓存路径
        import tempfile
        cache_dir = os.path.join(tempfile.gettempdir(), "campusrunner_tiles")
        os.makedirs(cache_dir, exist_ok=True)
        cache_db = os.path.join(cache_dir, "tiles_cache.db")

        self._map = TkinterMapView(
            map_frame,
            width=self._width,
            height=self._height - 36,
            corner_radius=0,
            database_path=cache_db,       # SQLite 离线瓦片缓存
            use_database_only=False,       # 允许在线加载新瓦片
            max_zoom=19,
        )

        # 设置初始瓦片服务器
        self._apply_tile_server()

        self._map.pack(fill="both", expand=True)

        # 设置初始位置 (低缩放先快速显示)
        self._map.set_position(self._default_lat, self._default_lng)
        self._map.set_zoom(min(self._default_zoom, 14))

        # 绑定点击事件
        self._map.add_left_click_map_command(self._on_map_left_click)
        self._map.add_right_click_menu_command(
            "删除上一个点", self.undo_last_point,
        )
        self._map.add_right_click_menu_command(
            "定位此处为中心", self._center_on_click,
        )

    # ─── 地图操作 ──────────────────────────────────────

    def _apply_tile_server(self):
        """应用当前选中的瓦片服务器"""
        if not HAS_MAPVIEW:
            return
        name, url = self._tile_servers[self._current_tile_idx]
        try:
            self._map.set_tile_server(url, max_zoom=19)
            logger.debug(f"瓦片源: {name}")
        except Exception:
            pass

    def _cycle_tile_server(self):
        """循环切换瓦片服务器"""
        self._current_tile_idx = (self._current_tile_idx + 1) % len(self._tile_servers)
        self._apply_tile_server()
        name = self._tile_servers[self._current_tile_idx][0]
        self._tile_btn.configure(text=f"🗺 {name}")
        logger.info(f"切换到瓦片源: {name}")

    def set_position(self, lat: float, lng: float):
        """设置地图中心"""
        if HAS_MAPVIEW:
            self._map.set_position(lat, lng)

    def set_zoom(self, zoom: int):
        """设置缩放级别"""
        if HAS_MAPVIEW:
            self._map.set_zoom(zoom)

    def search_address(self, address: str = ""):
        """
        搜索地址并跳转

        使用 tkintermapview 内置的地理编码功能。
        """
        query = address or self._search_var.get().strip()
        if not query:
            return

        if HAS_MAPVIEW:
            logger.info(f"搜索地址: {query}")
            self._map.set_address(query)

    def _center_on_click(self, coords):
        """右键菜单：定位到点击位置为中心"""
        if HAS_MAPVIEW:
            self._map.set_position(coords[0], coords[1])

    # ─── 绘制模式 ──────────────────────────────────────

    def toggle_drawing_mode(self):
        """切换绘制模式"""
        self._drawing_mode = not self._drawing_mode

        if self._drawing_mode:
            self._draw_btn.configure(bg="#e74c3c", text="✏ 绘制中...")
            self._draw_status.configure(text="🖱 点击地图添加路径点 | 右键撤销")
            self._undo_btn.configure(state="normal")
            self._clear_btn.configure(state="normal")
            logger.info("绘制模式已开启 - 点击地图添加路径点")
        else:
            self._draw_btn.configure(bg="#2d2d2d", text="✏ 绘制路线")
            self._draw_status.configure(text="")
            self._undo_btn.configure(state="disabled")
            self._clear_btn.configure(state="disabled")
            logger.info("绘制模式已关闭")

    def _on_map_left_click(self, coords):
        """
        地图左键点击回调

        如果处于绘制模式，添加路径点。

        Args:
            coords: (lat, lng) 元组
        """
        if not self._drawing_mode:
            return

        lat, lng = coords
        point = Waypoint(lat, lng)
        self._draw_points.append(point)

        # 添加标记
        marker = self._map.set_marker(
            lat, lng,
            text=str(len(self._draw_points)),
            text_color="white",
            font=("Arial", 9, "bold"),
        )
        self._draw_markers.append(marker)

        # 更新连线
        self._update_draw_path()

        # 更新状态
        n = len(self._draw_points)
        self._point_count_label.configure(text=f"已添加 {n} 个点")
        self._finish_btn.configure(state="normal" if n >= 2 else "disabled")

        if n >= 2:
            dist = haversine_distance(
                self._draw_points[0].lat, self._draw_points[0].lng,
                self._draw_points[-1].lat, self._draw_points[-1].lng,
            )
            self._draw_status.configure(
                text=f"点 {n} | 距起点 {dist:.0f}m | 双击或✓完成"
            )

        # 触发回调
        if self._on_drawing_changed:
            self._on_drawing_changed(self._draw_points)

    def _update_draw_path(self):
        """更新绘制路线的连线"""
        if not HAS_MAPVIEW or len(self._draw_points) < 2:
            return

        # 删除旧路径
        if self._draw_path_id is not None:
            self._map.delete(self._draw_path_id)

        # 绘制新路径
        positions = [(wp.lat, wp.lng) for wp in self._draw_points]
        self._draw_path_id = self._map.set_path(positions, color="#e74c3c", width=3)

    def undo_last_point(self):
        """撤销最后一个路径点"""
        if not self._draw_points:
            return

        self._draw_points.pop()

        # 移除最后一个标记
        if self._draw_markers:
            last_marker = self._draw_markers.pop()
            try:
                last_marker.delete()
            except Exception:
                pass

        # 更新路径
        self._update_draw_path()

        n = len(self._draw_points)
        self._point_count_label.configure(text=f"已添加 {n} 个点" if n > 0 else "")
        self._finish_btn.configure(state="normal" if n >= 2 else "disabled")

        if n == 0 and self._draw_path_id is not None:
            self._map.delete(self._draw_path_id)
            self._draw_path_id = None
            self._draw_status.configure(text="🖱 点击地图添加路径点 | 右键撤销")

        if self._on_drawing_changed:
            self._on_drawing_changed(self._draw_points)

    def clear_drawing(self):
        """清除所有手绘内容"""
        # 清除标记
        for marker in self._draw_markers:
            try:
                marker.delete()
            except Exception:
                pass
        self._draw_markers.clear()

        # 清除路径
        if self._draw_path_id is not None:
            try:
                self._map.delete(self._draw_path_id)
            except Exception:
                pass
            self._draw_path_id = None

        self._draw_points.clear()
        self._point_count_label.configure(text="")
        self._finish_btn.configure(state="disabled")
        self._draw_status.configure(text="🖱 点击地图添加路径点 | 右键撤销")

        if self._on_drawing_changed:
            self._on_drawing_changed(self._draw_points)

    def finish_drawing(self):
        """
        完成绘制，生成 Route 对象

        Returns:
            Route 对象或 None（点数不足时）
        """
        if len(self._draw_points) < 2:
            logger.warning("至少需要 2 个路径点")
            return None

        # 生成 Route
        route = Route(
            waypoints=list(self._draw_points),
            name=f"手绘路线 ({len(self._draw_points)}点)",
        )

        # 关闭绘制模式
        if self._drawing_mode:
            self.toggle_drawing_mode()

        # 显示完成的路线
        self.show_route(route)

        logger.info(f"手绘路线完成: {route.name}, {route.total_distance_m:.0f}m")

        # 触发回调
        if self._on_route_finished:
            self._on_route_finished(route)

        return route

    def set_on_drawing_changed(self, callback: Callable):
        """设置绘制变化回调"""
        self._on_drawing_changed = callback

    def set_on_route_finished(self, callback: Callable[[Route], None]):
        """设置路线完成回调"""
        self._on_route_finished = callback

    # ─── 路线显示 ──────────────────────────────────────

    def show_route(self, route: Route):
        """
        在地图上显示一条路线

        Args:
            route: Route 对象
        """
        if not HAS_MAPVIEW:
            return

        # 清除旧路线
        self.clear_route_display()

        if not route.waypoints:
            return

        # 绘制路线
        positions = [(wp.lat, wp.lng) for wp in route.waypoints]
        self._route_path_id = self._map.set_path(positions, color="#3498db", width=3)

        # 起点标记
        start = route.waypoints[0]
        self._start_marker = self._map.set_marker(
            start.lat, start.lng,
            text="起点",
            text_color="white",
            marker_color_circle="#2ecc71",
            marker_color_outside="#27ae60",
        )

        # 终点标记
        end = route.waypoints[-1]
        self._end_marker = self._map.set_marker(
            end.lat, end.lng,
            text="终点",
            text_color="white",
            marker_color_circle="#e74c3c",
            marker_color_outside="#c0392b",
        )

        # 自适应缩放查看整条路线
        if len(positions) >= 2:
            lats = [p[0] for p in positions]
            lngs = [p[1] for p in positions]
            self._map.fit_bounding_box(
                (max(lats), min(lngs)),  # top-left
                (min(lats), max(lngs)),  # bottom-right
            )

    def clear_route_display(self):
        """清除路线显示（保留手绘内容）"""
        if not HAS_MAPVIEW:
            return

        if self._route_path_id is not None:
            try:
                self._map.delete(self._route_path_id)
            except Exception:
                pass
            self._route_path_id = None

        for marker in [self._start_marker, self._end_marker, self._current_marker]:
            if marker is not None:
                try:
                    marker.delete()
                except Exception:
                    pass
        self._start_marker = None
        self._end_marker = None
        self._current_marker = None

    def update_current_position(self, lat: float, lng: float):
        """
        更新实时位置标记

        Args:
            lat, lng: 当前位置
        """
        if not HAS_MAPVIEW:
            return

        # 删除旧标记
        if self._current_marker is not None:
            try:
                self._current_marker.delete()
            except Exception:
                pass

        # 创建新标记
        self._current_marker = self._map.set_marker(
            lat, lng,
            text="📍",
            text_color="white",
            marker_color_circle="#3498db",
            marker_color_outside="#2980b9",
            font=("", 14),
        )

    def get_drawing_points(self) -> list[Waypoint]:
        """获取当前手绘路径点"""
        return list(self._draw_points)

    @property
    def drawing_mode(self) -> bool:
        return self._drawing_mode

    @property
    def has_points(self) -> bool:
        return len(self._draw_points) >= 2
