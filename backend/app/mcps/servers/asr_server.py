from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Dict

import httpx

from app.core.config import settings
from app.mcps.base_server import BaseMCPServer


class ASRServer(BaseMCPServer):
    """通义听悟语音转写 MCP Server（DashScope paraformer-v2）。

    流程：getPolicy 拿临时 OSS 凭证 -> 上传本地音频 -> 提交转写 -> 轮询结果。
    本地文件直接上传，无需用户自建 OSS。
    """

    def __init__(self):
        super().__init__(name="asr_server", description="通义听悟语音转写（DashScope paraformer-v2）")
        self.register_tool(
            name="transcribe_audio",
            description="转写录音，本地文件自动上传，长音频按配置切片处理",
            input_schema={"type": "object", "properties": {"file_path": {"type": "string"}, "file_name": {"type": "string"}, "duration_seconds": {"type": "number"}}, "required": ["file_path"]},
            handler=self._transcribe_audio,
        )

    async def _transcribe_audio(self, file_path: str, file_name: str = "", duration_seconds: float = 1200) -> Dict[str, Any]:
        base = (settings.ASR_API_URL or "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
        api_key = settings.ASR_API_KEY
        chunk_seconds = settings.ASR_MAX_CHUNK_SECONDS
        chunk_count = max(1, int((duration_seconds + chunk_seconds - 1) // chunk_seconds))

        if not api_key:
            return self._fallback(file_path, file_name, duration_seconds, chunk_seconds, chunk_count, "未配置 ASR_API_KEY")
        path = Path(file_path)
        if not path.exists():
            return self._fallback(file_path, file_name, duration_seconds, chunk_seconds, chunk_count, "文件不存在")

        try:
            audio_path = await self._prepare_audio(path)
            auth = {"Authorization": f"Bearer {api_key}"}

            async with httpx.AsyncClient(timeout=180) as client:
                # 1. 获取上传凭证
                policy_resp = await client.get(
                    f"{base}/uploads",
                    headers={**auth, "Content-Type": "application/json"},
                    params={"action": "getPolicy", "model": "paraformer-v2"},
                )
                policy_resp.raise_for_status()
                policy = policy_resp.json()["data"]
                key = f"{policy['upload_dir']}/{audio_path.name}"

                # 2. 上传本地音频到临时 OSS
                audio_bytes = audio_path.read_bytes()
                upload_resp = await client.post(
                    policy["upload_host"],
                    data={
                        "OSSAccessKeyId": policy["oss_access_key_id"],
                        "Signature": policy["signature"],
                        "policy": policy["policy"],
                        "x-oss-object-acl": policy["x_oss_object_acl"],
                        "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"],
                        "key": key,
                        "success_action_status": "200",
                    },
                    files={"file": (audio_path.name, audio_bytes, "audio/wav")},
                )
                upload_resp.raise_for_status()
                oss_url = f"oss://{key}"

                # 3. 提交转写任务
                task_resp = await client.post(
                    f"{base}/services/audio/asr/transcription",
                    headers={**auth, "Content-Type": "application/json", "X-DashScope-Async": "enable", "X-DashScope-OssResourceResolve": "enable"},
                    json={"model": "paraformer-v2", "input": {"file_urls": [oss_url]}, "parameters": {"language_hints": ["zh"], "diarization_enabled": True}},
                )
                task_resp.raise_for_status()
                task_id = task_resp.json()["output"]["task_id"]

                # 4. 轮询结果
                for _ in range(80):
                    await asyncio.sleep(3)
                    query_resp = await client.get(f"{base}/tasks/{task_id}", headers=auth)
                    query_resp.raise_for_status()
                    output = query_resp.json().get("output", {})
                    status = output.get("task_status")
                    if status == "SUCCEEDED":
                        transcript = await self._fetch_transcript(client, output)
                        return self._normalize(transcript, duration_seconds, chunk_seconds, chunk_count)
                    if status in ("FAILED", "CANCELED"):
                        return self._fallback(file_path, file_name, duration_seconds, chunk_seconds, chunk_count, f"转写失败：{output.get('code') or output.get('message') or status}")

                return self._fallback(file_path, file_name, duration_seconds, chunk_seconds, chunk_count, "转写超时")
        except Exception as exc:
            return self._fallback(file_path, file_name, duration_seconds, chunk_seconds, chunk_count, f"ASR 调用失败：{type(exc).__name__}: {exc}")

    async def _prepare_audio(self, path: Path) -> Path:
        """统一转成 16k 单声道 wav（paraformer 对 48k 立体声 m4a 会转写失败）。"""
        tmp = Path(tempfile.gettempdir()) / f"asr_{path.stem}_16k.wav"
        cmd = ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", "16000", str(tmp)]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()
        except FileNotFoundError:
            return path
        return tmp if tmp.exists() and tmp.stat().st_size > 0 else path

    async def _fetch_transcript(self, client: httpx.AsyncClient, output: Dict[str, Any]) -> Dict[str, Any]:
        """拉取转写结果，收集句子级时间戳与说话人编号。

        DashScope 返回 transcripts[].sentences[]，每句含 begin_time/end_time（毫秒）、
        text，diarization_enabled 开启后每句还带 speaker_id。旧代码只取 text 丢弃
        时间戳，导致转写永远是一坨无时间标注的纯文本——现在全部保留。
        """
        full_text_parts: list = []
        raw_sentences: list = []
        for item in output.get("results") or []:
            tu = item.get("transcription_url") or (item.get("output") or {}).get("transcription_url")
            if not tu:
                continue
            resp = await client.get(tu)
            resp.raise_for_status()
            data = resp.json()
            for t in data.get("transcripts", []):
                full_text_parts.append(t.get("text", ""))
                for s in t.get("sentences") or []:
                    text = (s.get("text") or "").strip()
                    if not text:
                        continue
                    raw_sentences.append({
                        "begin_ms": s.get("begin_time"),
                        "end_ms": s.get("end_time"),
                        "speaker_id": s.get("speaker_id"),
                        "text": text,
                    })
        return {"text": "".join(full_text_parts), "sentences": raw_sentences}

    @staticmethod
    def _ms_to_ts(ms: Any) -> str:
        """毫秒 → mm:ss（超 1 小时转 h:mm:ss）。缺失返回 '?'。"""
        try:
            total = int(ms) // 1000
        except (TypeError, ValueError):
            return "?"
        h, rem = divmod(total, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

    @classmethod
    def _merge_turns(cls, sentences: list, max_turns: int = 200) -> list:
        """句子 → 说话人轮次：连续同一说话人的句子合并成一段，避免逐句碎片化。"""
        turns: list = []
        for s in sentences:
            spk = f"说话人{(s.get('speaker_id') or 0) + 1}" if s.get("speaker_id") is not None else "说话人待识别"
            if turns and turns[-1]["speaker"] == spk:
                turns[-1]["_end_ms"] = s.get("end_ms")
                turns[-1]["text"] += s["text"]
            else:
                turns.append({
                    "_start_ms": s.get("begin_ms"),
                    "_end_ms": s.get("end_ms"),
                    "speaker": spk,
                    "text": s["text"],
                })
            if len(turns) >= max_turns:
                break
        for t in turns:
            t["start"] = cls._ms_to_ts(t.pop("_start_ms"))
            t["end"] = cls._ms_to_ts(t.pop("_end_ms"))
        return turns

    def _normalize(self, transcript: Dict[str, Any], duration_seconds: float, chunk_seconds: int, chunk_count: int) -> Dict[str, Any]:
        text = (transcript or {}).get("text") or ""
        segments = self._merge_turns((transcript or {}).get("sentences") or [])
        return {
            "provider": "dashscope_paraformer",
            "mode": "api",
            "duration_seconds": duration_seconds,
            "chunk_seconds": chunk_seconds,
            "chunk_count": chunk_count,
            "transcript": text,
            "segments": segments,
            "key_info": {"待确认字段": "说话人、金额、日期、付款承诺、催告内容、对方抗辩"},
            "confidence": 0.9,
        }

    def _fallback(self, file_path: str, file_name: str, duration_seconds: float, chunk_seconds: int, chunk_count: int, reason: str) -> Dict[str, Any]:
        return {
            "provider": "asr",
            "mode": "fallback",
            "duration_seconds": duration_seconds,
            "chunk_seconds": chunk_seconds,
            "chunk_count": chunk_count,
            "transcript": f"ASR 未转写成功（{reason}），已保留录音等待转写：{file_name or file_path}",
            "segments": [
                {"start": "00:00:00", "end": "00:05:00", "speaker": "待识别", "text": "待转写", "tags": ["待确认"]}
            ],
            "key_info": {"待确认字段": "说话人、金额、日期、付款承诺、催告内容、对方抗辩"},
            "confidence": 0.5,
            "error": reason,
        }
