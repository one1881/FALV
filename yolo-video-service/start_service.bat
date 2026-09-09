@echo off
REM yolo-video-service 启动脚本（Windows）
REM 作用：从 backend\.env 导入 Qwen-VL / ASR 环境变量后再启动服务，
REM       避免 QWEN_VL_* 未配置导致视频 summary 静默降级为规则模板。
REM 用法：双击运行，或在命令行执行 start_service.bat
REM 健康检查：curl http://127.0.0.1:9001/health  （degraded 必须为 false）

cd /d "%~dp0"

for /f "usebackq eol=# tokens=1,* delims==" %%a in ("..\backend\.env") do (
    set "%%a=%%b"
)

"D:\an\python.exe" -m uvicorn app:app --host 0.0.0.0 --port 9001
