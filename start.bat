@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没找到 Python。请先安装 Python，安装时勾选 "Add Python to PATH"。
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo ==================================================
echo   GH Release Tracker - 自动记录你的 GitHub 下载
echo   正在扫描历史并开始自动监听...
echo   想停止时按 Ctrl+C 即可
echo ==================================================
echo.
python gh-release-tracker.py
echo.
echo 程序已退出，按任意键关闭窗口。
pause >nul
