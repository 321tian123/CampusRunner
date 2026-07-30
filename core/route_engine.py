"""
路线引擎 - 生成、加载和管理跑步路线

支持圆形跑道、矩形路线、自定义路径点，以及 GPX/JSON 文件导入导出。
"""

import json
import math
import random
import logging
from typing import Optional, NamedTuple
from pathlib import Path

logger = logging.getLogger(__name__)

# 地球半径（米）
EARTH_RADIUS = 6371000.0


class Waypoint(NamedTuple):
    """路径点"""
    lat: float  # 纬度
    lng: float  # 经度
    alt: float = 0.0  # 海拔


class Route:
    """跑步路线"""

    def __init__(self, waypoints: list[Waypoint], name: str = "未命名路线"):
        self.waypoints = waypoints
        self.name = name
        self._distances: Optional[list[float]] = None  # 累积距离缓存

    @property
    def point_count(self) -> int:
        return len(self.waypoints)

    @property
    def total_distance_m(self) -> float:
        """总距离（米）"""
        if not self._distances:
            self._compute_cumulative_distances()
        return self._distances[-1] if self._distances else 0.0

    def _compute_cumulative_distances(self):
        """预计算累积距离"""
        self._distances = [0.0]
        for i in range(1, len(self.waypoints)):
            d = haversine_distance(
                self.waypoints[i - 1].lat, self.waypoints[i - 1].lng,
                self.waypoints[i].lat, self.waypoints[i].lng,
            )
            self._distances.append(self._distances[-1] + d)

    def get_position_at_distance(self, distance_m: float) -> Waypoint:
        """
        根据已跑距离获取插值后的位置

        采用线性插值在两个相邻路径点之间计算当前位置。

        Args:
            distance_m: 从起点开始的累计距离（米）

        Returns:
            插值后的 Waypoint
        """
        if not self.waypoints:
            return Waypoint(0, 0)

        if distance_m <= 0:
            return self.waypoints[0]

        if distance_m >= self.total_distance_m:
            return self.waypoints[-1]

        if not self._distances:
            self._compute_cumulative_distances()

        # 找到 distance_m 所在的区间
        for i in range(1, len(self._distances)):
            if self._distances[i] >= distance_m:
                # 在 waypoints[i-1] 和 waypoints[i] 之间插值
                seg_start_dist = self._distances[i - 1]
                seg_end_dist = self._distances[i]
                seg_length = seg_end_dist - seg_start_dist

                if seg_length < 0.001:
                    return self.waypoints[i - 1]

                t = (distance_m - seg_start_dist) / seg_length
                t = max(0.0, min(1.0, t))  # clamp

                lat = self.waypoints[i - 1].lat + t * (self.waypoints[i].lat - self.waypoints[i - 1].lat)
                lng = self.waypoints[i - 1].lng + t * (self.waypoints[i].lng - self.waypoints[i - 1].lng)
                alt = self.waypoints[i - 1].alt + t * (self.waypoints[i].alt - self.waypoints[i - 1].alt)

                return Waypoint(lat, lng, alt)

        return self.waypoints[-1]

    def get_progress_info(self, distance_m: float) -> dict:
        """
        获取某距离处的进度信息

        Returns:
            包含进度百分比、当前位置、预计剩余距离等的字典
        """
        total = self.total_distance_m
        distance_m = max(0.0, min(total, distance_m))

        return {
            "distance_m": distance_m,
            "total_m": total,
            "progress_pct": (distance_m / total * 100) if total > 0 else 0,
            "remaining_m": total - distance_m,
            "position": self.get_position_at_distance(distance_m),
            "route_name": self.name,
        }

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "name": self.name,
            "waypoints": [
                {"lat": wp.lat, "lng": wp.lng, "alt": wp.alt}
                for wp in self.waypoints
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Route":
        """从字典反序列化"""
        waypoints = [
            Waypoint(wp["lat"], wp["lng"], wp.get("alt", 0.0))
            for wp in data["waypoints"]
        ]
        return cls(waypoints, name=data.get("name", "未命名路线"))


class RouteGenerator:
    """路线生成器 - 创建各种形状的跑步路线"""

    @staticmethod
    def generate_circle(
        center_lat: float,
        center_lng: float,
        radius_m: float = 200.0,
        num_points: int = 60,
        name: str = "圆形跑道",
    ) -> Route:
        """
        生成圆形（环形）跑道

        Args:
            center_lat: 圆心纬度
            center_lng: 圆心经度
            radius_m: 半径（米）
            num_points: 路径点数量
            name: 路线名称

        Returns:
            圆形 Route
        """
        waypoints = []
        for i in range(num_points):
            angle = (2 * math.pi * i) / num_points
            # 将米偏移转换为经纬度偏移
            lat_offset = (radius_m * math.cos(angle)) / (EARTH_RADIUS * math.pi / 180)
            lng_offset = (radius_m * math.sin(angle)) / (
                EARTH_RADIUS * math.cos(center_lat * math.pi / 180) * math.pi / 180
            )
            waypoints.append(Waypoint(center_lat + lat_offset, center_lng + lng_offset))

        return Route(waypoints, name=name)

    @staticmethod
    def generate_rectangle(
        top_left_lat: float,
        top_left_lng: float,
        width_m: float = 400.0,
        height_m: float = 200.0,
        num_points_per_side: int = 20,
        name: str = "矩形路线",
    ) -> Route:
        """
        生成矩形跑道

        Args:
            top_left_lat: 左上角纬度
            top_left_lng: 左上角经度
            width_m: 宽度（米，经度方向）
            height_m: 高度（米，纬度方向）
            num_points_per_side: 每边点数
            name: 路线名称

        Returns:
            矩形 Route
        """
        lat_per_m = 1.0 / (EARTH_RADIUS * math.pi / 180)
        lng_per_m = 1.0 / (
            EARTH_RADIUS * math.cos(top_left_lat * math.pi / 180) * math.pi / 180
        )

        # 四个角
        top_right_lat = top_left_lat
        top_right_lng = top_left_lng + width_m * lng_per_m
        bottom_right_lat = top_left_lat - height_m * lat_per_m
        bottom_right_lng = top_right_lng
        bottom_left_lat = bottom_right_lat
        bottom_left_lng = top_left_lng

        corners = [
            (top_left_lat, top_left_lng),
            (top_right_lat, top_right_lng),
            (bottom_right_lat, bottom_right_lng),
            (bottom_left_lat, bottom_left_lng),
        ]

        waypoints = []
        for i in range(4):
            start_lat, start_lng = corners[i]
            end_lat, end_lng = corners[(i + 1) % 4]
            for j in range(num_points_per_side):
                t = j / num_points_per_side
                lat = start_lat + t * (end_lat - start_lat)
                lng = start_lng + t * (end_lng - start_lng)
                waypoints.append(Waypoint(lat, lng))

        return Route(waypoints, name=name)

    @staticmethod
    def generate_out_and_back(
        start_lat: float,
        start_lng: float,
        bearing_deg: float,
        length_m: float = 2500.0,
        num_points: int = 100,
        name: str = "折返路线",
    ) -> Route:
        """
        生成折返路线

        Args:
            start_lat: 起点纬度
            start_lng: 起点经度
            bearing_deg: 前进方位角（度，0=北，90=东）
            length_m: 单程距离（米）
            num_points: 总路径点数
            name: 路线名称

        Returns:
            折返 Route
        """
        waypoints = []
        half_points = num_points // 2

        # 去程
        for i in range(half_points):
            t = i / half_points
            dist = t * length_m
            lat, lng = _point_at_bearing(start_lat, start_lng, bearing_deg, dist)
            waypoints.append(Waypoint(lat, lng))

        # 返程
        for i in range(half_points):
            t = i / half_points
            dist = (1 - t) * length_m
            lat, lng = _point_at_bearing(start_lat, start_lng, bearing_deg, dist)
            waypoints.append(Waypoint(lat, lng))

        return Route(waypoints, name=name)

    @staticmethod
    def add_gps_jitter(route: Route, jitter_meters: float = 3.0) -> Route:
        """
        给路线添加 GPS 随机抖动，模拟真实 GPS 误差

        Args:
            route: 原始路线
            jitter_meters: 抖动范围（米）

        Returns:
            带抖动的新路线
        """
        jittered = []
        for wp in route.waypoints:
            # 随机偏移
            offset_lat = random.uniform(-jitter_meters, jitter_meters) / (
                EARTH_RADIUS * math.pi / 180
            )
            offset_lng = random.uniform(-jitter_meters, jitter_meters) / (
                EARTH_RADIUS
                * math.cos(wp.lat * math.pi / 180)
                * math.pi
                / 180
            )
            jittered.append(
                Waypoint(wp.lat + offset_lat, wp.lng + offset_lng, wp.alt)
            )

        return Route(jittered, name=f"{route.name} (带抖动)")

    @staticmethod
    def load_from_file(filepath: str) -> Optional[Route]:
        """
        从文件加载路线

        支持 JSON 和 GPX 格式

        Args:
            filepath: 文件路径

        Returns:
            Route 或 None
        """
        path = Path(filepath)
        if not path.exists():
            logger.error(f"路线文件不存在: {filepath}")
            return None

        suffix = path.suffix.lower()

        try:
            if suffix == ".json":
                return _load_json_route(path)
            elif suffix == ".gpx":
                return _load_gpx_route(path)
            else:
                logger.error(f"不支持的路线文件格式: {suffix}")
                return None
        except Exception as e:
            logger.error(f"加载路线文件失败: {e}")
            return None

    @staticmethod
    def save_to_file(route: Route, filepath: str) -> bool:
        """
        保存路线到文件 (JSON 或 GPX 格式)

        Args:
            route: 路线对象
            filepath: 保存路径 (.json 或 .gpx)

        Returns:
            成功标志
        """
        path = Path(filepath)
        suffix = path.suffix.lower()

        try:
            if suffix == ".gpx":
                return _save_gpx_route(route, filepath)
            else:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(route.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"路线已保存到: {filepath}")
            return True
        except Exception as e:
            logger.error(f"保存路线失败: {e}")
            return False

    @staticmethod
    def generate_campus_default(
        center_lat: float,
        center_lng: float,
        total_distance_m: float = 2000,
        name: str = "校园标准跑道",
    ) -> Route:
        """
        生成一个逼真的校园跑路线（环形+自然弯曲）

        结合圆形跑道和随机偏移来模拟真实校园路径。

        Args:
            center_lat: 校园中心纬度
            center_lng: 校园中心经度
            total_distance_m: 目标总距离（米）
            name: 路线名称

        Returns:
            Route
        """
        # 使用椭圆 + 正弦扰动的复杂路径
        radius = total_distance_m / (2 * math.pi) * 0.7
        num_points = max(30, int(total_distance_m / 20))  # 每20米一个点

        waypoints = []
        for i in range(num_points + 1):
            angle = (2 * math.pi * i) / num_points

            # 椭圆半径随角度变化
            r = radius + radius * 0.3 * math.sin(3 * angle)

            # 添加一些自然弯曲
            r += random.uniform(-5, 5)

            lat_offset = (r * math.cos(angle)) / (EARTH_RADIUS * math.pi / 180)
            lng_offset = (r * math.sin(angle)) / (
                EARTH_RADIUS * math.cos(center_lat * math.pi / 180) * math.pi / 180
            )

            waypoints.append(Waypoint(center_lat + lat_offset, center_lng + lng_offset))

        # 闭合路线（确保终点接近起点）
        waypoints.append(waypoints[0])

        return Route(waypoints, name=name)


# ─── 工具函数 ────────────────────────────────────────────


def haversine_distance(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> float:
    """
    使用 Haversine 公式计算两点间距离（米）
    """
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS * c


def _point_at_bearing(
    lat: float, lng: float, bearing_deg: float, distance_m: float
) -> tuple[float, float]:
    """
    从起点沿方位角移动指定距离后的坐标

    Args:
        lat, lng: 起点坐标
        bearing_deg: 方位角（度，0=北，90=东）
        distance_m: 距离（米）

    Returns:
        (纬度, 经度)
    """
    bearing = math.radians(bearing_deg)
    lat_rad = math.radians(lat)
    angular_dist = distance_m / EARTH_RADIUS

    new_lat = math.asin(
        math.sin(lat_rad) * math.cos(angular_dist)
        + math.cos(lat_rad) * math.sin(angular_dist) * math.cos(bearing)
    )
    new_lng = math.radians(lng) + math.atan2(
        math.sin(bearing) * math.sin(angular_dist) * math.cos(lat_rad),
        math.cos(angular_dist) - math.sin(lat_rad) * math.sin(new_lat),
    )

    return math.degrees(new_lat), math.degrees(new_lng)


def _load_json_route(path: Path) -> Route:
    """从 JSON 文件加载路线"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Route.from_dict(data)


def _load_gpx_route(path: Path) -> Route:
    """从 GPX 文件加载路线（简易解析器）"""
    import xml.etree.ElementTree as ET

    tree = ET.parse(path)
    root = tree.getroot()

    # 解析命名空间
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}

    waypoints = []
    for trkpt in root.findall(".//gpx:trkpt", ns):
        lat = float(trkpt.get("lat", 0))
        lng = float(trkpt.get("lon", 0))
        ele_elem = trkpt.find("gpx:ele", ns)
        alt = float(ele_elem.text) if ele_elem is not None and ele_elem.text else 0.0
        waypoints.append(Waypoint(lat, lng, alt))

    name_elem = root.find(".//gpx:name", ns)
    name = name_elem.text if name_elem is not None and name_elem.text else "GPX 路线"

    return Route(waypoints, name=name)


def _save_gpx_route(route: Route, filepath: str) -> bool:
    """导出路线为 GPX 格式"""
    import xml.etree.ElementTree as ET
    from xml.dom import minidom

    gpx = ET.Element("gpx", {
        "version": "1.1",
        "creator": "CampusRunner",
        "xmlns": "http://www.topografix.com/GPX/1/1",
    })

    # 元数据
    metadata = ET.SubElement(gpx, "metadata")
    ET.SubElement(metadata, "name").text = route.name

    # 路线
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = route.name
    trkseg = ET.SubElement(trk, "trkseg")

    for wp in route.waypoints:
        trkpt = ET.SubElement(trkseg, "trkpt", {
            "lat": f"{wp.lat:.8f}",
            "lon": f"{wp.lng:.8f}",
        })
        if wp.alt != 0:
            ET.SubElement(trkpt, "ele").text = f"{wp.alt:.1f}"

    # 格式化输出
    xml_str = minidom.parseString(ET.tostring(gpx, "utf-8")).toprettyxml(indent="  ")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(xml_str)

    logger.info(f"GPX 路线已导出: {filepath} ({route.point_count} 点)")
    return True
