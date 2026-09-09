"""A2A 相关代码的版本指纹：主控后端用它检测子代理服务进程是否跑的旧代码。

背景：:8001/:8002 是分离常驻进程，后端重启不会更新它们。
启动时比对「服务进程上报的指纹」与「当前磁盘代码指纹」，不一致就杀掉重启。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# 参与 A2A 子代理行为的代码文件（相对 backend/）
_AGENT_CODE_PATTERNS = [
    "app/a2a/*.py",
    "app/a2a_servers/*.py",
    "app/services/agent_core.py",
]


def compute_agent_code_version() -> str:
    """对 A2A 相关源码做内容哈希；文件增删/改动都会改变指纹。"""
    digest = hashlib.sha256()
    files: list[Path] = []
    for pattern in _AGENT_CODE_PATTERNS:
        files.extend(sorted(BACKEND_ROOT.glob(pattern)))
    for path in files:
        try:
            content = path.read_bytes()
        except OSError:
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(str(len(content)).encode("ascii"))
        digest.update(content)
    return digest.hexdigest()[:16]
