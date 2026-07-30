"""
模拟引擎 - GPS 跑步模拟主循环 v0.4

优化:
- Ornstein-Uhlenbeck 过程替代简单高斯抖动
- 平滑速度过渡 (缓起缓停)
- 起步爆发注入 (快速GPS定位)
- 步频/步幅实时计算

管理模拟状态机，在独立线程中按时间间隔更新 GPS 位置。
"""

import time
import random
import threading
import logging
from enum import Enum, auto
from typing import Optional, Callable

from .route_engine import Route, Waypoint
from .location_injector import LocationInjector
from .gps_engine import (
    OrnsteinUhlenbeckDrift,
    SmoothSpeedController,
    GPSInjectStrategy,
    StepCadenceSimulator,
    NMEASimulator,
)

logger = logging.getLogger(__name__)


class RunState(Enum):
    """模拟器运行状态"""
    IDLE = auto()       # 待命中
    RUNNING = auto()    # 正在运行
    PAUSED = auto()     # 已暂停
    FINISHED = auto()   # 已完成


class ProgressInfo:
    """进度信息（传递给 GUI 的数据结构）"""

    def __init__(self):
        self.state: RunState = RunState.IDLE
        self.distance_m: float = 0.0       # 已跑距离（米）
        self.total_m: float = 0.0          # 路线总距离（米）
        self.elapsed_sec: float = 0.0      # 已用时间（秒）
        self.current_speed_ms: float = 0.0 # 当前速度（米/秒）
        self.current_lat: float = 0.0      # 当前位置纬度
        self.current_lng: float = 0.0      # 当前位置经度
        self.laps: int = 0                 # 已完成圈数
        self.injector_name: str = ""       # 使用的注入器名称
        self.cadence: float = 0.0          # 步频（步/分钟）
        self.step_length: float = 0.0      # 步幅（米）
        self.gps_accuracy: float = 3.0     # GPS 精度（米）
        self.satellites: int = 10          # 可见卫星数

    @property
    def progress_pct(self) -> float:
        return (self.distance_m / self.total_m * 100) if self.total_m > 0 else 0.0

    @property
    def remaining_m(self) -> float:
        return max(0.0, self.total_m - self.distance_m)

    @property
    def pace_min_per_km(self) -> float:
        """配速（分钟/公里）"""
        if self.distance_m < 1.0 or self.elapsed_sec < 1:
            return 0.0
        return (self.elapsed_sec / 60) / (self.distance_m / 1000)


class Simulator:
    """
    GPS 跑步模拟引擎

    在独立线程中运行主循环：
    1. 根据速度和间隔计算移动距离
    2. 在路线上插值新位置
    3. 加入随机抖动模拟 GPS 噪声
    4. 通过注入器发送坐标到模拟器
    5. 触发 GUI 回调更新界面
    """

    def __init__(
        self,
        injector: LocationInjector,
        route: Optional[Route] = None,
        speed_kmh: float = 10.0,
        update_interval_ms: int = 1500,
        jitter_meters: float = 3.0,
        loop_mode: bool = False,
    ):
        """
        初始化模拟器

        Args:
            injector: GPS 位置注入器
            route: 跑步路线
            speed_kmh: 初始速度（km/h）
            update_interval_ms: 位置更新间隔（毫秒）
            jitter_meters: GPS 抖动幅度（米）
            loop_mode: 是否循环模式
        """
        self._injector = injector
        self._route: Optional[Route] = route
        self._speed_kmh = speed_kmh
        self._update_interval = update_interval_ms / 1000.0
        self._jitter_meters = jitter_meters
        self._loop_mode = loop_mode

        # GPS 引擎组件
        self._ou_drift = OrnsteinUhlenbeckDrift(
            theta=0.3, sigma=1.5, dt=update_interval_ms / 1000.0,
            max_drift_m=jitter_meters,
        )
        self._speed_ctrl = SmoothSpeedController(
            target_speed_kmh=speed_kmh, alpha=0.25,
        )
        self._gps_strategy: Optional[GPSInjectStrategy] = None

        # 状态
        self._state = RunState.IDLE
        self._distance_m = 0.0
        self._elapsed_sec = 0.0
        self._laps = 0
        self._current_position: Optional[Waypoint] = None

        # 线程控制
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # 回调
        self._on_progress: list[Callable[[ProgressInfo], None]] = []
        self._on_state_change: list[Callable[[RunState, RunState], None]] = []

    # ─── 属性 ────────────────────────────────────────────

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def route(self) -> Optional[Route]:
        return self._route

    @route.setter
    def route(self, value: Route):
        with self._lock:
            self._route = value
            self._distance_m = 0.0
            self._elapsed_sec = 0.0
            self._laps = 0

    @property
    def speed_kmh(self) -> float:
        return self._speed_kmh

    @speed_kmh.setter
    def speed_kmh(self, value: float):
        v = max(1.0, min(25.0, value))
        with self._lock:
            self._speed_kmh = v
        self._speed_ctrl.set_target(v)  # 平滑过渡到新速度

    @property
    def speed_ms(self) -> float:
        """速度（米/秒），反映平滑速度"""
        return self._speed_ctrl.current / 3.6

    # ─── 回调注册 ────────────────────────────────────────

    def on_progress(self, callback: Callable[[ProgressInfo], None]):
        """注册进度更新回调（在模拟线程中调用，GUI 需用 after() 或类似机制）"""
        self._on_progress.append(callback)

    def on_state_change(self, callback: Callable[[RunState, RunState], None]):
        """注册状态变化回调 (old_state, new_state)"""
        self._on_state_change.append(callback)

    def _notify_progress(self):
        """触发进度回调"""
        info = self._build_progress_info()
        for cb in self._on_progress:
            try:
                cb(info)
            except Exception as e:
                logger.error(f"进度回调错误: {e}")

    def _notify_state_change(self, old_state: RunState, new_state: RunState):
        """触发状态变化回调"""
        for cb in self._on_state_change:
            try:
                cb(old_state, new_state)
            except Exception as e:
                logger.error(f"状态回调错误: {e}")

    def _build_progress_info(self) -> ProgressInfo:
        """构建当前进度信息"""
        info = ProgressInfo()
        info.state = self._state
        info.distance_m = self._distance_m
        info.total_m = self._route.total_distance_m if self._route else 0.0
        info.elapsed_sec = self._elapsed_sec
        info.current_speed_ms = self.speed_ms
        info.laps = self._laps
        info.injector_name = self._injector.active_injector_name

        # 步频和步幅
        info.cadence = StepCadenceSimulator.cadence_for_speed(self._speed_ctrl.current)
        info.step_length = StepCadenceSimulator.step_length_for_speed(self._speed_ctrl.current)

        # GPS 精度（随时间略有波动）
        sat_data = NMEASimulator.generate_satellite_metadata()
        info.satellites = sat_data["satellites_used"]
        info.gps_accuracy = sat_data["hdop"] * 1.5

        if self._current_position:
            info.current_lat = self._current_position.lat
            info.current_lng = self._current_position.lng
        elif self._route and self._route.waypoints:
            info.current_lat = self._route.waypoints[0].lat
            info.current_lng = self._route.waypoints[0].lng

        return info

    # ─── 控制方法 ────────────────────────────────────────

    def start(self) -> bool:
        """
        开始模拟

        Returns:
            是否成功启动
        """
        if self._route is None:
            logger.error("没有设置路线!")
            return False

        if self._state == RunState.RUNNING:
            logger.warning("模拟已在运行中")
            return False

        with self._lock:
            if self._state == RunState.PAUSED:
                return self._do_resume()

            self._distance_m = 0.0
            self._elapsed_sec = 0.0
            self._laps = 0
            self._stop_event.clear()

            old_state = self._state
            self._state = RunState.RUNNING

        self._notify_state_change(old_state, RunState.RUNNING)

        # 初始化 GPS 注入策略
        self._gps_strategy = GPSInjectStrategy(
            inject_func=lambda lat, lng, alt: self._injector.set_location(lat, lng, alt)
        )
        self._ou_drift.reset()
        self._speed_ctrl.reset()
        self._speed_ctrl.set_target(self._speed_kmh)

        # 起步爆发注入 (快速建立 GPS 定位)
        start_pos = self._route.waypoints[0]
        self._current_position = start_pos
        logger.info("GPS burst injection start...")
        self._gps_strategy.burst_inject(start_pos.lat, start_pos.lng, burst_count=8, interval_ms=100)
        logger.info("GPS burst injection done")

        # 启动模拟线程
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="GPS-Simulator"
        )
        self._thread.start()

        logger.info(f"模拟已开始: 速度={self._speed_kmh}km/h, "
                     f"总距离≈{self._route.total_distance_m:.0f}m")
        return True

    def pause(self):
        """暂停模拟"""
        if self._state != RunState.RUNNING:
            return
        with self._lock:
            old_state = self._state
            self._state = RunState.PAUSED
        self._notify_state_change(old_state, RunState.PAUSED)
        logger.info("模拟已暂停")

    def resume(self) -> bool:
        """继续模拟"""
        if self._state != RunState.PAUSED:
            return False
        return self._do_resume()

    def _do_resume(self) -> bool:
        """内部：从暂停状态恢复"""
        with self._lock:
            old_state = self._state
            self._state = RunState.RUNNING
            self._stop_event.clear()

        self._notify_state_change(old_state, RunState.RUNNING)

        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="GPS-Simulator"
        )
        self._thread.start()
        logger.info("模拟已继续")
        return True

    def stop(self):
        """停止模拟"""
        if self._state in (RunState.IDLE, RunState.FINISHED):
            return

        old_state = self._state
        self._stop_event.set()

        # 等待线程结束
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        with self._lock:
            self._state = RunState.IDLE

        self._notify_state_change(old_state, RunState.IDLE)
        logger.info("模拟已停止")

    def toggle_pause(self):
        """切换暂停/继续"""
        if self._state == RunState.RUNNING:
            self.pause()
        elif self._state == RunState.PAUSED:
            self.resume()

    # ─── 主循环 ──────────────────────────────────────────

    def _run_loop(self):
        """
        模拟主循环（在独立线程中运行）

        每次迭代：
        1. 记录循环开始时间
        2. 计算行进距离（速度 × 间隔 + 随机抖动）
        3. 在路线上插值新位置
        4. 加入 GPS 位置噪声
        5. 发送坐标到模拟器
        6. 触发进度回调
        7. 休眠补偿（确保精确的更新间隔）
        """
        logger.debug("模拟线程已启动")

        while not self._stop_event.is_set():
            loop_start = time.monotonic()

            with self._lock:
                if self._state != RunState.RUNNING:
                    break

                speed_ms = self.speed_ms
                interval = self._update_interval
                jitter = self._jitter_meters
                current_route = self._route

            if current_route is None:
                break

            # 1. 平滑速度更新 + 微波动
            smooth_speed = self._speed_ctrl.update()
            speed_variation = random.gauss(1.0, 0.03)  # 3% 速度波动
            speed_variation = max(0.85, min(1.15, speed_variation))
            actual_speed_ms = (smooth_speed / 3.6) * speed_variation
            delta_distance = actual_speed_ms * interval

            # 2. 更新累积距离
            with self._lock:
                self._distance_m += delta_distance
                self._elapsed_sec += interval

            total = current_route.total_distance_m

            # 3. 检查是否完成
            if self._distance_m >= total:
                if self._loop_mode:
                    with self._lock:
                        self._distance_m = self._distance_m % total
                        self._laps += 1
                    logger.info(f"第 {self._laps} 圈完成，继续下一圈")
                else:
                    with self._lock:
                        self._distance_m = total
                        self._state = RunState.FINISHED

                    new_pos = current_route.get_position_at_distance(total)
                    self._current_position = new_pos
                    if self._gps_strategy:
                        self._gps_strategy.steady_inject(new_pos.lat, new_pos.lng)
                    else:
                        self._injector.set_location(new_pos.lat, new_pos.lng, new_pos.alt)

                    self._notify_progress()
                    self._notify_state_change(RunState.RUNNING, RunState.FINISHED)
                    logger.info("路线已完成!")
                    break

            # 4. 插值当前位置
            dist = self._distance_m
            new_pos = current_route.get_position_at_distance(dist)

            # 5. OU 漂移 (替代简单高斯抖动)
            drift_lat_m, drift_lng_m = self._ou_drift.step()
            self._current_position = new_pos

            # 6. 稳态注入 (含 OU 漂移)
            if self._gps_strategy:
                self._gps_strategy.steady_inject(
                    new_pos.lat, new_pos.lng,
                    drift_lat_m, drift_lng_m,
                )
            else:
                self._injector.set_location(new_pos.lat, new_pos.lng, new_pos.alt)

            # 7. 触发回调
            self._notify_progress()

            # 8. 休眠补偿（确保精确的更新间隔）
            elapsed = time.monotonic() - loop_start
            sleep_time = self._update_interval - elapsed
            if sleep_time > 0:
                # 使用短休眠 + 检查 stop_event，保持响应性
                while sleep_time > 0 and not self._stop_event.is_set():
                    chunk = min(0.1, sleep_time)
                    time.sleep(chunk)
                    sleep_time -= chunk

        logger.debug("模拟线程已结束")

    # ─── 查询方法 ────────────────────────────────────────

    def get_progress(self) -> ProgressInfo:
        """获取当前进度快照（线程安全）"""
        return self._build_progress_info()
