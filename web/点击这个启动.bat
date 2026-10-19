@echo off
cd /d "%~dp0"
title 烟雨江湖 · 本地存档工具
echo 正在启动本地服务器（http://127.0.0.1:8080）...
echo 浏览器将自动打开；关闭本窗口即停止服务。
echo.
if exist "%~dp0bin\node.exe" (
  "%~dp0bin\node.exe" server.js
) else (
  node server.js
)
echo.
pause
