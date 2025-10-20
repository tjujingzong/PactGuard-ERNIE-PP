#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合同审查系统启动脚本
自动激活conda环境并启动所有服务
"""

import os
import sys
import subprocess
import time
import threading
import signal
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('service_startup.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ServiceManager:
    def __init__(self):
        self.processes = {}
        self.running = True
        
    def start_service(self, name, command, cwd=None, env=None):
        """启动单个服务"""
        try:
            logger.info(f"启动服务: {name}")
            logger.info(f"命令: {command}")
            
            # 设置环境变量
            process_env = os.environ.copy()
            if env:
                process_env.update(env)
            
            # 启动进程
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            
            self.processes[name] = process
            logger.info(f"服务 {name} 已启动，PID: {process.pid}")
            return True
            
        except Exception as e:
            logger.error(f"启动服务 {name} 失败: {str(e)}")
            return False
    
    def stop_service(self, name):
        """停止单个服务"""
        if name in self.processes:
            process = self.processes[name]
            try:
                process.terminate()
                process.wait(timeout=5)
                logger.info(f"服务 {name} 已停止")
            except subprocess.TimeoutExpired:
                process.kill()
                logger.warning(f"强制停止服务 {name}")
            except Exception as e:
                logger.error(f"停止服务 {name} 失败: {str(e)}")
            finally:
                del self.processes[name]
    
    def stop_all_services(self):
        """停止所有服务"""
        logger.info("正在停止所有服务...")
        for name in list(self.processes.keys()):
            self.stop_service(name)
        logger.info("所有服务已停止")
    
    def check_service_health(self, name, url, timeout=5):
        """检查服务健康状态"""
        try:
            import requests
            response = requests.get(url, timeout=timeout)
            return response.status_code == 200
        except:
            return False
    
    def wait_for_service(self, name, url, max_wait=30):
        """等待服务启动"""
        logger.info(f"等待服务 {name} 启动...")
        for i in range(max_wait):
            if self.check_service_health(name, url):
                logger.info(f"服务 {name} 已就绪")
                return True
            time.sleep(1)
        logger.warning(f"服务 {name} 启动超时")
        return False

def get_conda_activate_command():
    """获取conda激活命令"""
    if os.name == 'nt':  # Windows
        # 尝试找到conda
        conda_paths = [
            os.path.expanduser("~/anaconda3/Scripts/activate.bat"),
            os.path.expanduser("~/miniconda3/Scripts/activate.bat"),
            "C:/anaconda3/Scripts/activate.bat",
            "C:/miniconda3/Scripts/activate.bat",
            "C:/ProgramData/Anaconda3/Scripts/activate.bat",
            "C:/ProgramData/Miniconda3/Scripts/activate.bat"
        ]
        
        for conda_path in conda_paths:
            if os.path.exists(conda_path):
                return f'call "{conda_path}" websearch && '
        
        # 如果找不到，尝试使用conda命令
        return "conda activate websearch && "
    else:  # Linux/Mac
        return "source ~/anaconda3/bin/activate websearch && "

def main():
    """主函数"""
    logger.info("=" * 50)
    logger.info("合同审查系统启动脚本")
    logger.info("=" * 50)
    
    # 检查当前目录
    current_dir = Path.cwd()
    logger.info(f"当前工作目录: {current_dir}")
    
    # 检查必要文件
    required_files = ['ui_app.py', 'agents.py', 'mcp_service.py']
    for file in required_files:
        if not Path(file).exists():
            logger.error(f"缺少必要文件: {file}")
            sys.exit(1)
    
    # 创建服务管理器
    service_manager = ServiceManager()
    
    # 设置信号处理
    def signal_handler(signum, frame):
        logger.info("接收到停止信号，正在关闭服务...")
        service_manager.running = False
        service_manager.stop_all_services()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # 获取conda激活命令
        conda_prefix = get_conda_activate_command()
        logger.info(f"使用conda命令前缀: {conda_prefix}")
        
        # 启动MCP服务
        logger.info("启动MCP服务...")
        mcp_command = f"{conda_prefix}python mcp_service.py"
        if not service_manager.start_service("mcp", mcp_command):
            logger.error("MCP服务启动失败")
            sys.exit(1)
        
        # 等待MCP服务启动
        if not service_manager.wait_for_service("mcp", "http://localhost:7001/health"):
            logger.error("MCP服务启动超时")
            sys.exit(1)
        
        # 启动Agent服务
        logger.info("启动Agent服务...")
        agents_command = f"{conda_prefix}python agents.py all"
        if not service_manager.start_service("agents", agents_command):
            logger.error("Agent服务启动失败")
            service_manager.stop_service("mcp")
            sys.exit(1)
        
        # 等待Agent服务启动
        agent_urls = [
            ("legal", "http://localhost:7002/health"),
            ("business", "http://localhost:7003/health"),
            ("format", "http://localhost:7004/health"),
            ("processor", "http://localhost:7005/health"),
            ("highlighter", "http://localhost:7006/health"),
            ("integrator", "http://localhost:7007/health")
        ]
        
        for name, url in agent_urls:
            if not service_manager.wait_for_service(name, url, max_wait=60):
                logger.warning(f"Agent服务 {name} 启动超时，但继续启动UI")
        
        # 启动Streamlit UI
        logger.info("启动Streamlit UI...")
        ui_command = f"{conda_prefix}streamlit run ui_app.py --server.port 8501"
        if not service_manager.start_service("ui", ui_command):
            logger.error("UI服务启动失败")
            service_manager.stop_all_services()
            sys.exit(1)
        
        logger.info("=" * 50)
        logger.info("所有服务启动完成！")
        logger.info("访问地址: http://localhost:8501")
        logger.info("按 Ctrl+C 停止所有服务")
        logger.info("=" * 50)
        
        # 保持运行
        while service_manager.running:
            time.sleep(1)
            
            # 检查服务状态
            for name, process in list(service_manager.processes.items()):
                if process.poll() is not None:
                    logger.error(f"服务 {name} 意外停止")
                    service_manager.running = False
                    break
        
    except KeyboardInterrupt:
        logger.info("用户中断，正在关闭服务...")
    except Exception as e:
        logger.error(f"启动过程中发生错误: {str(e)}")
    finally:
        service_manager.stop_all_services()
        logger.info("启动脚本结束")

if __name__ == "__main__":
    main()
