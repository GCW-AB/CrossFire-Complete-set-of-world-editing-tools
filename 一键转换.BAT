@echo off
chcp 65001 >nul
if "%~1"=="" (
    echo 使用方法：将需要处理的文件拖拽到本bat文件上
    pause
    exit
)
python dat2lt85.py "%~1" -v1
echo.
echo 执行完成
pause
