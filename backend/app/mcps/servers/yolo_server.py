from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.core.config import settings
from app.core.net import new_proxy_immune_async_client
from app.mcps.base_server import BaseMCPServer


class YoloServer(BaseMCPServer):
    def __init__(self):
        super().__init__(name="yolo_server", description="YOLO 视频抽帧识别 MCP Server")
        self.register_tool(
            name="analyze_video",
            description="按间隔抽帧并使用 YOLO 识别视频对象和关键帧",
            input_schema={"type": "object", "properties": {"file_path": {"type": "string"}, "file_name": {"type": "string"}, "duration_seconds": {"type": "number"}}, "required": ["file_path"]},
            handler=self._analyze_video,
        )

    async def _analyze_video(self, file_path: str, file_name: str = "", duration_seconds: float = 300) -> Dict[str, Any]:
        interval = settings.YOLO_FRAME_INTERVAL_SECONDS
        sampled_frames = max(1, int(duration_seconds // interval))
        if not settings.YOLO_API_URL:
            return self._fallback(file_path, file_name, duration_seconds, interval, sampled_frames)
        path = Path(file_path)
        if not path.exists():
            return {**self._fallback(file_path, file_name, duration_seconds, interval, sampled_frames), "error": "文件不存在，已使用回退结果"}
        try:
            with path.open("rb") as file:
                files = {"file": (file_name or path.name, file, "application/octet-stream")}
                data = {
                    "duration_seconds": str(duration_seconds),
                    "frame_interval_seconds": str(interval),
                    "model_path": settings.YOLO_MODEL_PATH,
                }
                # trust_env=False（见 app/core/net.py）：防代理注入把抽帧识别请求绕死
                async with new_proxy_immune_async_client(600) as client:
                    response = await client.post(settings.YOLO_API_URL, data=data, files=files)
            response.raise_for_status()
            payload = response.json()
            return self._normalize(payload, duration_seconds, interval, sampled_frames)
        except Exception as exc:
            return {**self._fallback(file_path, file_name, duration_seconds, interval, sampled_frames), "error": f"YOLO 调用失败：{type(exc).__name__}: {exc}"}

    def _normalize(self, payload: Dict[str, Any], duration_seconds: float, interval: int, sampled_frames: int) -> Dict[str, Any]:
        data = payload.get("data", payload)
        return {
            "provider": "yolo",
            "mode": "api",
            "duration_seconds": data.get("duration_seconds", duration_seconds),
            "frame_interval_seconds": data.get("frame_interval_seconds", interval),
            "sampled_frames": data.get("sampled_frames", sampled_frames),
            "objects": data.get("objects", []),
            "key_frames": data.get("key_frames", []),
            "summary": data.get("summary") or "视频分析已完成，请人工确认关键帧和可证明事实。",
            "key_events": data.get("key_events", []),
            "proof_purpose": data.get("proof_purpose") or "证明现场状态、人员到场、车辆/货物出现、交付或履行过程。",
            "risk_notes": data.get("risk_notes", []),
            "need_confirm": data.get("need_confirm", []),
            "raw": payload,
            "confidence": data.get("confidence", 0.8),
        }

    def _fallback(self, file_path: str, file_name: str, duration_seconds: float, interval: int, sampled_frames: int) -> Dict[str, Any]:
        return {
            "provider": "yolo",
            "mode": "fallback",
            "duration_seconds": duration_seconds,
            "frame_interval_seconds": interval,
            "sampled_frames": sampled_frames,
            "objects": [{"label": "pending", "label_cn": "待识别对象", "count": 0, "confidence": 0.0}],
            "key_frames": [],
            "summary": f"YOLO API 未配置或调用失败，已保留视频等待抽帧识别：{file_name or file_path}",
            "key_events": [],
            "proof_purpose": "证明交付现场、货物状态、人员行为或事件经过",
            "risk_notes": ["视频内容需要结合原始文件属性、上传人说明和其他证据交叉确认。"],
            "need_confirm": ["拍摄时间", "拍摄地点", "画面主体身份", "画面物品与案件标的的关联性"],
            "confidence": 0.5,
        }
