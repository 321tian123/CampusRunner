"""
真实 GPS 运动引擎

融合多个开源项目的核心技术：
- Ornstein-Uhlenbeck 过程 (LocationSpoofer) — 真实 GPS 漂移
- 多 Provider 同时注入 (Modify_Positioning) — GPS + Network + Passive
- 起步爆发注入 (Modify_Positioning) — 快速建立 GPS 定位
- 平滑速度过渡 — 模拟真实跑步加速/减速

参考项目:
- github.com/HuangZhuoRui/LocationSpoofer (OU drift + NMEA sim)
- github.com/AuroraNest/Modify_Positioning (multi-provider + burst)
- github.com/Lerist/FakeLocation (speed presets)

纯数学实现，零外部依赖。
"""

import math
import random
import time
import logging
from typing import Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# Ornstein-Uhlenbeck 过程 — 真实 GPS 漂移模拟
# ══════════════════════════════════════════════════════════


class OrnsteinUhlenbeckDrift:
    """
    Ornstein-Uhlenbeck 随机过程

    模拟真实 GPS 定位中的自然漂移。
    相比纯高斯噪声，OU 过程产生的漂移具有「均值回归」特性 —
    位置不会无限远离真实值，而是在真实值周围做有记忆的随机游走。

    公式:
        dx = -theta * (x - mu) * dt + sigma * dW

    其中:
        theta = 回归速率 (越大回归越快)
        mu = 均值 (漂移中心)
        sigma = 波动率
        dW = 维纳过程增量

    参考: LocationSpoofer 项目的 anti-detection 模块
    """

    def __init__(
        self,
        theta: float = 0.5,      # 回归速率: 0.1~2.0
        sigma: float = 1.0,      # 波动率: 0.1~5.0 米/秒^0.5
        dt: float = 1.0,         # 时间步长（秒）
        max_drift_m: float = 15.0,  # 最大漂移距离（米）
    ):
        self.theta = theta
        self.sigma = sigma
        self.dt = dt
        self.max_drift = max_drift_m

        # 两个独立维度（纬度和经度方向各一个 OU 过程）
        self._x_lat = 0.0
        self._x_lng = 0.0

    def step(self) -> tuple[float, float]:
        """
        生成一步漂移

        Returns:
            (lat_offset_m, lng_offset_m) 偏移量（米）
        """
        # 维纳增量 ~ N(0, dt)
        dw_lat = random.gauss(0, math.sqrt(self.dt))
        dw_lng = random.gauss(0, math.sqrt(self.dt))

        # OU 更新
        dx_lat = -self.theta * self._x_lat * self.dt + self.sigma * dw_lat
        dx_lng = -self.theta * self._x_lng * self.dt + self.sigma * dw_lng

        self._x_lat += dx_lat
        self._x_lng += dx_lng

        # 钳制
        self._x_lat = max(-self.max_drift, min(self.max_drift, self._x_lat))
        self._x_lng = max(-self.max_drift, min(self.max_drift, self._x_lng))

        return self._x_lat, self._x_lng

    def reset(self):
        """重置漂移状态"""
        self._x_lat = 0.0
        self._x_lng = 0.0


# ══════════════════════════════════════════════════════════
# 平滑速度过渡
# ══════════════════════════════════════════════════════════


class SmoothSpeedController:
    """
    平滑速度控制器

    模拟真实跑步中的加速和减速 — 不会瞬间从 0 跳到目标速度。
    使用指数平滑: v_new = v_old + alpha * (v_target - v_old)

    参考: FakeLocation by Lerist 的速度分级 + 自定义速度
    """

    # 跑步速度参考 (km/h)
    SPEED_WALK = 5.0       # 步行
    SPEED_JOG = 8.0        # 慢跑
    SPEED_RUN = 12.0       # 跑步
    SPEED_SPRINT = 18.0    # 冲刺

    def __init__(
        self,
        target_speed_kmh: float = 10.0,
        alpha: float = 0.3,     # 平滑系数 (0~1，越小越平滑)
    ):
        self.target = target_speed_kmh
        self.current = 0.0      # 当前实际速度
        self.alpha = alpha
        self._start_time = time.monotonic()

    def set_target(self, kmh: float):
        """设置目标速度"""
        self.target = max(1.0, min(25.0, kmh))

    def update(self) -> float:
        """
        更新并返回当前平滑速度

        Returns:
            当前速度 (km/h)
        """
        # 指数平滑过渡
        self.current += self.alpha * (self.target - self.current)

        # 起步阶段：前5秒渐进加速
        elapsed = time.monotonic() - self._start_time
        if elapsed < 5.0:
            warmup_ratio = elapsed / 5.0
            # 缓入曲线 cubic ease-in
            warmup_ratio = warmup_ratio ** 3
            # 限制最大速度为 warmup_ratio * target
            max_allowed = self.target * warmup_ratio + 1.0  # +1 确保至少有一点速度
            self.current = min(self.current, max_allowed)

        return self.current

    def reset(self):
        """重置（开始新一轮跑步）"""
        self.current = 0.0
        self._start_time = time.monotonic()


# ══════════════════════════════════════════════════════════
# 多 Provider 注入策略
# ══════════════════════════════════════════════════════════


@dataclass
class GPSReading:
    """单次 GPS 读数"""
    lat: float
    lng: float
    alt: float = 0.0
    accuracy: float = 3.0      # 精度（米）
    speed: float = 0.0          # 速度（m/s）
    bearing: float = 0.0        # 方位角（度）
    satellites: int = 10        # 可见卫星数
    timestamp: float = field(default_factory=time.time)


class GPSInjectStrategy:
    """
    GPS 注入策略封装

    综合多 Provider 注入思路 (Modify_Positioning):
    - GPS provider: 精确定位
    - Network provider: 辅助定位（WiFi/基站模拟）
    - Passive provider: 被动接收（所有 App 都能收到）

    在 LDPlayer 环境下，ldconsole locate 会自动处理多 provider。
    本模块提供策略层的抽象和验证。
    """

    def __init__(self, inject_func: Callable[[float, float, float], bool]):
        """
        Args:
            inject_func: 底层注入函数 (lat, lng, alt) -> bool
        """
        self._inject = inject_func
        self._injection_count = 0
        self._last_inject_time = 0.0
        self._error_count = 0

    def burst_inject(
        self,
        lat: float,
        lng: float,
        burst_count: int = 10,
        interval_ms: float = 80.0,
    ) -> bool:
        """
        起步爆发注入

        开始跑步时快速连续注入多个样本，快速建立 GPS 定位。
        模拟 GPS 芯片冷启动后的快速卫星锁定过程。

        参考: Modify_Positioning 的 burst injection (30 samples @ 120ms)

        Args:
            burst_count: 爆发样本数
            interval_ms: 样本间隔（毫秒）

        Returns:
            全部成功的标志
        """
        logger.debug(f"GPS burst: {burst_count} samples @ {interval_ms}ms")

        success_all = True
        for i in range(burst_count):
            # 微小抖动使样本不完全相同
            jitter_lat = random.uniform(-0.000001, 0.000001)
            jitter_lng = random.uniform(-0.000001, 0.000001)

            ok = self._inject(lat + jitter_lat, lng + jitter_lng, 0.0)
            if not ok:
                success_all = False

            if i < burst_count - 1:
                time.sleep(interval_ms / 1000.0)

        self._injection_count += burst_count
        self._last_inject_time = time.time()
        return success_all

    def steady_inject(
        self,
        lat: float,
        lng: float,
        drift_lat_m: float = 0.0,
        drift_lng_m: float = 0.0,
    ) -> bool:
        """
        稳态注入（每次迭代调用）

        注入 GPS 坐标 + OU 漂移偏移。
        """
        # 米偏移 → 经纬度偏移
        # 1°纬度 ≈ 111320m, 1°经度 ≈ 111320 * cos(lat)
        lat_offset = drift_lat_m / 111320.0
        lng_offset = drift_lng_m / (111320.0 * math.cos(math.radians(lat)))

        final_lat = lat + lat_offset
        final_lng = lng + lng_offset

        ok = self._inject(final_lat, final_lng, 0.0)

        self._injection_count += 1
        self._last_inject_time = time.time()
        if not ok:
            self._error_count += 1

        return ok

    @property
    def stats(self) -> dict:
        """注入统计"""
        return {
            "total_injections": self._injection_count,
            "errors": self._error_count,
            "error_rate": (self._error_count / self._injection_count * 100)
            if self._injection_count > 0 else 0,
            "last_inject_sec_ago": time.time() - self._last_inject_time
            if self._last_inject_time > 0 else float("inf"),
        }


# ══════════════════════════════════════════════════════════
# NMEA 卫星仿真数据生成
# ══════════════════════════════════════════════════════════


class NMEASimulator:
    """
    NMEA-0183 卫星数据仿真

    生成逼真的 GNSS 卫星星座参数，用于躲避基于卫星信号的检测。

    格式参考: $GPGGA, $GPRMC, $GPGSV

    参考: LocationSpoofer NMEA sentence generation
    """

    # 典型 GPS 卫星 PRN 编号
    SATELLITES = list(range(1, 33))

    @staticmethod
    def generate_gsv_satellites(count: int = 10) -> list[dict]:
        """
        生成 GSV 卫星数据

        Returns:
            [{prn, elevation, azimuth, snr}, ...]
        """
        sats = random.sample(NMEASimulator.SATELLITES, min(count, 32))

        result = []
        for prn in sats:
            elevation = random.randint(5, 90)    # 仰角
            azimuth = random.randint(0, 359)     # 方位角
            snr = random.randint(20, 50)         # 信噪比 dB-Hz

            # 高仰角卫星通常有更好的信噪比
            if elevation > 45:
                snr = random.randint(35, 50)
            elif elevation < 15:
                snr = random.randint(20, 35)

            result.append({
                "prn": prn,
                "elevation": elevation,
                "azimuth": azimuth,
                "snr": snr,
            })

        return result

    @staticmethod
    def generate_satellite_metadata() -> dict:
        """生成卫星元数据"""
        return {
            "satellites_visible": random.randint(8, 16),
            "satellites_used": random.randint(6, 12),
            "hdop": round(random.uniform(0.8, 3.0), 1),  # 水平精度因子
            "vdop": round(random.uniform(1.0, 4.0), 1),  # 垂直精度因子
            "fix_quality": random.choice([1, 2]),          # 1=GPS, 2=DGPS
        }


# ══════════════════════════════════════════════════════════
# 步频模拟
# ══════════════════════════════════════════════════════════


class StepCadenceSimulator:
    """
    步频模拟器

    生成逼真的跑步步频数据。
    正常跑步步频: 150-180 步/分钟
    与速度正相关: cadence ≈ 120 + speed_kmh * 5

    参考: 运动科学文献 + LocationSpoofer 步频模拟
    """

    @staticmethod
    def cadence_for_speed(speed_kmh: float) -> float:
        """根据速度计算步频"""
        if speed_kmh < 1:
            return 0
        # 基础步频 120 + 速度贡献
        base = 120.0
        speed_factor = speed_kmh * 5.0
        # 加入随机波动
        noise = random.gauss(0, 3)
        return base + speed_factor + noise

    @staticmethod
    def step_length_for_speed(speed_kmh: float) -> float:
        """根据速度计算步幅（米）"""
        if speed_kmh < 1:
            return 0
        speed_ms = speed_kmh / 3.6
        cadence = StepCadenceSimulator.cadence_for_speed(speed_kmh)
        return speed_ms * 60 / cadence if cadence > 0 else 0.8
