"""
校园跑助手 (CampusRunner) - 雷电模拟器 GPS 位置模拟工具

用法:
    python main.py          # 启动 GUI 控制面板
    python main.py --cli    # CLI 模式（基础功能）

CLI 模式支持:
    python main.py --cli test-adb              # 测试 ADB 连接
    python main.py --cli inject <lat> <lng>   # 单点 GPS 注入测试

要求:
    - Python 3.11+
    - 雷电模拟器9 或其他 Android 模拟器
    - ADB (Android Debug Bridge)
"""

import sys
import os
import argparse
import logging


def get_base_path():
    """
    获取项目根目录路径，兼容开发模式和 PyInstaller 打包模式。

    PyInstaller 打包后，sys._MEIPASS 指向临时解压目录，
    而 sys.executable 指向 exe 所在目录（用户可编辑 config.json）。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包模式
        return os.path.dirname(sys.executable)
    else:
        # 开发模式
        return os.path.dirname(os.path.abspath(__file__))


BASE_PATH = get_base_path()

# 将项目目录加入 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.adb_client import ADBClient
from core.route_engine import RouteGenerator
from core.location_injector import LocationInjector


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="CampusRunner - 校园跑助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                     启动 GUI 界面
  python main.py --cli test-adb      测试 ADB 连接
  python main.py --cli inject 39.9923 116.3264  测试 GPS 注入
  python main.py --cli route 39.9923 116.3264 --distance 2000  生成路线预览
        """,
    )
    parser.add_argument("--cli", action="store_true", help="CLI 模式")
    parser.add_argument("--legacy", action="store_true", help="使用旧版 GUI (v0.4)")
    parser.add_argument("--classic", action="store_true", help="使用 v0.4 dashboard")
    parser.add_argument("action", nargs="?", help="操作: test-adb | inject | route")
    parser.add_argument("args", nargs="*", help="操作参数")
    parser.add_argument("--distance", type=float, default=2000, help="路线距离（米）")

    return parser.parse_args()


def cli_test_adb():
    """CLI: 测试 ADB 连接"""
    adb_path = ADBClient.find_adb()
    if adb_path is None:
        print("❌ 未找到 ADB，请安装 Android SDK Platform Tools 或雷电模拟器")
        print("   默认搜索路径: D:/op/adb.exe, C:/leidian/LDPlayer9/adb.exe, ...")
        return

    print(f"✓ 找到 ADB: {adb_path}")

    client = ADBClient(adb_path)
    print(f"正在连接模拟器 (127.0.0.1:5555)...")

    if client.connect():
        print("✓ 连接成功!")

        android_ver = client.get_android_version()
        model = client.get_device_model()
        print(f"  设备型号: {model or 'Unknown'}")
        print(f"  Android 版本: {android_ver or 'Unknown'}")
    else:
        print("❌ 连接失败，请确保:")
        print("   1. 雷电模拟器9 已启动")
        print("   2. ADB 调试已开启")
        print("   3. 尝试手动执行: adb connect 127.0.0.1:5555")


def cli_test_inject(lat: float, lng: float):
    """CLI: 测试 GPS 注入"""
    adb_path = ADBClient.find_adb()
    if adb_path is None:
        print("❌ 未找到 ADB")
        return

    injector = LocationInjector(
        adb_path=adb_path,
        host="127.0.0.1",
        console_port=5554,
    )

    print(f"尝试自动连接 GPS 注入器...")
    if injector.auto_connect():
        print(f"✓ 使用注入器: {injector.active_injector_name}")

        if injector.set_location(lat, lng):
            print(f"✓ 已注入坐标: ({lat}, {lng})")
            print("  请在模拟器中打开 Keep App 查看位置是否更新")
        else:
            print("❌ 坐标注入失败")
    else:
        print("❌ 没有可用的注入器")
        print("  请确保模拟器已启动并开启了开发者选项")


def cli_route_preview(center_lat: float, center_lng: float, distance: float):
    """CLI: 生成路线并打印预览"""
    route = RouteGenerator.generate_campus_default(
        center_lat=center_lat,
        center_lng=center_lng,
        total_distance_m=distance,
    )

    print(f"路线: {route.name}")
    print(f"路径点: {route.point_count}")
    print(f"总距离: {route.total_distance_m:.0f} 米")
    print(f"起点: ({route.waypoints[0].lat:.6f}, {route.waypoints[0].lng:.6f})")
    print(f"终点: ({route.waypoints[-1].lat:.6f}, {route.waypoints[-1].lng:.6f})")
    print(f"预计用时 ({10}km/h): {distance/1000/10*60:.1f} 分钟")
    print(f"预计用时 ({8}km/h): {distance/1000/8*60:.1f} 分钟")


def main():
    args = parse_args()

    if args.cli:
        # CLI 模式
        if args.action == "test-adb":
            cli_test_adb()
        elif args.action == "inject":
            if len(args.args) < 2:
                print("用法: python main.py --cli inject <纬度> <经度>")
                return
            lat, lng = float(args.args[0]), float(args.args[1])
            cli_test_inject(lat, lng)
        elif args.action == "route":
            if len(args.args) < 2:
                print("用法: python main.py --cli route <纬度> <经度> [--distance 2000]")
                return
            lat, lng = float(args.args[0]), float(args.args[1])
            cli_route_preview(lat, lng, args.distance)
        else:
            print("可用操作: test-adb | inject <lat> <lng> | route <lat> <lng>")
            print("不带参数运行启动 GUI 界面")
    else:
        # GUI 模式 — 默认 Soft UI
        if args.legacy:
            print("启动 CampusRunner GUI (旧版)...")
            from gui.main_window import MainWindow
            app = MainWindow()
            app.run()
        elif args.classic:
            print("启动 CampusRunner Dashboard (v0.4)...")
            from gui.dashboard import AppDashboard
            app = AppDashboard()
            app.run()
        else:
            print("启动 CampusRunner Soft UI...")
            from gui.soft_ui import SoftDashboard
            app = SoftDashboard()
            app.run()


if __name__ == "__main__":
    main()
