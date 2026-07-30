#!/usr/bin/env python
"""
CampusRunner - 一键打包脚本

使用 PyInstaller 将 CampusRunner 打包为单文件 .exe。

用法:
    python build_exe.py              # 打包为单文件 exe
    python build_exe.py --console     # 带控制台窗口（调试用）
    python build_exe.py --clean       # 清理构建缓存后重新打包

输出:
    dist/CampusRunner.exe

注意:
    - 打包后需要将 config.json 和 routes/ 目录放在 exe 同目录
    - 首次运行会自动安装 PyInstaller
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path


def main():
    console_mode = "--console" in sys.argv
    clean_first = "--clean" in sys.argv

    project_dir = Path(__file__).parent
    os.chdir(project_dir)

    print("=" * 60)
    print("  CampusRunner - 打包工具")
    print("=" * 60)
    print(f"  项目目录: {project_dir}")
    print(f"  Python:   {sys.version}")

    # 确保依赖已安装
    print("\n[1/5] 检查依赖...")
    deps = [
        ("pyinstaller", "PyInstaller"),
        ("tkintermapview", "tkintermapview"),
    ]
    for pip_name, import_name in deps:
        try:
            __import__(import_name)
            print(f"  {pip_name} 已安装")
        except ImportError:
            print(f"  正在安装 {pip_name}...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pip_name],
                check=True,
            )
            print(f"  {pip_name} 安装完成")

    # 清理旧的构建文件
    if clean_first:
        print("\n[2/4] 清理旧构建...")
        for d in ["build", "dist", "__pycache__"]:
            path = project_dir / d
            if path.exists():
                shutil.rmtree(path)
                print(f"  已删除: {d}")
        spec_file = project_dir / "CampusRunner.spec"
        if spec_file.exists():
            spec_file.unlink()
            print("  已删除: CampusRunner.spec")
    else:
        print("\n[2/5] 跳过清理（使用 --clean 强制清理）")

    # 构建 PyInstaller 命令
    print("\n[3/5] 开始打包...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                     # 单文件输出
        "--name", "CampusRunner",        # 输出名称
        "--add-data", f"config.json{os.pathsep}.",     # 打包配置文件
        "--add-data", f"routes{os.pathsep}routes",     # 打包路线目录
        "--hidden-import", "tkinter",
        "--hidden-import", "socket",
        "--hidden-import", "json",
        "--hidden-import", "threading",
        "--hidden-import", "logging",
        "--hidden-import", "urllib.request",
        "--hidden-import", "xml.etree.ElementTree",
        "--collect-all", "tkinter",
        "--collect-all", "tkintermapview",
        "--collect-all", "customtkinter",
        "--hidden-import", "gui.dashboard",
        "--hidden-import", "gui.widgets",
        "--collect-all", "geocoder",
        "--collect-all", "geopy",
    ]

    if not console_mode:
        cmd.append("--windowed")  # 无控制台窗口

    cmd.append(str(project_dir / "main.py"))

    print(f"  命令: {' '.join(cmd[:6])} ...")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print("\n  ❌ 打包失败! 检查上方错误信息")
        sys.exit(1)

    # 验证输出
    print("\n[4/5] 验证输出...")
    exe_path = project_dir / "dist" / "CampusRunner.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"  [OK] 打包成功!")
        print(f"  输出文件: {exe_path}")
        print(f"  文件大小: {size_mb:.1f} MB")
        print(f"\n  使用说明:")
        print(f"  1. 将 {exe_path.name} 复制到任意目录")
        print(f"  2. 在同目录下放置 config.json (可编辑)")
        print(f"  3. 在同目录下创建 routes/ 文件夹 (存放路线文件)")
        print(f"  4. 双击运行 CampusRunner.exe")
    else:
        print("  [FAIL] 找不到输出文件，打包可能失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
