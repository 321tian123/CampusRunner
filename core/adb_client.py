"""
ADB 客户端 - 管理与 Android 模拟器的 ADB 连接

支持连接雷电模拟器9 及其他 Android 模拟器。
"""

import subprocess
import sys
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_POPEN_KWARGS = {}
if sys.platform == "win32":
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


class ADBClient:
    """ADB 连接管理器，封装 adb 命令行操作"""

    def __init__(self, adb_path: str = "adb", device_addr: str = "127.0.0.1:5555"):
        """
        初始化 ADB 客户端

        Args:
            adb_path: adb.exe 的路径
            device_addr: 模拟器地址 (默认 127.0.0.1:5555)
        """
        self.adb_path = adb_path
        self.device_addr = device_addr
        self._connected = False
        self._device_serial: Optional[str] = None

    def execute(self, *args: str, timeout: int = 10) -> tuple[bool, str]:
        """
        执行 ADB 命令

        Args:
            *args: ADB 命令参数
            timeout: 超时秒数

        Returns:
            (成功标志, 输出文本)
        """
        cmd = [self.adb_path] + list(args)
        logger.debug(f"执行命令: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", errors="replace",
                **_POPEN_KWARGS,
            )
            output = result.stdout.strip() or result.stderr.strip()
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "命令执行超时"
        except FileNotFoundError:
            return False, f"找不到 ADB 程序: {self.adb_path}"
        except Exception as e:
            return False, f"执行错误: {e}"

    def connect(self) -> bool:
        """
        连接到模拟器

        Returns:
            连接是否成功
        """
        logger.info(f"正在连接模拟器: {self.device_addr}")

        # 先检查是否已经连接
        success, output = self.execute("devices")
        if success and self.device_addr in output and "\tdevice" in output:
            self._connected = True
            self._device_serial = self.device_addr
            logger.info("模拟器已连接")
            return True

        # 尝试连接
        success, output = self.execute("connect", self.device_addr, timeout=15)
        if success and ("connected" in output.lower() or "already connected" in output.lower()):
            self._connected = True
            self._device_serial = self.device_addr
            logger.info(f"连接成功: {output}")
            return True
        else:
            self._connected = False
            logger.error(f"连接失败: {output}")
            return False

    def disconnect(self) -> bool:
        """断开模拟器连接"""
        if self._connected:
            success, _ = self.execute("disconnect", self.device_addr)
            self._connected = False
            self._device_serial = None
            return success
        return True

    def is_connected(self) -> bool:
        """检查连接状态"""
        if not self._connected:
            return False
        success, output = self.execute("devices")
        return success and self.device_addr in output and "\tdevice" in output

    def get_devices(self) -> list[str]:
        """
        获取所有已连接的设备列表

        Returns:
            设备序列号列表
        """
        success, output = self.execute("devices")
        if not success:
            return []

        devices = []
        for line in output.split("\n")[1:]:  # 跳过第一行 "List of devices attached"
            line = line.strip()
            if line and "\tdevice" in line:
                serial = line.split("\t")[0]
                devices.append(serial)
        return devices

    def shell(self, command: str, timeout: int = 10) -> tuple[bool, str]:
        """
        在设备上执行 shell 命令

        Args:
            command: shell 命令
            timeout: 超时秒数

        Returns:
            (成功标志, 输出文本)
        """
        return self.execute("shell", command, timeout=timeout)

    def get_android_version(self) -> Optional[str]:
        """获取 Android 版本"""
        success, output = self.shell("getprop ro.build.version.release")
        return output.strip() if success else None

    def get_device_model(self) -> Optional[str]:
        """获取设备型号"""
        success, output = self.shell("getprop ro.product.model")
        return output.strip() if success else None

    @staticmethod
    def find_adb() -> Optional[str]:
        """
        尝试在系统中查找 ADB 可执行文件

        Returns:
            ADB 路径，找不到返回 None
        """
        import os

        # 常见路径
        search_paths = [
            "adb",  # PATH 中
            "adb.exe",
            "D:/op/adb.exe",
            "C:/leidian/LDPlayer9/adb.exe",
            "D:/leidian/LDPlayer9/adb.exe",
            os.path.expandvars("%LOCALAPPDATA%/Android/Sdk/platform-tools/adb.exe"),
            os.path.expandvars("%ANDROID_HOME%/platform-tools/adb.exe"),
        ]

        for path in search_paths:
            try:
                result = subprocess.run(
                    [path, "version"], capture_output=True,
                    text=True, timeout=5,
                    **_POPEN_KWARGS,
                )
                if result.returncode == 0 and "Android Debug Bridge" in result.stdout:
                    return path
            except Exception:
                continue

        return None
