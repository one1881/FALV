from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.routes import approvals, auth, contracts, customers, stats, mcp
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YOLO 视频服务（:9001）自动拉起
# 后端启动时检测 9001，若未运行则用子进程拉起 yolo-video-service，
# 避免每次手动先起 YOLO。进程以分离方式启动，后端退出不影响它继续跑。
# ---------------------------------------------------------------------------
YOLO_PORT = 9001
_BACKEND_DIR = Path(__file__).resolve().parents[1]        # backend/
_PROJECT_ROOT = _BACKEND_DIR.parent                        # 项目根/
YOLO_SERVICE_DIR = _PROJECT_ROOT / "yolo-video-service"
YOLO_ENV_FILE = _BACKEND_DIR / ".env"


def _yolo_port_open(timeout: float = 1.0) -> bool:
    """检测 127.0.0.1:9001 是否已有服务在监听。"""
    try:
        with socket.create_connection(("127.0.0.1", YOLO_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _yolo_python_exe() -> str:
    """优先用 start_service.bat 同款解释器（装了 ultralytics/cv2），否则退回当前解释器。"""
    preferred = Path(r"D:\an\python.exe")
    if preferred.exists():
        return str(preferred)
    return sys.executable


def _yolo_env() -> dict:
    """复用 start_service.bat 的逻辑：把 backend/.env 注入子进程环境变量。"""
    env = os.environ.copy()
    try:
        for line in YOLO_ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env.setdefault(key.strip(), value.strip())
    except Exception as e:
        logger.warning(f"YOLO 自启动：读取 {YOLO_ENV_FILE} 失败（环境变量将继承当前进程）: {e}")
    return env


def _spawn_yolo_service() -> bool:
    """拉起 yolo-video-service 子进程，成功返回 True。"""
    app_py = YOLO_SERVICE_DIR / "app.py"
    if not app_py.exists():
        logger.warning(f"YOLO 自启动：找不到 {app_py}，跳过")
        return False
    cmd = [
        _yolo_python_exe(), "-m", "uvicorn", "app:app",
        "--host", "127.0.0.1", "--port", str(YOLO_PORT),
    ]
    creationflags = 0
    if os.name == "nt":
        # 分离进程：不随本后端退出而被杀，也不弹新窗口
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    log_fh = open(YOLO_SERVICE_DIR / "service.log", "ab")
    try:
        subprocess.Popen(
            cmd,
            cwd=str(YOLO_SERVICE_DIR),
            env=_yolo_env(),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        logger.info(f"YOLO 自启动：已派发子进程 {' '.join(cmd)}")
        return True
    except Exception as e:
        logger.error(f"YOLO 自启动失败: {e}")
        return False
    finally:
        # 子进程已通过 Popen 复制了自己的句柄，父进程这份可以关掉，避免句柄泄漏
        log_fh.close()


def _ensure_yolo_service_background() -> None:
    """在后台线程里等 YOLO 就绪并打日志，不阻塞后端启动。"""
    def _worker():
        if _yolo_port_open():
            logger.info("YOLO 视频服务已在运行（:9001），无需自启")
            return
        if not _spawn_yolo_service():
            return
        # YOLO 加载 yolo11s.pt 需要一段时间，最多等 60 秒确认健康
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(2)
            if _yolo_port_open():
                logger.info(f"YOLO 视频服务自启动成功（:{YOLO_PORT}）")
                return
        logger.warning("YOLO 视频服务自启动后 60 秒内未就绪，请检查 yolo-video-service/service.log")

    threading.Thread(target=_worker, name="yolo-autostart", daemon=True).start()


# ---------------------------------------------------------------------------
# A2A 子代理服务（:8001 起草 / :8002 审核）自动拉起
# 主代理（本进程）经 Agent Card 发现 + JSON-RPC message/send 派活；
# 服务不可达时主代理会自动回退进程内执行，这里拉起只是为了走标准 A2A 链路。
# ---------------------------------------------------------------------------
A2A_SERVERS = [
    ("app.a2a_servers.drafting_agent_server", 8001, "drafting-agent"),
    ("app.a2a_servers.review_agent_server", 8002, "review-agent"),
]
A2A_LOG_DIR = _BACKEND_DIR / "a2a_logs"


def _a2a_port_open(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _spawn_a2a_server(module: str, port: int) -> bool:
    cmd = [_yolo_python_exe(), "-m", module]
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        A2A_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_fh = open(A2A_LOG_DIR / f"{module.rsplit('.', 1)[-1]}.log", "ab")
    except Exception as e:
        logger.warning(f"A2A 自启动：日志文件创建失败: {e}")
        log_fh = None
    try:
        subprocess.Popen(
            cmd,
            cwd=str(_BACKEND_DIR),
            env=_yolo_env(),
            stdout=log_fh or subprocess.DEVNULL,
            stderr=subprocess.STDOUT if log_fh else None,
            creationflags=creationflags,
        )
        logger.info(f"A2A 自启动：已派发子进程 {' '.join(cmd)} (:{port})")
        return True
    except Exception as e:
        logger.error(f"A2A 自启动失败 ({module}): {e}")
        return False
    finally:
        if log_fh:
            log_fh.close()


def _pid_listening_on(port: int):
    """用 netstat 找出占用端口的进程 PID（Windows）。找不到返回 None。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(f":{port}"):
                return int(parts[4])
    except Exception:
        pass
    return None


def _agent_code_version_matches(port: int) -> bool:
    """比对子代理服务上报的代码指纹与当前磁盘指纹；取不到指纹时视为不匹配。"""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    from app.a2a.code_version import compute_agent_code_version
    return data.get("code_version") == compute_agent_code_version()


def _ensure_a2a_servers_background() -> None:
    """后台线程里逐个确保 A2A 子代理服务在线且代码版本最新，不阻塞后端启动。"""
    def _worker():
        for module, port, name in A2A_SERVERS:
            if _a2a_port_open(port):
                if _agent_code_version_matches(port):
                    logger.info(f"A2A 子代理 {name} 已在运行（:{port}，代码版本一致）")
                    continue
                # 代码已变更但旧进程还在跑旧代码 → 杀掉重启（治版本漂移）
                stale_pid = _pid_listening_on(port)
                logger.warning(f"A2A 子代理 {name}（:{port}）代码版本过期，准备重启 (pid={stale_pid})")
                if stale_pid:
                    try:
                        subprocess.run(["taskkill", "/PID", str(stale_pid), "/F"],
                                       capture_output=True, timeout=10)
                        time.sleep(2)
                    except Exception as e:
                        logger.error(f"A2A 子代理 {name} 旧进程终止失败: {e}")
                        continue
            if not _spawn_a2a_server(module, port):
                continue
            deadline = time.time() + 40
            while time.time() < deadline:
                time.sleep(2)
                if _a2a_port_open(port):
                    logger.info(f"A2A 子代理 {name} 自启动成功（:{port}）")
                    break
            else:
                logger.warning(f"A2A 子代理 {name} 自启动后 40 秒内未就绪，主代理将回退进程内执行，请查 backend/a2a_logs/")

    threading.Thread(target=_worker, name="a2a-autostart", daemon=True).start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_yolo_service_background()
    if settings.A2A_ENABLED:
        _ensure_a2a_servers_background()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    lifespan=lifespan,
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://10.223.9.87:5173",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|10\.223\.9\.87)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_private_network_access_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


# 注册路由
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(contracts.router, prefix=settings.API_V1_PREFIX)
app.include_router(approvals.router, prefix=settings.API_V1_PREFIX)
app.include_router(customers.router, prefix=settings.API_V1_PREFIX)
app.include_router(stats.router, prefix=settings.API_V1_PREFIX)
app.include_router(mcp.router, prefix=f"{settings.API_V1_PREFIX}/mcp")
from app.routes.review import router as review_router
from app.routes.litigation import router as litigation_router
app.include_router(review_router, prefix=settings.API_V1_PREFIX)
app.include_router(litigation_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    """健康检查（含 A2A 子代理与 YOLO 探活，一眼看出全家桶死活）"""
    def _port_alive(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            return False

    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "services": {
            "backend": True,
            "a2a_drafting_agent_8001": _port_alive(8001) if settings.A2A_ENABLED else None,
            "a2a_review_agent_8002": _port_alive(8002) if settings.A2A_ENABLED else None,
            "yolo_9001": _port_alive(YOLO_PORT),
        },
    }


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Contract Management System API",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
