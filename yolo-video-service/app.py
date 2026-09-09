from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import httpx
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware

try:
    from ultralytics import YOLO
except Exception:  # pragma: no cover
    YOLO = None

app = FastAPI(title="YOLO Video Evidence Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_MODEL_CACHE: dict[str, Any] = {}
DEFAULT_MODEL = "yolo11s.pt"
OUTPUT_DIR = Path("outputs")
LEGAL_OBJECT_MAP = {
    "person": "人员",
    "car": "车辆",
    "truck": "货车",
    "bus": "车辆",
    "motorcycle": "摩托车",
    "bicycle": "自行车",
    "cell phone": "手机",
    "laptop": "电脑",
    "book": "文件/册页",
    "backpack": "包裹",
    "suitcase": "箱包",
    "bottle": "物品",
    "chair": "现场设施",
    "dining table": "桌面/工作台",
}

QWEN_VL_API_URL = os.getenv("QWEN_VL_API_URL", "").rstrip("/")
QWEN_VL_API_KEY = os.getenv("QWEN_VL_API_KEY", "")
QWEN_VL_MODEL = os.getenv("QWEN_VL_MODEL", "qwen-vl-plus")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "").rstrip("/")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
ASR_API_URL = os.getenv("ASR_API_URL", "").rstrip("/")
ASR_API_KEY = os.getenv("ASR_API_KEY", "")
ASR_MAX_CHUNK_SECONDS = int(os.getenv("ASR_MAX_CHUNK_SECONDS", "300"))


def get_model(model_path: str):
    if YOLO is None:
        return None
    model_key = model_path or DEFAULT_MODEL
    if model_key != DEFAULT_MODEL and not Path(model_key).exists():
        model_key = DEFAULT_MODEL
    if model_key not in _MODEL_CACHE:
        _MODEL_CACHE[model_key] = YOLO(model_key)
    return _MODEL_CACHE[model_key]


def seconds_to_ts(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def run_ffmpeg(command: list[str]) -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return completed.returncode == 0


def extract_audio_track(video_path: Path, output_dir: Path) -> Path | None:
    audio_path = output_dir / "audio.wav"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]
    if run_ffmpeg(command) and audio_path.exists() and audio_path.stat().st_size > 0:
        return audio_path
    return None


def sample_frames(video_path: Path, frame_interval_seconds: int, output_dir: Path) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_interval_seconds = max(1, frame_interval_seconds)
    if shutil.which("ffmpeg") is not None:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{frame_interval_seconds}",
            str(output_dir / "frame_%04d.jpg"),
        ]
        if run_ffmpeg(command):
            sampled = []
            for index, frame_path in enumerate(sorted(output_dir.glob("frame_*.jpg"))):
                timestamp = index * frame_interval_seconds
                sampled.append(
                    {
                        "index": index,
                        "frame_no": index,
                        "timestamp": timestamp,
                        "timestamp_text": seconds_to_ts(timestamp),
                        "frame_path": str(frame_path),
                    }
                )
            return sampled[:300]

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps else 0
    interval_frames = max(1, int(fps * frame_interval_seconds))
    sampled = []
    index = 0
    frame_no = 0
    while frame_no < frame_count:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok:
            break
        timestamp = frame_no / fps if fps else index * frame_interval_seconds
        frame_path = output_dir / f"frame_{index:04d}.jpg"
        cv2.imwrite(str(frame_path), frame)
        sampled.append(
            {
                "index": index,
                "frame_no": frame_no,
                "timestamp": timestamp,
                "timestamp_text": seconds_to_ts(timestamp),
                "frame_path": str(frame_path),
            }
        )
        index += 1
        frame_no += interval_frames
    cap.release()
    return sampled[:300] if duration > 0 else sampled


def detect_frames(frames: list[dict[str, Any]], model_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    model = get_model(model_path)
    if model is None:
        return [], [{**frame, "objects": [], "summary": "ultralytics 未安装或模型不可用，未执行 YOLO 检测。"} for frame in frames]
    object_counter: Counter[str] = Counter()
    confidences: defaultdict[str, list[float]] = defaultdict(list)
    key_frames = []
    for frame in frames:
        result = model(frame["frame_path"], verbose=False)[0]
        objects = []
        for box in result.boxes:
            class_id = int(box.cls[0])
            label = result.names.get(class_id, str(class_id))
            confidence = float(box.conf[0])
            label_cn = LEGAL_OBJECT_MAP.get(label, label)
            object_counter[label_cn] += 1
            confidences[label_cn].append(confidence)
            objects.append({"label": label, "label_cn": label_cn, "confidence": round(confidence, 4)})
        if objects:
            key_frames.append(
                {
                    **frame,
                    "objects": objects,
                    "summary": f"画面中识别到：{'、'.join(sorted({item['label_cn'] for item in objects}))}。",
                }
            )
    detected_objects = [
        {
            "label_cn": label,
            "count": count,
            "confidence": round(sum(confidences[label]) / max(1, len(confidences[label])), 4),
        }
        for label, count in object_counter.most_common()
    ]
    return detected_objects, key_frames[:20]


def select_visual_frames(frames: list[dict[str, Any]], key_frames: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    """选择送入多模态模型的帧。

    优先使用 YOLO 命中的关键帧；如果 YOLO 没命中，则从普通抽帧中均匀抽样，
    避免视频在“无可检测对象”时完全失去画面语义理解能力。
    """
    if key_frames:
        return key_frames[:limit]
    if not frames:
        return []
    limit = max(1, min(limit, len(frames)))
    if limit == len(frames):
        return frames
    step = max(1, len(frames) // limit)
    selected = frames[::step][:limit]
    if frames[-1] not in selected and len(selected) < limit:
        selected.append(frames[-1])
    return selected[:limit]


def build_rule_summary(objects: list[dict[str, Any]], key_frames: list[dict[str, Any]], transcript: str = "") -> dict[str, Any]:
    names = [item["label_cn"] for item in objects]
    events = []
    for frame in key_frames[:8]:
        object_names = sorted({item["label_cn"] for item in frame.get("objects", [])})
        events.append(
            {
                "time": frame["timestamp_text"],
                "event": f"画面出现{'、'.join(object_names) or '待识别对象'}。",
                "evidence_value": "可辅助证明现场状态、参与人员、车辆/货物出现或交付过程。",
                "frame_path": frame["frame_path"],
            }
        )
    if {"人员", "货车"}.issubset(set(names)):
        summary = "视频中出现人员和货车，可能与货物交付、运输或现场作业过程有关。"
    elif "人员" in names:
        summary = "视频中出现人员活动，可用于辅助还原现场经过和参与主体。"
    elif transcript:
        summary = "视频音轨已提取，可结合音频转写和抽帧结果辅助认定案件事实。"
    else:
        summary = "视频已完成抽帧识别，需律师结合案情确认画面与本案事实的关联性。"
    return {
        "summary": summary,
        "key_events": events,
        "proof_purpose": "证明现场状态、人员到场、车辆/货物出现、交付或履行过程。",
        "risk_notes": [
            "视频无法单独证明拍摄时间和地点，需要结合原始文件属性、聊天记录或证人说明。",
            "需确认画面中的人员、车辆、货物是否与本案主体和合同标的对应。",
        ],
        "need_confirm": [
            "视频拍摄时间是否为争议发生当天",
            "画面中的人员身份是否明确",
            "画面中的物品是否为本案合同标的",
        ],
    }


def parse_json_text(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if not candidate:
        return {}
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(candidate[start:end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
    return {}


async def transcribe_audio(audio_path: Path, file_name: str, duration_seconds: float) -> dict[str, Any]:
    chunk_seconds = ASR_MAX_CHUNK_SECONDS
    chunk_count = max(1, int((duration_seconds + chunk_seconds - 1) // chunk_seconds))
    if not ASR_API_URL or not ASR_API_KEY:
        return {
            "provider": "asr",
            "mode": "fallback",
            "duration_seconds": duration_seconds,
            "chunk_seconds": chunk_seconds,
            "chunk_count": chunk_count,
            "transcript": f"ASR 未配置，已保留音轨等待转写：{file_name}",
            "confidence": 0.5,
            "error": "ASR_API_URL 或 ASR_API_KEY 未配置",
        }
    base_url = ASR_API_URL
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            policy_resp = await client.get(
                f"{base_url}/uploads",
                headers={"Authorization": f"Bearer {ASR_API_KEY}", "Content-Type": "application/json"},
                params={"action": "getPolicy", "model": "paraformer-v2"},
            )
            policy_resp.raise_for_status()
            policy = policy_resp.json()["data"]
            key = f"{policy['upload_dir']}/{audio_path.name}"
            with audio_path.open("rb") as file_handle:
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
                    files={"file": (audio_path.name, file_handle.read(), "audio/wav")},
                )
            upload_resp.raise_for_status()
            task_resp = await client.post(
                f"{base_url}/services/audio/asr/transcription",
                headers={
                    "Authorization": f"Bearer {ASR_API_KEY}",
                    "Content-Type": "application/json",
                    "X-DashScope-Async": "enable",
                    "X-DashScope-OssResourceResolve": "enable",
                },
                json={"model": "paraformer-v2", "input": {"file_urls": [f"oss://{key}"]}, "parameters": {"language_hints": ["zh"]}},
            )
            task_resp.raise_for_status()
            task_id = task_resp.json()["output"]["task_id"]
            for _ in range(80):
                await asyncio.sleep(2)
                query_resp = await client.get(f"{base_url}/tasks/{task_id}", headers={"Authorization": f"Bearer {ASR_API_KEY}"})
                query_resp.raise_for_status()
                output = query_resp.json().get("output", {})
                status = output.get("task_status")
                if status == "SUCCEEDED":
                    transcript = ""
                    for item in output.get("results") or []:
                        transcription_url = item.get("transcription_url") or (item.get("output") or {}).get("transcription_url")
                        if transcription_url:
                            resp = await client.get(transcription_url)
                            resp.raise_for_status()
                            data = resp.json()
                            transcript = "".join(segment.get("text", "") for segment in data.get("transcripts", []))
                            break
                    return {
                        "provider": "dashscope_paraformer",
                        "mode": "api",
                        "duration_seconds": duration_seconds,
                        "chunk_seconds": chunk_seconds,
                        "chunk_count": chunk_count,
                        "transcript": transcript,
                        "confidence": 0.9,
                    }
                if status in {"FAILED", "CANCELED"}:
                    return {
                        "provider": "asr",
                        "mode": "fallback",
                        "duration_seconds": duration_seconds,
                        "chunk_seconds": chunk_seconds,
                        "chunk_count": chunk_count,
                        "transcript": f"ASR 转写失败，已保留音轨：{file_name}",
                        "confidence": 0.5,
                        "error": output.get("message") or status,
                    }
        return {
            "provider": "asr",
            "mode": "fallback",
            "duration_seconds": duration_seconds,
            "chunk_seconds": chunk_seconds,
            "chunk_count": chunk_count,
            "transcript": f"ASR 转写超时，已保留音轨：{file_name}",
            "confidence": 0.5,
            "error": "转写超时",
        }
    except Exception as exc:
        return {
            "provider": "asr",
            "mode": "fallback",
            "duration_seconds": duration_seconds,
            "chunk_seconds": chunk_seconds,
            "chunk_count": chunk_count,
            "transcript": f"ASR 调用失败，已保留音轨：{file_name}",
            "confidence": 0.5,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def summarize_multimodal(
    video_name: str,
    transcript: str,
    objects: list[dict[str, Any]],
    key_frames: list[dict[str, Any]],
    visual_frames: list[dict[str, Any]],
    duration_seconds: float,
) -> dict[str, Any]:
    fallback = build_rule_summary(objects, key_frames, transcript)
    if not QWEN_VL_API_URL or not QWEN_VL_API_KEY:
        return {"provider": "rule", "mode": "fallback", **fallback}

    selected_frames = visual_frames[:6]
    visual_source = "yolo_key_frames" if key_frames else "sampled_frames"
    frame_timestamps = [f.get("timestamp_text") or f"{i*3:02d}:00" for i, f in enumerate(selected_frames)]
    prompt = (
        "你是法律视频证据分析助手。请基于视频抽帧画面、YOLO 识别对象和音轨转写，"
        "输出严格 JSON，字段包含 summary、proof_purpose、key_events、risk_notes、need_confirm、confidence。\n"
        "输出要求：\n"
        "1. summary：用一段中文概括整个视频发生了什么（人物、动作、事件、场景），不要用'画面出现…'这种模板；\n"
        "2. key_events：按时间顺序输出 3-8 个关键事件，每一项必须是对象 {\"time\": \"00:00:06\", \"event\": \"具体行为描述\", \"evidence_value\": \"可证明的事实\"}，"
        "event 描述画面中人物在做什么动作/正在发生什么，不要说'画面出现XX'，time 从给出的时间戳序列中选择最接近的；\n"
        "3. proof_purpose：这段视频能证明什么事实。\n"
        f"\n视频名称：{video_name}\n视频时长估计：{duration_seconds} 秒\n"
        f"送入画面按顺序对应的时间戳：{json.dumps(frame_timestamps, ensure_ascii=False)}\n"
        f"YOLO 对象：{json.dumps(objects, ensure_ascii=False)}\n"
        f"音轨转写：{transcript or '（未获得转写）'}\n"
        f"YOLO 关键帧数量：{len(key_frames)}，本次送入视觉模型帧数：{len(selected_frames)}，"
        f"视觉帧来源：{visual_source}。如果 YOLO 对象为空，也必须直接根据附带画面描述视频内容。"
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "你只输出 JSON，不要输出 markdown 或解释文字。"},
    ]
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for frame in selected_frames:
        try:
            frame_bytes = Path(frame["frame_path"]).read_bytes()
            frame_b64 = base64.b64encode(frame_bytes).decode("utf-8")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"}})
        except Exception:
            continue
    messages.append({"role": "user", "content": content})

    try:
        async with httpx.AsyncClient(timeout=240) as client:
            response = await client.post(
                f"{QWEN_VL_API_URL}/chat/completions",
                headers={"Authorization": f"Bearer {QWEN_VL_API_KEY}", "Content-Type": "application/json"},
                json={"model": QWEN_VL_MODEL, "messages": messages, "temperature": 0.1, "max_tokens": 1200},
            )
        response.raise_for_status()
        data = response.json()
        content_text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        parsed = parse_json_text(content_text)
        if not parsed:
            parsed = {"summary": content_text.strip() or fallback["summary"]}
        return {
            "provider": "qwen_vl",
            "mode": "api",
            "visual_source": visual_source,
            "summary": parsed.get("summary") or fallback["summary"],
            "proof_purpose": parsed.get("proof_purpose") or fallback["proof_purpose"],
            "key_events": parsed.get("key_events") or fallback["key_events"],
            "risk_notes": parsed.get("risk_notes") or fallback["risk_notes"],
            "need_confirm": parsed.get("need_confirm") or fallback["need_confirm"],
            "confidence": parsed.get("confidence", 0.82),
            "raw": data,
        }
    except Exception as exc:
        return {"provider": "rule", "mode": "fallback", "visual_source": visual_source, **fallback, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/health")
def health():
    vl_configured = bool(QWEN_VL_API_URL and QWEN_VL_API_KEY)
    asr_configured = bool(ASR_API_URL and ASR_API_KEY)
    return {
        "status": "healthy",
        "model_available": YOLO is not None,
        "vl_configured": vl_configured,
        "asr_configured": asr_configured,
        # degraded=True 时视频 summary 会静默回退为规则模板，需检查启动环境变量
        "degraded": not vl_configured,
    }


@app.post("/analyze-video")
async def analyze_video(
    file: UploadFile = File(...),
    frame_interval_seconds: int = Form(3),
    duration_seconds: float = Form(300),
    model_path: str = Form(DEFAULT_MODEL),
):
    request_id = uuid4().hex
    output_dir = OUTPUT_DIR / request_id
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    video_path = Path(tempfile.gettempdir()) / f"{request_id}{suffix}"
    with video_path.open("wb") as target:
        shutil.copyfileobj(file.file, target)

    audio_path = extract_audio_track(video_path, output_dir)
    frames = sample_frames(video_path, frame_interval_seconds, output_dir / "frames")
    objects, key_frames = detect_frames(frames, model_path)
    visual_frames = select_visual_frames(frames, key_frames)
    transcript_result = await transcribe_audio(audio_path, file.filename or video_path.name, duration_seconds) if audio_path else {
        "provider": "asr",
        "mode": "fallback",
        "duration_seconds": duration_seconds,
        "chunk_seconds": ASR_MAX_CHUNK_SECONDS,
        "chunk_count": 1,
        "transcript": "未提取到音轨，跳过音频转写。",
        "confidence": 0.5,
        "error": "no_audio_track",
    }
    transcript = transcript_result.get("transcript", "")
    summary = await summarize_multimodal(file.filename or video_path.name, transcript, objects, key_frames, visual_frames, duration_seconds)

    return {
        "duration_seconds": duration_seconds,
        "frame_interval_seconds": frame_interval_seconds,
        "sampled_frames": len(frames),
        "audio_extracted": audio_path is not None,
        "audio_path": str(audio_path) if audio_path else None,
        "audio_transcript": transcript,
        "audio_transcript_result": transcript_result,
        "objects": objects,
        "key_frames": key_frames,
        "visual_frames": [
            {
                "index": frame.get("index"),
                "frame_no": frame.get("frame_no"),
                "timestamp": frame.get("timestamp"),
                "timestamp_text": frame.get("timestamp_text"),
                "frame_path": frame.get("frame_path"),
            }
            for frame in visual_frames
        ],
        **summary,
        "confidence": summary.get("confidence", 0.82 if objects else 0.5),
    }
