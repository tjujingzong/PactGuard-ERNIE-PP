#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合同审查系统 - 工作流版本启动脚本
"""

import subprocess
import sys
import time
import requests
import os
from pathlib import Path


def check_mcp_service():
    """检查MCP服务是否运行"""
    try:
        response = requests.get("http://localhost:7001/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def start_mcp_service():
    """启动MCP服务"""
    print("🚀 启动MCP文档处理服务...")
    try:
        # 在后台启动MCP服务
        process = subprocess.Popen(
            [sys.executable, "mcp_service.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # 等待服务启动
        for i in range(30):  # 最多等待30秒
            if check_mcp_service():
                print("✅ MCP服务启动成功")
                return process
            time.sleep(1)
            print(f"⏳ 等待MCP服务启动... ({i+1}/30)")

        print("❌ MCP服务启动超时")
        return None

    except Exception as e:
        print(f"❌ 启动MCP服务失败: {e}")
        return None


def start_ui():
    """启动UI界面"""
    print("🌐 启动Web界面...")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "ui_workflow.py",
                "--server.port",
                "8501",
                "--server.address",
                "localhost",
            ]
        )
    except KeyboardInterrupt:
        print("\n👋 用户中断，正在退出...")
    except Exception as e:
        print(f"❌ 启动UI失败: {e}")


def main():
    """主函数"""
    print("=" * 60)
    print("📄 合同审查系统 - 工作流版本")
    print("=" * 60)

    # 检查必要文件
    required_files = ["mcp_service.py", "ui_workflow.py", "contract_workflow.py"]
    for file in required_files:
        if not os.path.exists(file):
            print(f"❌ 缺少必要文件: {file}")
            sys.exit(1)

    # 检查MCP服务是否已运行
    if check_mcp_service():
        print("✅ MCP服务已在运行")
        mcp_process = None
    else:
        mcp_process = start_mcp_service()
        if not mcp_process:
            print("❌ 无法启动MCP服务，请手动启动")
            sys.exit(1)

    try:
        # 启动UI
        start_ui()
    finally:
        # 清理MCP进程
        if mcp_process:
            print("🔄 正在关闭MCP服务...")
            mcp_process.terminate()
            mcp_process.wait()
            print("✅ MCP服务已关闭")


if __name__ == "__main__":
    main()
