@echo off
for /r %%d in (.) do (
    if not exist "%%d\DirTypeTextures" (
        echo. > "%%d\DirTypeTextures"
    )
)
echo 处理完成，已跳过已存在的文件，不会覆盖！
pause
