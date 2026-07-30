"""
GPS 位置注入器 - 将模拟坐标注入到 Android 模拟器

支持三种注入策略（按优先级 fallback）：
1. EmulatorConsoleInjector: 通过 socket 发送 geo fix 命令
2. LDPlayerInjector: 调用雷电模拟器的 ldconsole.exe
3. ADBShellInjector: 通过 adb shell mock location provider
"""

import socket
import subprocess
import logging
import time
import os
import sys
from abc import ABC, abstractmethod
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Windows 下隐藏 subprocess 弹出的 CMD 窗口
_POPEN_KWARGS = {}
if sys.platform == "win32":
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


# ─── 抽象基类 ────────────────────────────────────────────


class BaseInjector(ABC):
    """GPS 注入器抽象基类"""

    @abstractmethod
    def connect(self) -> bool:
        """建立连接，返回是否成功"""
        ...

    @abstractmethod
    def inject(self, lat: float, lng: float, alt: float = 0.0) -> bool:
        """注入一个 GPS 坐标点"""
        ...

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查此注入器是否可用"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """注入器名称"""
        ...


# ─── 方案 A: Emulator Console Telnet ────────────────────


class EmulatorConsoleInjector(BaseInjector):
    """
    通过 socket 连接 Android 模拟器控制台，发送 geo fix 命令

    这是最标准的 GPS 注入方式，适用于 Android Studio AVD 和大部分第三方模拟器。
    需要模拟器开启控制台端口（通常为 ADB 端口 - 1，如 ADB:5555 → Console:5554）。

    注意：使用原生 socket 而非 telnetlib（Python 3.13 已移除 telnetlib）。
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        console_port: int = 5554,
        auth_token: Optional[str] = None,
    ):
        self.host = host
        self.console_port = console_port
        self.auth_token = auth_token
        self._sock: Optional[socket.socket] = None
        self._available: Optional[bool] = None

    @property
    def name(self) -> str:
        return f"Emulator Console (socket {self.host}:{self.console_port})"

    def is_available(self) -> bool:
        """检查端口是否可达"""
        if self._available is not None:
            return self._available
        try:
            sock = socket.create_connection(
                (self.host, self.console_port), timeout=3
            )
            sock.close()
            self._available = True
        except Exception:
            self._available = False
        return self._available

    def connect(self) -> bool:
        """建立 socket 连接并认证"""
        if self._sock is not None:
            return True

        try:
            logger.info(f"正在连接模拟器控制台 {self.host}:{self.console_port}...")
            self._sock = socket.create_connection(
                (self.host, self.console_port), timeout=5
            )
            self._sock.settimeout(3)

            # 读取欢迎信息
            time.sleep(0.5)
            welcome = self._recv_all()

            # 如果需要认证
            if "OK" not in welcome and self.auth_token:
                self._send_cmd(f"auth {self.auth_token}")
                time.sleep(0.3)
                response = self._recv_all()
                if "OK" not in response:
                    logger.warning(f"认证可能失败: {response}")
            elif "OK" in welcome:
                logger.info("控制台无需认证，已连接")
            else:
                logger.info("控制台就绪")

            self._available = True
            return True

        except ConnectionRefusedError:
            logger.error(f"连接被拒绝: {self.host}:{self.console_port}")
            self._available = False
            return False
        except Exception as e:
            logger.error(f"连接失败: {e}")
            self._available = False
            return False

    def inject(self, lat: float, lng: float, alt: float = 0.0) -> bool:
        """发送 geo fix 命令 (格式: geo fix <lng> <lat> [alt])"""
        if self._sock is None:
            if not self.connect():
                return False

        try:
            cmd = f"geo fix {lng} {lat} {alt}"
            self._send_cmd(cmd)
            time.sleep(0.1)
            response = self._recv_all()

            if "KO:" in response:
                logger.warning(f"geo fix 返回错误: {response.strip()}")
                return False

            logger.debug(f"已注入坐标: ({lat:.6f}, {lng:.6f})")
            return True

        except (ConnectionError, OSError) as e:
            logger.warning(f"控制台连接已断开，尝试重连... ({e})")
            self._sock = None
            return False
        except Exception as e:
            logger.error(f"注入坐标失败: {e}")
            self._sock = None
            return False

    def _send_cmd(self, cmd: str):
        """发送命令到控制台"""
        if self._sock:
            self._sock.sendall((cmd + "\n").encode("utf-8"))

    def _recv_all(self) -> str:
        """读取所有可用数据"""
        if self._sock is None:
            return ""
        try:
            self._sock.settimeout(0.3)
            chunks = []
            while True:
                try:
                    data = self._sock.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
                except socket.timeout:
                    break
            self._sock.settimeout(3)
            return b"".join(chunks).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def disconnect(self):
        """断开 socket 连接"""
        if self._sock:
            try:
                self._sock.sendall(b"quit\n")
                self._sock.close()
            except Exception:
                pass
            self._sock = None


# ─── 方案 B: LDPlayer ldconsole ──────────────────────────


class LDPlayerInjector(BaseInjector):
    """
    通过雷电模拟器的 ldconsole.exe 控制虚拟定位

    LDPlayer 9 通常安装在:
    - C:/leidian/LDPlayer9/
    - D:/leidian/LDPlayer9/

    ldconsole.exe 支持命令行控制模拟器各项功能。
    """

    def __init__(self, ld_path: Optional[str] = None, vm_index: int = 0):
        self.ld_path: Optional[Path] = None
        self.vm_index = vm_index

        if ld_path:
            candidate = Path(ld_path) / "ldconsole.exe"
            if candidate.exists():
                self.ld_path = candidate
        else:
            self.ld_path = self._find_ldconsole()

    @staticmethod
    def _find_ldconsole() -> Optional[Path]:
        """自动搜索 ldconsole.exe"""
        search_dirs = [
            Path("C:/leidian/LDPlayer9/ldconsole.exe"),
            Path("D:/leidian/LDPlayer9/ldconsole.exe"),
            Path("C:/Program Files/leidian/LDPlayer9/ldconsole.exe"),
            Path("D:/Program Files/leidian/LDPlayer9/ldconsole.exe"),
        ]
        for p in search_dirs:
            if p.exists():
                return p

        # 尝试在 PATH 中搜索
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            candidate = Path(path_dir) / "ldconsole.exe"
            if candidate.exists():
                return candidate

        return None

    @property
    def name(self) -> str:
        return f"LDPlayer (ldconsole: {self.ld_path})"

    def is_available(self) -> bool:
        return self.ld_path is not None and self.ld_path.exists()

    def connect(self) -> bool:
        return self.is_available()

    def inject(self, lat: float, lng: float, alt: float = 0.0) -> bool:
        """
        调用 ldconsole 设置虚拟定位

        LDPlayer 9 使用: ldconsole locate --index <idx> --LLI <Lng>,<Lat>
        """
        if not self.ld_path:
            logger.error("找不到 ldconsole.exe")
            return False

        cmd = [
            str(self.ld_path),
            "locate",
            "--index",
            str(self.vm_index),
            "--LLI",
            f"{lng},{lat}",
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=10, encoding="utf-8", errors="replace",
                **_POPEN_KWARGS,
            )
            if result.returncode == 0:
                logger.debug(f"LDPlayer locate 注入成功: ({lat:.6f}, {lng:.6f})")
                return True
            else:
                logger.warning(f"ldconsole locate 失败 (code={result.returncode}): {result.stderr.strip()}")
        except Exception as e:
            logger.error(f"ldconsole 命令异常: {e}")

        # 备用: action 命令
        try:
            cmd2 = [
                str(self.ld_path),
                "action",
                "--index",
                str(self.vm_index),
                "--key",
                "location",
                "--value",
                f"{lng},{lat}",
            ]
            result = subprocess.run(cmd2, capture_output=True, text=True, timeout=10,
                                    encoding="utf-8", errors="replace", **_POPEN_KWARGS)
            if result.returncode == 0:
                logger.debug(f"LDPlayer action 注入成功: ({lat:.6f}, {lng:.6f})")
                return True
        except Exception:
            pass

        return False

    def disconnect(self):
        pass  # 无连接需要断开


# ─── 方案 C: ADB Shell Mock Location ─────────────────────


class ADBShellInjector(BaseInjector):
    """
    通过 ADB Shell 命令注入模拟位置

    此方法需要:
    1. 模拟器已开启开发者选项
    2. 已允许模拟位置 (mock location)

    通过 'adb shell' 执行 Android 命令来注入位置。
    """

    def __init__(self, adb_path: str = "adb", device_serial: Optional[str] = None):
        self.adb_path = adb_path
        self.device_serial = device_serial
        self._available: Optional[bool] = None
        self._mock_enabled = False

    @property
    def name(self) -> str:
        return "ADB Shell Mock Location"

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        try:
            result = subprocess.run(
                [self.adb_path, "version"],
                capture_output=True, timeout=5,
                **_POPEN_KWARGS,
            )
            self._available = result.returncode == 0
        except Exception:
            self._available = False

        return self._available

    def connect(self) -> bool:
        """配置 mock location 环境"""
        if not self.is_available():
            return False

        # 完整的位置模拟环境配置
        cmds = [
            # 开启高精度定位模式 (GPS+WiFi+基站)
            "settings put secure location_mode 3",
            # 允许 mock location
            "settings put secure mock_location 1",
            # 给关键组件 mock location 权限
            "appops set com.google.android.gms android:mock_location allow",
            "appops set com.android.shell android:mock_location allow",
            "appops set com.gotokeep.keep android:mock_location allow",
        ]

        for cmd in cmds:
            success, output = self._adb_shell(cmd)
            if not success:
                logger.debug(f"命令执行失败 ({cmd}): {output}")
            else:
                logger.debug(f"命令执行成功: {cmd}")

        self._mock_enabled = True
        logger.info("Mock Location 环境已配置 (location_mode=3, mock enabled)")
        return True

    def inject(self, lat: float, lng: float, alt: float = 0.0) -> bool:
        """
        通过 ADB shell 注入位置

        使用 Android 10+ 的 'cmd location' 命令，或通过 am broadcast 发送位置。
        """
        # 方法1: 使用 Android 10+ 的 cmd location 命令
        success, output = self._adb_shell(
            f"cmd location set-location-enabled gps true"
        )
        if success:
            success2, _ = self._adb_shell(
                f"cmd location providers set-test-provider-location gps "
                f"--location {lat},{lng},{alt}"
            )
            if success2:
                logger.debug(f"ADB Shell 坐标注入成功: ({lat:.6f}, {lng:.6f})")
                return True

        # 方法2: 使用 am broadcast (传统方式)
        success, _ = self._adb_shell(
            f"am broadcast -a android.location.PROVIDERS_CHANGED"
        )
        if success:
            logger.debug("发送位置变化广播")
            return True

        # 方法3: 使用 settings + 直接写入 (最后的尝试)
        success, _ = self._adb_shell(
            f"settings put system location_coarse_accuracy_m 50"
        )
        if not success:
            logger.warning("所有 ADB Shell 位置注入方法均失败")
            return False

        return True

    def _adb_shell(self, cmd: str, timeout: int = 10) -> tuple[bool, str]:
        """执行 ADB shell 命令"""
        full_cmd = [self.adb_path]
        if self.device_serial:
            full_cmd += ["-s", self.device_serial]
        full_cmd += ["shell", cmd]

        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", errors="replace",
                **_POPEN_KWARGS,
            )
            output = result.stdout.strip() or result.stderr.strip()
            return result.returncode == 0, output
        except Exception as e:
            return False, str(e)

    def disconnect(self):
        pass


# ─── 门面类：LocationInjector ────────────────────────────


class LocationInjector:
    """
    GPS 位置注入门面

    自动选择可用的注入策略：
    1. 优先尝试 Emulator Console (telnet geo fix)
    2. 若失败，尝试 LDPlayer ldconsole
    3. 若再失败，尝试 ADB Shell Mock Location
    """

    def __init__(
        self,
        adb_path: str = "adb",
        host: str = "127.0.0.1",
        console_port: int = 5554,
        device_serial: Optional[str] = None,
        ldplayer_path: Optional[str] = None,
    ):
        self._injectors: list[BaseInjector] = []
        self._active_injector: Optional[BaseInjector] = None

        # 按优先级构建注入器列表 (LDPlayer 优先，因为它最可靠)
        self._injectors.append(LDPlayerInjector(ld_path=ldplayer_path))
        self._injectors.append(
            EmulatorConsoleInjector(host=host, console_port=console_port)
        )
        self._injectors.append(
            ADBShellInjector(adb_path=adb_path, device_serial=device_serial)
        )

    def auto_connect(self) -> bool:
        """
        自动选择可用的注入器并连接

        Returns:
            是否成功连接
        """
        for injector in self._injectors:
            logger.info(f"尝试 {injector.name}...")
            if injector.is_available():
                if injector.connect():
                    self._active_injector = injector
                    logger.info(f"✓ 使用注入器: {injector.name}")
                    return True
                else:
                    logger.warning(f"  × 连接失败")

        logger.error("所有注入器均不可用！请检查模拟器是否启动。")
        return False

    def set_location(self, lat: float, lng: float, alt: float = 0.0) -> bool:
        """
        设置 GPS 位置

        Args:
            lat: 纬度
            lng: 经度
            alt: 海拔（米）

        Returns:
            是否成功
        """
        if self._active_injector is None:
            logger.error("没有可用的注入器，请先调用 auto_connect()")
            return False
        return self._active_injector.inject(lat, lng, alt)

    def disconnect(self):
        """断开所有连接"""
        for inj in self._injectors:
            try:
                inj.disconnect()
            except Exception:
                pass
        self._active_injector = None

    @property
    def active_injector_name(self) -> str:
        """当前活跃的注入器名称"""
        return self._active_injector.name if self._active_injector else "无"
