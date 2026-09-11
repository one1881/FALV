@echo off
REM ============================================================
REM 一键启动：后端 :8000 + 前端 :5173
REM YOLO 视频服务 :9001、A2A 子代理（起草 :8001 / 审核 :8002）
REM 均由后端启动时自动拉起，无需手动启动。
REM 关闭本窗口不会杀掉已启动的服务；要停服务请用任务管理器或：
REM   netstat -ano | findstr ":8000 :8001 :8002 :9001 :5173"
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

REM 清除沙箱/工具进程注入的代理变量。
REM 若 HTTP_PROXY=127.0.0.1:8279 被继承，模型请求会被绕进本地代理挂死（实测卡满 50 分钟）。
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "http_proxy="
set "https_proxy="
set "ALL_PROXY="
set "all_proxy="
set "NO_PROXY="
set "no_proxy="

echo [1/2] 启动后端 :8000 （YOLO :9001 与 A2A 子代理 :8001/:8002 会随后端自动拉起）...
start "legal-backend-8000" cmd /c "cd backend && D:\an\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

echo [2/2] 启动前端 :5173 ...
start "legal-frontend-5173" cmd /c "cd frontend && npm run dev"

echo.
echo 全部已派发：
echo   后端        http://127.0.0.1:8000/docs
echo   前端        http://localhost:5173
echo   YOLO        http://127.0.0.1:9001/health  （约 10~30 秒后可用，模型加载需要时间）
echo   A2A 起草    http://127.0.0.1:8001/.well-known/agent-card.json
echo   A2A 审核    http://127.0.0.1:8002/.well-known/agent-card.json
echo.
echo 日志位置：backend 窗口自身 + yolo-video-service\service.log + backend\a2a_logs\
pause
