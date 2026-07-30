"""
高德地图 API 路线规划模块

通过高德 Web 服务 API 获取真实道路的步行/骑行路线，
将返回的 polyline 坐标串解析为 CampusRunner 的 Route 对象。

API 文档: https://lbs.amap.com/api/webservice/guide/api/direction

坐标体系: GCJ-02 (火星坐标)，与国内主流 App 一致。
免费额度: 5000 次/日，足够个人使用。
"""

import json
import logging
import urllib.request
import urllib.parse
from typing import Optional, NamedTuple

from .route_engine import Route, Waypoint

logger = logging.getLogger(__name__)

# 高德地图 API 基础 URL
AMAP_DIRECTION_WALKING_URL = "https://restapi.amap.com/v3/direction/walking"
AMAP_DIRECTION_CYCLING_URL = "https://restapi.amap.com/v3/direction/bicycling"
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"


class GeoPoint(NamedTuple):
    """地理坐标点 (注意: 高德API使用 lng,lat 顺序)"""
    lng: float
    lat: float


class AmapRoutePlanner:
    """高德地图路线规划器"""

    def __init__(self, api_key: str):
        """
        Args:
            api_key: 高德开放平台 Web 服务 API Key
                     申请地址: https://console.amap.com/dev/key/app
        """
        self.api_key = api_key

    # ─── 路线规划 ──────────────────────────────────────

    def plan_walking(
        self,
        origin: str,
        destination: str,
        alternative: bool = False,
    ) -> Optional[Route]:
        """
        步行路线规划

        Args:
            origin: 起点，格式 "lng,lat" 或地址文本
            destination: 终点，格式 "lng,lat" 或地址文本
            alternative: 是否返回备选路线（默认只返回最优路线）

        Returns:
            Route 对象，失败返回 None
        """
        return self._plan_route(
            AMAP_DIRECTION_WALKING_URL,
            origin,
            destination,
            route_type="步行",
            alternative=alternative,
        )

    def plan_cycling(
        self,
        origin: str,
        destination: str,
        alternative: bool = False,
    ) -> Optional[Route]:
        """
        骑行路线规划

        Args:
            origin: 起点，格式 "lng,lat" 或地址文本
            destination: 终点，格式 "lng,lat" 或地址文本
            alternative: 是否返回备选路线

        Returns:
            Route 对象，失败返回 None
        """
        return self._plan_route(
            AMAP_DIRECTION_CYCLING_URL,
            origin,
            destination,
            route_type="骑行",
            alternative=alternative,
        )

    def plan_campus_run(
        self,
        origin: str,
        destination: str,
    ) -> Optional[Route]:
        """
        校园跑路线规划（优先步行，步行路径更能反映校园内真实可跑路线）

        Args:
            origin: 起点
            destination: 终点

        Returns:
            Route 对象
        """
        route = self.plan_walking(origin, destination)
        if route is None:
            logger.info("步行路线获取失败，尝试骑行路线...")
            route = self.plan_cycling(origin, destination)
        return route

    def plan_loop_route(
        self,
        center: str,
        radius_m: int = 1000,
        waypoints: Optional[list[str]] = None,
    ) -> Optional[Route]:
        """
        规划环形校园跑路线

        策略: 在中心点周围选取若干途经点，串成环形路径。

        Args:
            center: 中心点坐标 "lng,lat" 或地址
            radius_m: 搜索半径（米），决定途经点的偏移距离
            waypoints: 自定义途经点列表 ["lng,lat", ...]，
                       不传则自动在中心周围生成4个方向点

        Returns:
            环形 Route 对象
        """
        # 解析中心坐标
        center_pt = self._resolve_coord(center)
        if center_pt is None:
            return None

        if waypoints is None:
            # 在中心周围生成 4 个方向的途经点
            # 1 度纬度 ≈ 111320m，1 度经度 ≈ 111320 * cos(lat)
            import math
            lat_shift = radius_m / 111320.0
            lng_shift = radius_m / (111320.0 * math.cos(math.radians(center_pt.lat)))

            waypoints = [
                f"{center_pt.lng + lng_shift},{center_pt.lat}",           # 东
                f"{center_pt.lng + lng_shift},{center_pt.lat - lat_shift}", # 东南
                f"{center_pt.lng},{center_pt.lat - lat_shift}",            # 南
                f"{center_pt.lng - lng_shift},{center_pt.lat - lat_shift}", # 西南
                f"{center_pt.lng - lng_shift},{center_pt.lat}",           # 西
                f"{center_pt.lng - lng_shift},{center_pt.lat + lat_shift}", # 西北
                f"{center_pt.lng},{center_pt.lat + lat_shift}",            # 北
            ]

        # 连接途经点：origin → wp1 → wp2 → ... → origin（闭合环）
        logger.info(f"规划环形路线: {len(waypoints)} 个途经点")

        all_waypoints: list[Waypoint] = []
        current = origin if self._is_coord_str(origin) else f"{center_pt.lng},{center_pt.lat}"

        # 先添加起点
        start_pt = self._resolve_coord(current)
        if start_pt:
            all_waypoints.append(Waypoint(start_pt.lat, start_pt.lng))

        for wp in waypoints:
            segment = self.plan_walking(current, wp)
            if segment:
                # 添加除了第一个点之外的所有点（避免重复）
                pts = segment.waypoints
                if all_waypoints and pts:
                    all_waypoints.extend(pts[1:] if len(pts) > 1 else pts)
                else:
                    all_waypoints.extend(pts)
                current = wp
            else:
                # 这段路线获取失败，用直线连接
                wp_pt = self._resolve_coord(wp)
                if wp_pt and all_waypoints:
                    all_waypoints.append(Waypoint(wp_pt.lat, wp_pt.lng))
                    current = wp

        # 闭合回起点
        if len(all_waypoints) >= 2:
            first = all_waypoints[0]
            last = all_waypoints[-1]
            if (abs(first.lat - last.lat) > 0.0001 or
                    abs(first.lng - last.lng) > 0.0001):
                all_waypoints.append(Waypoint(first.lat, first.lng))

        if len(all_waypoints) < 3:
            logger.error("环形路线点数不足")
            return None

        return Route(
            waypoints=all_waypoints,
            name=f"校园环形路线 ({len(waypoints)}途经点)",
        )

    # ─── 地理编码 ───────────────────────────────────────

    def geocode(self, address: str) -> Optional[GeoPoint]:
        """
        地址 → 坐标（地理编码）

        Args:
            address: 地址文本，如 "北京大学"

        Returns:
            GeoPoint 或 None
        """
        params = {
            "key": self.api_key,
            "address": address,
            "city": "",  # 全国搜索
        }
        data = self._api_get(AMAP_GEOCODE_URL, params)
        if data is None:
            return None

        try:
            geocodes = data.get("geocodes", [])
            if not geocodes:
                logger.warning(f"地理编码无结果: {address}")
                return None
            location = geocodes[0].get("location", "")
            lng_str, lat_str = location.split(",")
            return GeoPoint(float(lng_str), float(lat_str))
        except Exception as e:
            logger.error(f"解析地理编码结果失败: {e}")
            return None

    def reverse_geocode(self, lng: float, lat: float) -> Optional[str]:
        """
        坐标 → 地址（逆地理编码）

        Returns:
            格式化地址字符串，失败返回 None
        """
        params = {
            "key": self.api_key,
            "location": f"{lng},{lat}",
            "extensions": "base",
        }
        data = self._api_get(AMAP_REGEO_URL, params)
        if data is None:
            return None

        try:
            regeocode = data.get("regeocode", {})
            return regeocode.get("formatted_address", "")
        except Exception:
            return None

    # ─── 内部方法 ───────────────────────────────────────

    def _plan_route(
        self,
        url: str,
        origin: str,
        destination: str,
        route_type: str = "步行",
        alternative: bool = False,
    ) -> Optional[Route]:
        """通用的路线获取逻辑"""
        params = {
            "key": self.api_key,
            "origin": origin,
            "destination": destination,
            "extensions": "base",  # base=返回概略信息, all=返回详细信息
        }

        logger.info(f"获取{route_type}路线: {origin} → {destination}")

        data = self._api_get(url, params)
        if data is None:
            return None

        try:
            if data.get("status") != "1":
                logger.error(f"高德API返回错误: {data.get('info', '未知错误')}")
                return None

            route_info = data.get("route", {})
            paths = route_info.get("paths", [])

            if not paths:
                logger.warning(f"未找到{route_type}路线")
                return None

            path = paths[0]  # 取最优路线
            distance_m = int(path.get("distance", 0))
            duration_sec = int(path.get("duration", 0))

            steps = path.get("steps", [])
            all_waypoints: list[Waypoint] = []

            for step in steps:
                polyline = step.get("polyline", "")
                waypoints = self._parse_polyline(polyline)
                all_waypoints.extend(waypoints)

            if not all_waypoints:
                logger.error("路线坐标串为空")
                return None

            name = f"{route_type}路线 ({distance_m}m, {duration_sec//60}分钟)"
            logger.info(f"获取成功: {name}, {len(all_waypoints)} 个路径点")

            return Route(waypoints=all_waypoints, name=name)

        except Exception as e:
            logger.error(f"解析路线数据失败: {e}")
            return None

    @staticmethod
    def _parse_polyline(polyline_str: str) -> list[Waypoint]:
        """
        解析高德 polyline 坐标串

        格式: "lng1,lat1;lng2,lat2;lng3,lat3;..."

        Returns:
            Waypoint 列表
        """
        waypoints = []
        if not polyline_str:
            return waypoints

        for coord_str in polyline_str.split(";"):
            coord_str = coord_str.strip()
            if not coord_str:
                continue
            try:
                parts = coord_str.split(",")
                if len(parts) >= 2:
                    lng = float(parts[0])
                    lat = float(parts[1])
                    waypoints.append(Waypoint(lat, lng))
            except (ValueError, IndexError):
                logger.debug(f"跳过无效坐标: {coord_str}")

        return waypoints

    @staticmethod
    def _api_get(url: str, params: dict) -> Optional[dict]:
        """发送 GET 请求并返回 JSON"""
        query_string = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_string}"

        try:
            req = urllib.request.Request(full_url)
            req.add_header("User-Agent", "CampusRunner/0.2")
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.URLError as e:
            logger.error(f"网络请求失败: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"API 请求异常: {e}")
            return None

    def _resolve_coord(self, coord_or_address: str) -> Optional[GeoPoint]:
        """解析坐标或地址 → GeoPoint"""
        if self._is_coord_str(coord_or_address):
            try:
                parts = coord_or_address.split(",")
                return GeoPoint(float(parts[0]), float(parts[1]))
            except (ValueError, IndexError):
                pass
        return self.geocode(coord_or_address)

    @staticmethod
    def _is_coord_str(text: str) -> bool:
        """判断字符串是否为 "lng,lat" 格式的坐标"""
        parts = text.split(",")
        if len(parts) == 2:
            try:
                float(parts[0])
                float(parts[1])
                return True
            except ValueError:
                pass
        return False
