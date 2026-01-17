#!/usr/bin/env python3
import os
import sys
import subprocess

def check_dependencies():
    """检查必要的依赖是否已安装"""
    try:
        import flask
        import flask_socketio
        print("✓ 已安装Flask和Flask-SocketIO")
        return True
    except ImportError:
        print("✗ 缺少必要的依赖")
        return False

def install_dependencies():
    """安装必要的依赖"""
    print("正在安装依赖...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
        print("✓ 依赖安装成功")
        return True
    except subprocess.CalledProcessError:
        print("✗ 依赖安装失败，请确保已安装pip")
        return False

def start_server():
    """启动游戏服务器"""
    print("正在启动服务器...")
    try:
        print("游戏服务器已启动！")
        print("请在浏览器中访问: http://localhost:5000")
        print("按Ctrl+C停止服务器")
        # 设置FLASK_APP环境变量为server.py
        env = os.environ.copy()
        env['FLASK_APP'] = 'server.py'
        subprocess.run([sys.executable, "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"], env=env)
    except KeyboardInterrupt:
        print("\n✓ 服务器已停止")
    except Exception as e:
        print(f"✗ 服务器启动失败: {e}")

if __name__ == "__main__":
    print("=== 战舰游戏离线服务器启动器 ===")
    
    if not check_dependencies():
        response = input("是否要安装依赖？(y/n): ")
        if response.lower() != "y":
            print("✗ 取消启动")
            sys.exit(1)
        if not install_dependencies():
            sys.exit(1)
    
    start_server()
