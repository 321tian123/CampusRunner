"""
配速计算器 - 距离/配速/时间 三者联动

三参数联动规则:
- distance_km = time_min / pace_min_per_km
- pace_min_per_km = time_min / distance_km
- time_min = distance_km * pace_min_per_km
- speed_kmh = 60 / pace_min_per_km

修改任意一个参数，保持被修改参数 + 最近被修改的另一个参数不变，
重新计算第三个参数。

用于 GUI 中三个输入框的实时联动更新。
"""

import logging
from typing import Optional, Callable
from enum import Enum, auto

logger = logging.getLogger(__name__)


class ParamId(Enum):
    """参数标识"""
    DISTANCE = auto()   # 距离 (km)
    PACE = auto()       # 配速 (min/km)
    TIME = auto()       # 时间 (min)


class PaceCalculator:
    """
    配速联动计算器

    维护三个核心参数: 距离(km)、配速(min/km)、时间(min)
    以及派生参数: 速度(km/h)

    联动规则: 用户修改哪个参数，该参数 + 前一次被修改的参数保持不变，
              自动计算剩下那个参数。
    """

    def __init__(
        self,
        distance_km: float = 5.0,
        pace_min_per_km: float = 6.0,
    ):
        """
        Args:
            distance_km: 初始距离（公里）
            pace_min_per_km: 初始配速（分钟/公里）
        """
        self._distance_km = max(0.01, distance_km)
        self._pace_min_per_km = max(0.5, pace_min_per_km)
        self._time_min = self._distance_km * self._pace_min_per_km
        self._speed_kmh = 60.0 / self._pace_min_per_km

        # 追踪修改历史: [最近修改, 次近修改]
        self._last_two: list[ParamId] = [ParamId.DISTANCE, ParamId.PACE]

        # 回调: (distance_km, pace_str, time_min, speed_kmh) -> None
        self._on_change_callbacks: list[Callable] = []

    # ─── 属性 ──────────────────────────────────────────

    @property
    def distance_km(self) -> float:
        return self._distance_km

    @property
    def pace_min_per_km(self) -> float:
        return self._pace_min_per_km

    @property
    def time_min(self) -> float:
        return self._time_min

    @property
    def speed_kmh(self) -> float:
        return self._speed_kmh

    @property
    def pace_str(self) -> str:
        """配速字符串: 5'30\" /km"""
        minutes = int(self._pace_min_per_km)
        seconds = int((self._pace_min_per_km - minutes) * 60)
        return f"{minutes}'{seconds:02d}\""

    @property
    def time_str(self) -> str:
        """时间字符串: HH:MM:SS"""
        total_sec = int(self._time_min * 60)
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @property
    def distance_str(self) -> str:
        """距离字符串: 5.00 km"""
        return f"{self._distance_km:.2f} km"

    @property
    def speed_str(self) -> str:
        """速度字符串: 10.0 km/h"""
        return f"{self._speed_kmh:.1f} km/h"

    # ─── 设置方法（联动核心） ──────────────────────────

    def set_distance(self, km: float) -> bool:
        """
        设置距离

        联动规则:
        - 如果上次修改的是配速 → 保持距离和配速，重新计算时间
        - 如果上次修改的是时间 → 保持距离和时间，重新计算配速
        - 如果这是首次修改 → 保持配速，重新计算时间

        Returns:
            是否更新成功
        """
        if km <= 0:
            return False

        self._distance_km = km
        self._mark_modified(ParamId.DISTANCE)
        self._recalc()
        self._notify()
        return True

    def set_pace(self, min_per_km: float) -> bool:
        """
        设置配速

        Returns:
            是否更新成功
        """
        if min_per_km <= 0:
            return False

        self._pace_min_per_km = min_per_km
        self._mark_modified(ParamId.PACE)
        self._recalc()
        self._notify()
        return True

    def set_time(self, minutes: float) -> bool:
        """
        设置时间

        Returns:
            是否更新成功
        """
        if minutes <= 0:
            return False

        self._time_min = minutes
        self._mark_modified(ParamId.TIME)
        self._recalc()
        self._notify()
        return True

    def set_speed(self, kmh: float) -> bool:
        """
        设置速度（间接设置配速）

        speed_kmh = 60 / pace_min_per_km
        """
        if kmh <= 0:
            return False
        return self.set_pace(60.0 / kmh)

    # ─── 批量设置（不触发联动） ────────────────────────

    def set_all(self, distance_km: float, pace_min_per_km: float):
        """批量设置所有参数，不触发联动（用于初始化）"""
        self._distance_km = max(0.01, distance_km)
        self._pace_min_per_km = max(0.5, pace_min_per_km)
        self._time_min = self._distance_km * self._pace_min_per_km
        self._speed_kmh = 60.0 / self._pace_min_per_km
        self._notify()

    # ─── 回调 ──────────────────────────────────────────

    def on_change(self, callback: Callable):
        """注册变化回调"""
        self._on_change_callbacks.append(callback)

    def _notify(self):
        """触发变化回调"""
        for cb in self._on_change_callbacks:
            try:
                cb(self._distance_km, self._pace_min_per_km,
                   self._time_min, self._speed_kmh)
            except Exception as e:
                logger.error(f"配速回调错误: {e}")

    # ─── 内部 ──────────────────────────────────────────

    def _mark_modified(self, param: ParamId):
        """更新修改历史"""
        if self._last_two and self._last_two[0] == param:
            return  # 连续修改同一个参数，不更新历史
        self._last_two = [param] + [p for p in self._last_two if p != param]
        self._last_two = self._last_two[:2]

    def _recalc(self):
        """
        根据修改历史和当前值重新计算第三个参数

        规则: 最近修改的参数（固定） + 次近修改的参数（固定） → 计算第三个
        """
        if len(self._last_two) < 2:
            return

        fixed_params = set(self._last_two[:2])

        if fixed_params == {ParamId.DISTANCE, ParamId.PACE}:
            # 距离 + 配速 → 时间
            self._time_min = self._distance_km * self._pace_min_per_km
            self._speed_kmh = 60.0 / self._pace_min_per_km

        elif fixed_params == {ParamId.DISTANCE, ParamId.TIME}:
            # 距离 + 时间 → 配速
            self._pace_min_per_km = self._time_min / self._distance_km
            self._speed_kmh = 60.0 / self._pace_min_per_km

        elif fixed_params == {ParamId.PACE, ParamId.TIME}:
            # 配速 + 时间 → 距离
            self._distance_km = self._time_min / self._pace_min_per_km
            self._speed_kmh = 60.0 / self._pace_min_per_km

    def __repr__(self) -> str:
        return (f"PaceCalc(dist={self._distance_km:.2f}km, "
                f"pace={self.pace_str}, time={self.time_str}, "
                f"speed={self._speed_kmh:.1f}km/h)")
