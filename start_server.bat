@echo off
chcp 65001 >nul
echo === 战舰游戏离线服务器启动器 ===
echo.

:: 检查Python是否安装
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo 错误: 未找到Python环境，请先安装Python 3.6或更高版本
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo 检测到Python环境...
echo.

:: 检查依赖
python -c "import flask; import flask_socketio" >nul 2>nul
if %errorlevel% neq 0 (
    echo 正在安装必要的依赖...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo 错误: 依赖安装失败
        pause
        exit /b 1
    )
    echo 依赖安装完成！
    echo.
)

echo 启动游戏服务器...
echo 请在浏览器中访问: http://localhost:5000
echo 按Ctrl+C停止服务器
echo.

:: 设置FLASK_APP并启动服务器
set FLASK_APP=server.py
python -m flask run --host=0.0.0.0 --port=5000

pause
