from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
import base64
import hashlib
import json
import shutil

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings

# 图片(物体类)识别 prompt：让 QWEN-VL 直接输出一句话凝练摘要，禁止 ###/分点清单
ONE_LINE_IMG_PROMPT = (
    "这是一张诉讼证据图片。请用严格 JSON 输出（不要其他文字、不要markdown代码块）: "
    "{\"summary\": \"一句话（30-90字）概括该图证明的核心事实\", "
    "\"detailed\": \"100-220字详细描述：画面中的人物/物体/动作/场景/可见文字/时间地点线索/证据意义，分句即可不要分点\", "
    "\"key_info\": {\"人物\": [\"画面/文字中出现的人物\"], \"物品\": [\"关键物品\"], \"动作\": [\"发生的动作\"], \"时间地点\": [\"可见的时间地点线索\"], \"可见文字\": [\"图中可辨认的文字内容\"]}}。"
    "key_info 各列表按图中实际内容填写，没有的留空数组，但至少一个列表非空。"
)


def _parse_vl_json(text: str) -> tuple[str, str, dict]:
    """尝试从 QWEN-VL 文本里抽出 JSON {summary, detailed, key_info}，失败则 (整段, 空, {})。"""
    import re
    if not text:
        return ("", "", {})

    def _take(obj) -> tuple[str, str, dict] | None:
        if isinstance(obj, dict) and "summary" in obj:
            ki = obj.get("key_info")
            ki = ki if isinstance(ki, dict) else {}
            # 过滤掉空列表，只保留有内容的键
            ki = {k: v for k, v in ki.items() if v}
            return (str(obj.get("summary", "")).strip(), str(obj.get("detailed", "")).strip(), ki)
        return None

    # 预处理：剥掉 ```json / ``` 围栏
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    # 先尝试直接 parse
    try:
        import json
        taken = _take(json.loads(candidate))
        if taken:
            return taken
    except Exception:
        pass
    # 兜底：贪婪匹配最外层大括号（key_info 是嵌套对象，不能用非贪婪）
    m = re.search(r"\{[\s\S]*\}", candidate)
    if m:
        try:
            import json
            taken = _take(json.loads(m.group(0)))
            if taken:
                return taken
        except Exception:
            pass
    # 截断兜底：模型输出超 max_tokens 导致 JSON 不完整时，正则抽取 summary/detailed，
    # 保证 summary 字段不被原始 JSON 文本污染（key_info 此时不可靠，返回空）
    def _field(name: str) -> str:
        fm = re.search(rf'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)"', candidate)
        if not fm:
            return ""
        try:
            import json
            return str(json.loads(f'"{fm.group(1)}"')).strip()
        except Exception:
            return fm.group(1).strip()

    s, d = _field("summary"), _field("detailed")
    if s:
        return (s, d, {})
    return (text.strip(), "", {})


from app.models.litigation import (
    CaseIntakeDraft,
    LitigationIntake,
    LitigationMaterial,
    MaterialAnalysisResult,
    MaterialConfirmationBlock,
)
from app.models.user import User
from app.schemas.litigation_intake import (
    CaseDraftUpdateRequest,
    IntakeCreateRequest,
    MaterialBatchCreateRequest,
)


class LitigationIntakeService:
    def __init__(self, db: Session):
        self.db = db

    def generate_intake_id(self) -> str:
        prefix = datetime.now().strftime("INTAKE-%Y%m%d-")
        try:
            last = (
                self.db.query(LitigationIntake)
                .filter(LitigationIntake.intake_id.like(f"{prefix}%"))
                .order_by(LitigationIntake.intake_id.desc())
                .first()
            )
            next_number = int(last.intake_id[-4:]) + 1 if last else 1
        except Exception:
            next_number = int(datetime.now().strftime("%H%M%S"))
        return f"{prefix}{next_number:04d}"

    def generate_material_id(self) -> str:
        prefix = datetime.now().strftime("MAT-%Y%m%d-")
        return f"{prefix}{uuid4().hex[:12].upper()}"

    def generate_analysis_id(self) -> str:
        prefix = datetime.now().strftime("ANL-%Y%m%d-")
        return f"{prefix}{uuid4().hex[:12].upper()}"

    def generate_block_id(self) -> str:
        return f"BLK-{uuid4().hex[:12].upper()}"

    def generate_draft_id(self) -> str:
        prefix = datetime.now().strftime("DRAFT-%Y%m%d-")
        last = (
            self.db.query(CaseIntakeDraft)
            .filter(CaseIntakeDraft.draft_id.like(f"{prefix}%"))
            .order_by(CaseIntakeDraft.draft_id.desc())
            .first()
        )
        next_number = int(last.draft_id[-4:]) + 1 if last else 1
        return f"{prefix}{next_number:04d}"

    def create_intake(self, request: IntakeCreateRequest, user: User) -> LitigationIntake:
        intake = LitigationIntake(
            intake_id=self.generate_intake_id(),
            source=request.source,
            case_type=request.case_type,
            customer_name=request.customer_name,
            opposite_party=request.opposite_party,
            status="uploading",
            created_by=user.id,
        )
        self.db.add(intake)
        self.db.commit()
        self.db.refresh(intake)
        return intake

    def get_intake(self, intake_id: str) -> Optional[LitigationIntake]:
        return self.db.query(LitigationIntake).filter(LitigationIntake.intake_id == intake_id).first()

    def detect_file_type(self, file_name: str, content_type: Optional[str]) -> str:
        content_type = content_type or ""
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if content_type.startswith("image/") or ext in {"jpg", "jpeg", "png", "webp", "bmp"}:
            return "image"
        if content_type.startswith("audio/") or ext in {"mp3", "wav", "m4a", "aac", "ogg"}:
            return "audio"
        if content_type.startswith("video/") or ext in {"mp4", "mov", "avi", "mkv", "webm"}:
            return "video"
        return "document"

    @staticmethod
    def _sha256_bytes(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _try_load_json(text: str) -> Dict[str, Any]:
        candidate = (text or "").strip()
        if not candidate:
            return {}
        fenced = candidate
        if fenced.startswith("```"):
            fenced = fenced.strip("`")
            if fenced.startswith("json"):
                fenced = fenced[4:].strip()
            candidate = fenced
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

    def _image_signature(self, content: bytes) -> str:
        sample = content[:4096]
        return hashlib.sha256(sample).hexdigest()

    def _looks_like_blank_or_scenery(self, content: bytes, file_name: str) -> bool:
        name = (file_name or "").lower()
        if any(token in name for token in ("风景", "scape", "landscape", "empty", "blank")):
            return True
        signature = self._image_signature(content)
        return signature.startswith("000") or signature.endswith("000")

    async def _classify_image(self, path: Path, file_name: str, mime: str) -> Dict[str, Any]:
        from app.services.ai_service import AIService

        ai = AIService()
        image_bytes = path.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "请判断这张法律证据图片更偏向哪一类，只返回 JSON："
            '{"category":"text|object","confidence":0-1,"reason":"简短原因"}。'
            "如果图片主要是文字、截图、票据、合同扫描件、聊天记录，返回 text；"
            "如果主要是实物、现场、人物、车辆、货物、环境，返回 object。"
        )
        result = ai.describe_image(image_b64, prompt, mime or "image/jpeg")
        if not result.get("success"):
            return {"category": "object", "confidence": 0.5, "reason": result.get("error", "分类失败")}
        parsed = self._try_load_json(result.get("description", ""))
        category = parsed.get("category") if parsed.get("category") in {"text", "object"} else None
        confidence = parsed.get("confidence") if isinstance(parsed.get("confidence"), (int, float)) else 0.6
        reason = parsed.get("reason") or result.get("description", "")[:120]
        if not category:
            text = (result.get("description") or "").lower()
            if any(token in text for token in ("文字", "合同", "截图", "票据", "扫描件", "聊天", "表格", "文档")):
                category = "text"
            else:
                category = "object"
        return {"category": category, "confidence": float(confidence), "reason": reason}

    @staticmethod
    def _estimate_video_duration(path: Path) -> float:
        import subprocess

        if shutil.which("ffprobe") is None:
            return 300.0
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        try:
            output = subprocess.check_output(command, stderr=subprocess.DEVNULL, text=True).strip()
            return float(output) if output else 300.0
        except Exception:
            return 300.0

    async def _analyze_video_file(self, path: Path, file_name: str) -> Dict[str, Any]:
        from app.mcps.servers.yolo_server import YoloServer

        yolo = YoloServer()
        duration_seconds = self._estimate_video_duration(path)
        return await yolo._analyze_video(str(path), file_name, duration_seconds)

    async def _summarize_video_with_vl(
        self,
        yolo_result: Dict[str, Any],
        video_path: Path,
        file_name: str,
        ai,
    ) -> Dict[str, Any]:
        """把 YOLO 的关键帧 + 对象统计 → 喂 Qwen-VL(qwen3.8-27b) 做二次语义摘要。

        输入是 YoloServer._analyze_video 的返回，输出叠加 Qwen-VL 真实叙事 + 证据等级。
        修复点：之前 video 分支只回保底 summary（"视频中出现人员活动"）→ 现在出真实内容。
        """
        import base64
        import logging

        logger = logging.getLogger(__name__)

        # 1) 拼 YOLO 对象统计文本（喂给 Qwen-VL 当上下文）
        objects = yolo_result.get("objects") or []
        obj_lines = []
        for obj in objects:
            label = obj.get("label_cn") or obj.get("label") or "对象"
            count = obj.get("count", 0)
            conf = obj.get("confidence", 0.0)
            obj_lines.append(f"- {label} ×{count}（置信度 {conf:.2f}）")
        yolo_summary = "YOLO 检测到的对象分布：\n" + "\n".join(obj_lines) if obj_lines else ""

        # 2) 取关键帧（最多 6 张）拼 base64
        key_frames = yolo_result.get("key_frames") or []
        frames_base64: list[str] = []
        # YOLO 服务 cwd 是 ../../yolo-video-service/，frame_path 是绝对字符串（含 \）
        # 在主后端 cwd=backend/ 下需要把相对路径拆出来再拼到 yolo-video-service 根
        yolo_service_root = Path(__file__).resolve().parent.parent.parent.parent / "yolo-video-service"
        for kf in key_frames[:6]:
            fp_str = kf.get("frame_path") or ""
            if not fp_str:
                continue
            # 兼容 \\ 和 /，统一分隔符
            fp_clean = fp_str.replace("\\", "/")
            # 如果含 outputs/ 但不是绝对路径，拼到 yolo-video-service 根
            if "outputs/" in fp_clean and not Path(fp_clean).is_absolute():
                abs_path = yolo_service_root / fp_clean
            else:
                abs_path = Path(fp_clean)
            if not abs_path.exists():
                # 兜底：在 cwd 下找
                alt = Path.cwd() / fp_clean
                if alt.exists():
                    abs_path = alt
                else:
                    logger.warning(f"视频关键帧不存在: {abs_path}")
                    continue
            try:
                frames_base64.append(base64.b64encode(abs_path.read_bytes()).decode("utf-8"))
            except Exception as exc:
                logger.warning(f"读取视频关键帧失败 {abs_path}: {exc}")

        # 3) 调 Qwen-VL 二次摘要
        if frames_base64:
            vl_result = ai.describe_video_frames(frames_base64, yolo_summary, file_name, max_frames=6)
            if vl_result.get("ok"):
                data = vl_result["data"]
                # 4) 合并到 parsed（保留 YOLO 抽帧结构 + 替换 summary 类）
                merged = dict(yolo_result)
                merged["provider"] = "yolo+qwen_vl"
                merged["mode"] = "api"
                merged["vl_objects_context"] = yolo_summary
                merged["vl_input_frames"] = len(frames_base64)
                merged["summary"] = data.get("summary") or merged.get("summary", "")
                merged["detailed"] = data.get("detailed") or ""
                merged["key_info"] = data.get("key_info") if isinstance(data.get("key_info"), dict) else merged.get("key_info", {})
                merged["proof_purpose"] = data.get("proof_purpose") or merged.get("proof_purpose", "")
                merged["risk_notes"] = data.get("risk_notes") if isinstance(data.get("risk_notes"), list) else merged.get("risk_notes", [])
                merged["need_confirm"] = data.get("need_confirm") if isinstance(data.get("need_confirm"), list) else merged.get("need_confirm", [])
                # evidence_level 之前根本没在这层填，现在补上
                level = (data.get("evidence_level") or "").strip().upper()
                level_map = {"A": "A", "B": "B", "C": "C", "高": "A", "中": "B", "低": "C"}
                merged["evidence_level"] = level_map.get(level, "C")
                merged["useful"] = merged.get("useful")
                return merged
            else:
                logger.warning(f"Qwen-VL 视频摘要失败: {vl_result.get('error')}，回退到 YOLO 保底结果")
                # 失败时给 evidence_level 兜底
                yolo_result["evidence_level"] = "C"
                yolo_result["vl_objects_context"] = yolo_summary
                yolo_result["vl_input_frames"] = len(frames_base64)
                return yolo_result
        else:
            # 没有抽到帧，YOLO fallback
            logger.warning(f"video={file_name} 未抽到关键帧，跳过 Qwen-VL 二次摘要")
            yolo_result["evidence_level"] = "C"
            yolo_result["vl_objects_context"] = yolo_summary
            yolo_result["vl_input_frames"] = 0
            return yolo_result

    async def save_uploaded_files(self, intake: LitigationIntake, files: List[UploadFile]) -> List[LitigationMaterial]:
        saved = []
        base_dir = Path(settings.UPLOAD_DIR) / "litigation" / intake.intake_id
        base_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        seen_hashes: set[str] = set(
            row[0]
            for row in self.db.query(LitigationMaterial.file_hash)
            .filter(LitigationMaterial.intake_id == intake.id, LitigationMaterial.file_hash.isnot(None))
            .all()
        )
        for file in files:
            content = await file.read()
            if len(content) > max_bytes:
                raise ValueError(f"文件超过大小限制: {file.filename}")
            file_hash = self._sha256_bytes(content)
            if file_hash in seen_hashes:
                continue
            seen_hashes.add(file_hash)
            material_id = self.generate_material_id()
            safe_name = Path(file.filename or f"{material_id}.bin").name
            file_dir = base_dir / material_id
            file_dir.mkdir(parents=True, exist_ok=True)
            file_path = file_dir / f"{uuid4().hex}_{safe_name}"
            file_path.write_bytes(content)
            file_type = self.detect_file_type(safe_name, file.content_type)
            material = LitigationMaterial(
                material_id=material_id,
                intake_id=intake.id,
                file_name=safe_name,
                file_type=file_type,
                mime_type=file.content_type,
                file_size=len(content),
                file_path=str(file_path),
                file_hash=file_hash,
                analysis_status="uploaded",
                confirm_status="pending",
            )
            self.db.add(material)
            self.db.flush()
            if file_type == "image":
                if self._looks_like_blank_or_scenery(content, safe_name):
                    material.analysis_status = "rejected"
                    self.db.add(MaterialAnalysisResult(
                        analysis_id=self.generate_analysis_id(),
                        material_id=material.id,
                        agent_name="evidence_precheck",
                        analysis_type="image_filter",
                        raw_text="图片被判定为疑似风景/空白/无关图，已过滤",
                        structured_result={"category": "filtered", "reason": "blank_or_scenery"},
                        confidence=0.95,
                        status="filtered",
                    ))
                else:
                    classify_result = await self._classify_image(file_path, safe_name, file.content_type or "image/jpeg")
                    material.analysis_status = f"image_{classify_result['category']}"
                    self.db.add(MaterialAnalysisResult(
                        analysis_id=self.generate_analysis_id(),
                        material_id=material.id,
                        agent_name="evidence_precheck",
                        analysis_type="image_classification",
                        raw_text=classify_result.get("reason", ""),
                        structured_result=classify_result,
                        confidence=classify_result.get("confidence", 0.6),
                        status="success",
                    ))
            saved.append(material)
        intake.status = "uploaded"
        self.db.commit()
        for material in saved:
            self.db.refresh(material)
        return saved

    async def analyze_materials(self, intake: LitigationIntake) -> Dict[str, Any]:
        """对受理单内未分析的材料按类型调用真实 AI（规则流，不套 Agent）。

        - 图片：统一走 Qwen 多模态，先判断 text / object，再直接抽取结构化结果
        - 音频：ASR 转写（DashScope paraformer）→ Qwen 抽取
        - 视频：当前不处理（保留待处理确认块）
        - 其他文档：统一走 Qwen 多模态抽取
        结果写入 MaterialAnalysisResult + MaterialConfirmationBlock，供前端确认页展示/编辑。
        """
        import base64
        import logging

        logger = logging.getLogger(__name__)
        from app.services.ai_service import AIService
        from app.mcps.servers.asr_server import ASRServer
        from app.mcps.servers.qwen_server import QwenServer

        ai = AIService()
        asr_server = ASRServer()
        qwen = QwenServer()
        analyzed = []

        for material in intake.materials:
            if material.analysis_status in {"analyzed", "pending_confirm", "confirmed", "rejected"}:
                continue
            path = Path(material.file_path)
            if not path.exists():
                analyzed.append({"material_id": material.material_id, "file_name": material.file_name, "status": "error", "error": "文件不存在"})
                continue
            try:
                if material.file_type == "image":
                    image_class = next((r.structured_result for r in material.analysis_results if r.analysis_type == "image_classification"), None)
                    category = (image_class or {}).get("category") or "object"
                    if category == "object":
                        # 物体类图片识别效果不佳：跳过 AI 识别，直接归入物体图片待律师确认
                        parsed = {
                            "provider": "none",
                            "mode": "skipped_object",
                            "document_type": "image",
                            "summary": "物体类图片，系统未做 AI 识别，待律师确认并补充说明",
                            "key_info": {"人物": [], "机构/地点": [], "金额": [], "日期时间": [], "可见文字/关键承诺": []},
                            "proof_purpose": "证明图片所反映的现场、实物或画面内容",
                            "risk_notes": ["物体类图片 AI 识别置信度低，已跳过自动识别，由律师人工判断", "图片无法单独证明拍摄时间地点，需结合原始属性或证人说明"],
                            "need_confirm": ["画面内容与本案的关联性", "拍摄时间与地点", "请律师补充图片关键信息与证明目的"],
                            "useful": None,
                            "evidence_level": "C",
                            "classification": {"category": "object"},
                            "visual_description": "",
                        }
                    else:
                        b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
                        prompt = (
                            "这是一张法律证据图片（偏文字类）。请用严格 JSON 输出："
                            '{"summary":"一句话概括该图证明的核心事实","detailed":"100-220字详细描述：可见文字、关键信息、证据意义、人物/物体/动作/场景，分句即可不要分点",'
                            '"key_info":{"人物":[],"机构/地点":[],"金额":[],"日期时间":[],"可见文字/关键承诺":[]}}，'
                            "key_info 各列表按图中实际内容填写，没有的留空数组，但至少一个列表非空。"
                        )
                        desc = ai.describe_image(b64, prompt, material.mime_type or "image/jpeg")
                        visual = (desc.get("description") or "").strip()
                        one_line_summary, detailed, vl_key_info = _parse_vl_json(visual)
                        if not detailed or detailed == one_line_summary:
                            detailed = visual
                        parsed = {
                            "provider": "qwen_vl",
                            "mode": "api",
                            "document_type": "image",
                            "summary": one_line_summary,
                            "key_info": vl_key_info,
                            "proof_purpose": "证明图片所反映的现场、实物或画面内容",
                            "risk_notes": ["图片无法单独证明拍摄时间地点，需结合原始属性或证人说明"],
                            "need_confirm": ["画面内容与本案的关联性", "拍摄时间与地点"],
                            "useful": None,
                            "evidence_level": "C",
                            "classification": {"category": category},
                            "visual_description": detailed or visual,
                        }
                elif material.file_type == "audio":
                    trans = await asr_server._transcribe_audio(str(path), material.file_name)
                    text = trans.get("transcript") or ""
                    parsed = await qwen._extract_key_info("audio", text, {"file_name": material.file_name})
                    # 保留 ASR 原始转写（前端音频卡片"查看转写全文"用）+ 关键时间戳块
                    segments = trans.get("segments") or []
                    parsed = {
                        **parsed,
                        "transcript": text,
                        "audio_transcript": text,
                        "asr_provider": trans.get("provider"),
                        "asr_confidence": trans.get("confidence"),
                        "asr_duration_seconds": trans.get("duration_seconds"),
                        "asr_segments": segments,
                        "asr_key_info": trans.get("key_info") or {},
                    }
                    # ASR 返回 segments 为空时，按标点切分给前端"关键时间点"用（无真实时间戳但给段落分隔）
                    if not segments and text:
                        chunks = [c.strip() for c in text.replace("\n", "。").split("。") if c.strip()]
                        parsed["key_events"] = [
                            {"time": f"段落{i+1}", "event": c[:80] + ("..." if len(c) > 80 else "")}
                            for i, c in enumerate(chunks[:6])
                        ]
                elif material.file_type == "video":
                    parsed = await self._analyze_video_file(path, material.file_name)
                    # 二次语义摘要：把 YOLO 抽到的关键帧 + 对象统计 → 喂 Qwen-VL(qwen3.8-27b)
                    # 修复之前 video 分支只回保底模板 summary 的问题
                    parsed = await self._summarize_video_with_vl(parsed, path, material.file_name, ai)
                else:
                    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
                    desc = ai.describe_image(b64, "请将这份法律证据材料按严格 JSON 解析，输出 summary、detailed、key_info、proof_purpose、risk_notes、need_confirm、useful、evidence_level。", material.mime_type or "application/octet-stream")
                    visual = (desc.get("description") or "").strip()
                    summary, detailed = _parse_vl_json(visual)
                    if not detailed or detailed == summary:
                        detailed = visual
                    parsed = {
                        "provider": "qwen_vl",
                        "mode": "api",
                        "document_type": material.file_type,
                        "summary": summary,
                        "key_info": {},
                        "proof_purpose": "证明材料所反映的事实或权利义务关系",
                        "risk_notes": ["文档类材料需结合原始文件属性和上下文确认"],
                        "need_confirm": ["文字内容是否完整", "材料与案件的关联性"],
                        "useful": None,
                        "evidence_level": "C",
                        "visual_description": detailed or visual,
                    }

                result_block = dict(parsed)
                result_block["file_name"] = material.file_name
                result_block["material_id"] = material.material_id
                self.db.add(MaterialAnalysisResult(
                    analysis_id=self.generate_analysis_id(),
                    material_id=material.id,
                    agent_name="evidence_rules",
                    analysis_type="material_analysis",
                    raw_text=result_block.get("summary", ""),
                    structured_result=result_block,
                    confidence=0.85,
                    status="success",
                ))
                self.db.add(MaterialConfirmationBlock(
                    block_id=self.generate_block_id(),
                    material_id=material.id,
                    block_type=material.file_type,
                    title=material.file_name,
                    ai_result=result_block,
                    status="pending",
                ))
                material.analysis_status = "pending_confirm"
                analyzed.append({
                    "material_id": material.material_id,
                    "file_name": material.file_name,
                    "file_type": material.file_type,
                    "status": "ok",
                    "summary": str(result_block.get("summary", ""))[:80],
                    "useful": result_block.get("useful"),
                    "evidence_level": result_block.get("evidence_level"),
                    "classification": result_block.get("classification"),
                })
            except Exception as exc:
                logger.error(f"材料分析失败 {material.file_name}: {exc}")
                analyzed.append({"material_id": material.material_id, "file_name": material.file_name, "status": "error", "error": str(exc)})

        if intake.materials:
            intake.status = "pending_confirm"
        self.db.commit()
        return {"status": "ok", "analyzed": analyzed, "detail": self.to_detail(intake)}

    async def analyze_one_material(self, intake: LitigationIntake, material: LitigationMaterial) -> Dict[str, Any]:
        """对单个材料调用 AI（图片统一 Qwen 多模态分 text/object 抽取 / 音频 ASR+Qwen / 视频 YOLO+Qwen-VL）。
        供前端逐文件进度条调用。与 analyze_materials 同构，不使用 MinerU。"""
        import base64
        import logging

        logger = logging.getLogger(__name__)
        from app.services.ai_service import AIService
        from app.mcps.servers.asr_server import ASRServer
        from app.mcps.servers.qwen_server import QwenServer

        if material.analysis_status in {"analyzed", "pending_confirm", "confirmed", "rejected"}:
            return {"material_id": material.material_id, "file_name": material.file_name, "status": "skipped"}

        ai = AIService()
        asr_server = ASRServer()
        qwen = QwenServer()
        path = Path(material.file_path)
        if not path.exists():
            return {"material_id": material.material_id, "file_name": material.file_name, "status": "error", "error": "文件不存在"}

        try:
            if material.file_type == "image":
                image_class = next((r.structured_result for r in material.analysis_results if r.analysis_type == "image_classification"), None)
                category = (image_class or {}).get("category") or "object"
                if category == "object":
                    # 物体类图片识别效果不佳：跳过 AI 识别，直接归入物体图片待律师确认
                    parsed = {
                        "provider": "none",
                        "mode": "skipped_object",
                        "document_type": "image",
                        "summary": "物体类图片，系统未做 AI 识别，待律师确认并补充说明",
                        "key_info": {"人物": [], "机构/地点": [], "金额": [], "日期时间": [], "可见文字/关键承诺": []},
                        "proof_purpose": "证明图片所反映的现场、实物或画面内容",
                        "risk_notes": ["物体类图片 AI 识别置信度低，已跳过自动识别，由律师人工判断", "图片无法单独证明拍摄时间地点，需结合原始属性或证人说明"],
                        "need_confirm": ["画面内容与本案的关联性", "拍摄时间与地点", "请律师补充图片关键信息与证明目的"],
                        "useful": None,
                        "evidence_level": "C",
                        "classification": {"category": "object"},
                        "visual_description": "",
                    }
                else:
                    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
                    prompt = (
                        "这是一张法律证据图片（偏文字类）。请用严格 JSON 输出："
                        '{"summary":"一句话概括该图证明的核心事实","detailed":"100-220字详细描述：可见文字、关键信息、证据意义、人物/物体/动作/场景，分句即可不要分点",'
                        '"key_info":{"人物":[],"机构/地点":[],"金额":[],"日期时间":[],"可见文字/关键承诺":[]}}，'
                        "key_info 各列表按图中实际内容填写，没有的留空数组，但至少一个列表非空。"
                    )
                    desc = ai.describe_image(b64, prompt, material.mime_type or "image/jpeg")
                    visual = (desc.get("description") or "").strip()
                    one_line_summary, detailed, vl_key_info = _parse_vl_json(visual)
                    if not detailed or detailed == one_line_summary:
                        detailed = visual
                    parsed = {
                        "provider": "qwen_vl",
                        "mode": "api",
                        "document_type": "image",
                        "summary": one_line_summary,
                        "key_info": vl_key_info,
                        "proof_purpose": "证明图片所反映的现场、实物或画面内容",
                        "risk_notes": ["图片无法单独证明拍摄时间地点，需结合原始属性或证人说明"],
                        "need_confirm": ["画面内容与本案的关联性", "拍摄时间与地点"],
                        "useful": None,
                        "evidence_level": "C",
                        "classification": {"category": category},
                        "visual_description": detailed or visual,
                    }
            elif material.file_type == "audio":
                trans = await asr_server._transcribe_audio(str(path), material.file_name)
                text = trans.get("transcript") or ""
                parsed = await qwen._extract_key_info("audio", text, {"file_name": material.file_name})
                segments = trans.get("segments") or []
                parsed = {
                    **parsed,
                    "transcript": text,
                    "audio_transcript": text,
                    "asr_provider": trans.get("provider"),
                    "asr_confidence": trans.get("confidence"),
                    "asr_duration_seconds": trans.get("duration_seconds"),
                    "asr_segments": segments,
                    "asr_key_info": trans.get("key_info") or {},
                }
                if not segments and text:
                    chunks = [c.strip() for c in text.replace("\n", "。").split("。") if c.strip()]
                    parsed["key_events"] = [
                        {"time": f"段落{i+1}", "event": c[:80] + ("..." if len(c) > 80 else "")}
                        for i, c in enumerate(chunks[:6])
                    ]
            elif material.file_type == "video":
                parsed = await self._analyze_video_file(path, material.file_name)
                # 二次语义摘要：把 YOLO 抽到的关键帧 + 对象统计 → 喂 Qwen-VL(qwen3.8-27b)
                parsed = await self._summarize_video_with_vl(parsed, path, material.file_name, ai)
            else:
                b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
                desc = ai.describe_image(b64, "请将这份法律证据材料按严格 JSON 解析，输出 summary、detailed、key_info、proof_purpose、risk_notes、need_confirm、useful、evidence_level。", material.mime_type or "application/octet-stream")
                visual = (desc.get("description") or "").strip()
                summary, detailed = _parse_vl_json(visual)
                if not detailed or detailed == summary:
                    detailed = visual
                parsed = {
                    "provider": "qwen_vl",
                    "mode": "api",
                    "document_type": material.file_type,
                    "summary": summary,
                    "key_info": {},
                    "proof_purpose": "证明材料所反映的事实或权利义务关系",
                    "risk_notes": ["文档类材料需结合原始文件属性和上下文确认"],
                    "need_confirm": ["文字内容是否完整", "材料与案件的关联性"],
                    "useful": None,
                    "evidence_level": "C",
                    "visual_description": detailed or visual,
                }

            result_block = dict(parsed)
            result_block["file_name"] = material.file_name
            result_block["material_id"] = material.material_id
            self.db.add(MaterialAnalysisResult(
                analysis_id=self.generate_analysis_id(),
                material_id=material.id,
                agent_name="evidence_rules",
                analysis_type="material_analysis",
                raw_text=result_block.get("summary", ""),
                structured_result=result_block,
                confidence=0.85,
                status="success",
            ))
            self.db.add(MaterialConfirmationBlock(
                block_id=self.generate_block_id(),
                material_id=material.id,
                block_type=material.file_type,
                title=material.file_name,
                ai_result=result_block,
                status="pending",
            ))
            material.analysis_status = "pending_confirm"
            self.db.commit()
            return {
                "material_id": material.material_id,
                "file_name": material.file_name,
                "file_type": material.file_type,
                "status": "ok",
                "summary": str(result_block.get("summary", ""))[:80],
                "useful": result_block.get("useful"),
                "evidence_level": result_block.get("evidence_level"),
                "classification": result_block.get("classification"),
            }
        except Exception as exc:
            logger.error(f"材料分析失败 {material.file_name}: {exc}")
            return {"material_id": material.material_id, "file_name": material.file_name, "status": "error", "error": str(exc)}

    def add_materials(self, intake: LitigationIntake, request: MaterialBatchCreateRequest) -> List[LitigationMaterial]:
        materials = []
        for item in request.materials:
            material = LitigationMaterial(
                material_id=self.generate_material_id(),
                intake_id=intake.id,
                file_name=item.file_name,
                file_type=item.file_type,
                mime_type=item.mime_type,
                file_size=item.file_size,
                file_path=item.file_path,
                file_hash=item.file_hash,
                analysis_status="uploaded",
                confirm_status="pending",
            )
            self.db.add(material)
            self.db.flush()
            if item.analysis_text or item.proof_purpose:
                self.db.add(MaterialAnalysisResult(
                    analysis_id=self.generate_analysis_id(),
                    material_id=material.id,
                    agent_name="frontend_upload",
                    analysis_type="initial_summary",
                    raw_text=item.analysis_text,
                    structured_result={"proof_purpose": item.proof_purpose},
                    confidence=0.5,
                    status="success",
                ))
            materials.append(material)
        intake.status = "uploaded"
        self.db.commit()
        for material in materials:
            self.db.refresh(material)
        return materials

    def save_analysis_result(self, intake: LitigationIntake, result: Dict[str, Any]) -> Dict[str, Any]:
        material_map = {item.material_id: item for item in intake.materials}
        for analyzed in result.get("materials", []):
            material_id = analyzed.get("material_id")
            material = material_map.get(material_id)
            if not material:
                material = next((item for item in intake.materials if item.file_name == analyzed.get("file_name")), None)
            if not material:
                continue
            material.analysis_status = "pending_confirm"
            for block in list(material.confirmation_blocks):
                self.db.delete(block)
            self.db.add(MaterialAnalysisResult(
                analysis_id=self.generate_analysis_id(),
                material_id=material.id,
                agent_name="MaterialAnalysisAgent",
                analysis_type="material_analysis",
                raw_text=analyzed.get("analysis_text"),
                structured_result=analyzed,
                confidence=0.72,
                status="success",
            ))
        for block in result.get("confirmation_blocks", []):
            material = material_map.get(block.get("material_id")) or next((item for item in intake.materials if item.file_name in str(block.get("title"))), None)
            if not material:
                continue
            self.db.add(MaterialConfirmationBlock(
                block_id=self.generate_block_id(),
                material_id=material.id,
                block_type=block.get("block_type") or "analysis_text",
                title=block.get("title"),
                ai_result=block.get("ai_result"),
                status=block.get("status") or "pending",
            ))
        intake.status = "pending_confirm"
        self.db.commit()
        return self.to_detail(intake)

    def update_confirmation(self, block_id: str, confirmed_result: Any, status: str, user: User) -> Optional[MaterialConfirmationBlock]:
        block = self.db.query(MaterialConfirmationBlock).filter(MaterialConfirmationBlock.block_id == block_id).first()
        if not block:
            return None
        block.confirmed_result = confirmed_result
        block.status = status
        block.confirmed_by = user.id
        block.confirmed_at = datetime.now()
        if all(item.status in {"confirmed", "edited", "rejected"} for item in block.material.confirmation_blocks):
            block.material.confirm_status = "confirmed"
        self.db.commit()
        self.db.refresh(block)
        return block

    def save_draft(self, intake: LitigationIntake, request: CaseDraftUpdateRequest) -> CaseIntakeDraft:
        draft = CaseIntakeDraft(
            draft_id=self.generate_draft_id(),
            intake_id=intake.id,
            case_title=request.case_title,
            plaintiff=request.plaintiff,
            defendant=request.defendant,
            case_summary=request.case_summary,
            claims=request.claims,
            timeline=request.timeline,
            evidence_catalog=request.evidence_catalog,
            assessment=request.assessment,
            status="pending_archive",
        )
        intake.status = "confirmed"
        self.db.add(draft)
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def build_archive_payload(self, intake: LitigationIntake, case_info: Dict[str, Any], assessment: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        case_info = case_info or {}
        assessment = assessment or {}
        evidence_catalog = []
        materials = []
        for index, material in enumerate(intake.materials, start=1):
            latest = material.analysis_results[-1] if material.analysis_results else None
            structured = latest.structured_result if latest and isinstance(latest.structured_result, dict) else {}
            summary = structured.get("summary") or latest.raw_text if latest else ""
            proof_purpose = structured.get("proof_purpose") or structured.get("evidence_value") or f"证明案件相关事实：{material.file_name}"
            catalog_item = {
                "evidence_no": f"{index:02d}",
                "evidence_name": material.file_name,
                "file_name": material.file_name,
                "source_file": material.file_name,
                "evidence_source": "当事人提交",
                "evidence_type": material.file_type,
                "group_name": material.file_type,
                "proof_purpose": proof_purpose,
                "page_range": "待编页",
                "original_status": "电子原件/上传件",
                "summary": summary,
                "useful": structured.get("useful"),
                "evidence_level": structured.get("evidence_level"),
            }
            evidence_catalog.append(catalog_item)
            materials.append({
                "material_id": material.material_id,
                "file_name": material.file_name,
                "file_type": material.file_type,
                "mime_type": material.mime_type,
                "file_size": material.file_size,
                "file_path": material.file_path,
                "analysis_text": summary,
                "proof_purpose": proof_purpose,
                "source_text": summary,
                "key_info": structured.get("key_facts") or {},
            })

        plaintiff_name = case_info.get("plaintiff") or intake.customer_name or "原告待补充"
        defendant_name = case_info.get("defendant") or intake.opposite_party or "被告待补充"
        case_summary = case_info.get("case_summary") or assessment.get("strategy_summary") or "基于上传材料形成的诉讼案件。"
        cause = assessment.get("cause") if isinstance(assessment.get("cause"), dict) else {}
        jurisdiction = assessment.get("jurisdiction") if isinstance(assessment.get("jurisdiction"), dict) else {}
        strategy_summary = assessment.get("strategy_summary") or "围绕案件事实、证据目录和风险点推进诉讼准备。"
        claims = case_info.get("claims") or ["请求法院依法支持我方诉讼请求", "请求对方承担本案相关费用"]

        context = {
            "case_title": case_info.get("case_title") or f"{plaintiff_name}与{defendant_name}纠纷案",
            "case_summary": case_summary,
            "claims": claims,
            "plaintiff": {"name": plaintiff_name, "entity_type": "person"},
            "defendant": {"name": defendant_name, "entity_type": "person"},
            "evidence_files": materials,
        }
        result = {
            "status": "success",
            "intake": self.to_intake_dict(intake),
            "materials": materials,
            "draft": {
                "case_title": context["case_title"],
                "case_summary": case_summary,
                "claims": claims,
                "timeline": [],
                "evidence_catalog": evidence_catalog,
            },
            "assessment": assessment,
            "cause": {"primary_cause": cause} if cause else {},
            "jurisdiction": jurisdiction,
            "risk": {"level": assessment.get("risk_level"), "points": assessment.get("risk_points") or []},
            "strategy": {
                "case_meta": {
                    "case_title": context["case_title"],
                    "lawyer_role": "原告代理人",
                    "claims": claims,
                    "strong_evidence": [item["evidence_name"] for item in evidence_catalog[:5]],
                },
                "strategy_summary": strategy_summary,
                "cause": {"primary_cause": cause} if cause else {},
                "jurisdiction": jurisdiction,
                "risk": {"level": assessment.get("risk_level"), "points": assessment.get("risk_points") or []},
                "claims": claims,
                "dispute_focus": ["基础法律关系是否成立", "上传材料能否形成完整证据链", "对方责任范围与金额如何确定"],
                "litigation_path": ["补齐证据原件", "完善证据目录", "准备起诉材料", "庭前质证与发问准备"],
                "next_steps": assessment.get("next_steps") or ["补齐缺失证据", "完善证据目录", "进入庭审准备"],
            },
            "cross_examination": [
                {"evidence_name": item["evidence_name"], "opinion": "核对原件、确认来源、说明与待证事实的关联性。"}
                for item in evidence_catalog
            ],
            "judge_questions": [
                {"question": "本案核心法律关系是什么？", "answer": "结合上传材料与当事人陈述，围绕基础交易/侵权事实进行说明。"},
                {"question": "现有证据能证明哪些关键事实？", "answer": "以证据目录为基础，逐项对应证明目的和事实链条。"},
            ],
            "trial_outline": {"focus": "围绕事实成立、责任承担、损失范围进行庭审准备。"},
            "pretrial_package": {"status": "ready", "items": ["证据目录", "诉讼策略书", "庭审发问提纲", "质证提纲", "材料包清单"]},
        }
        return context, result

    def archive_intake(self, intake: LitigationIntake, user: User, case_info: Dict[str, Any], assessment: Dict[str, Any], target_case_id: Optional[str] = None) -> Dict[str, Any]:
        from app.services.litigation_service import LitigationService

        service = LitigationService(self.db)
        context, result = self.build_archive_payload(intake, case_info, assessment)
        if target_case_id:
            # 归档到已有案件小库：材料追加进该案件的证据库，不新建案件
            case = service.get_case_by_public_id(target_case_id)
            if not case:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail=f"目标案件不存在：{target_case_id}")
            service.append_evidence_to_case(case, context.get("evidence_files") or [])
        else:
            case = LitigationService(self.db).create_case_from_result(user.id, context, result)
        intake.archived_case_id = case.id
        intake.status = "archived"
        self.db.commit()
        # 归档 = 受理小库封存：材料固化进 case.evidence_items，证据管理页直读，
        # 不再预生成受理报告/证据目录/策略/庭审准备/庭前材料包等诉讼阶段内容。
        return {
            "status": "success",
            "case_id": case.case_id,
            "case": service.get_case_detail(case.case_id),
            "evidence": service.get_evidence_payload(case.case_id),
        }

    def to_intake_dict(self, intake: LitigationIntake) -> Dict[str, Any]:
        return {
            "id": intake.id,
            "intake_id": intake.intake_id,
            "status": intake.status,
            "source": intake.source,
            "case_type": intake.case_type,
            "customer_name": intake.customer_name,
            "opposite_party": intake.opposite_party,
            "archived_case_id": intake.archived_case_id,
            "created_at": intake.created_at.isoformat() if intake.created_at else None,
        }

    def to_material_dict(self, material: LitigationMaterial) -> Dict[str, Any]:
        latest = material.analysis_results[-1] if material.analysis_results else None
        return {
            "id": material.id,
            "material_id": material.material_id,
            "file_name": material.file_name,
            "evidence_name": material.file_name,
            "file_type": material.file_type,
            "mime_type": material.mime_type,
            "file_size": material.file_size,
            "file_path": material.file_path,
            "analysis_status": material.analysis_status,
            "confirm_status": material.confirm_status,
            "analysis_text": latest.raw_text if latest else None,
            "structured_result": latest.structured_result if latest else None,
        }

    def to_block_dict(self, block: MaterialConfirmationBlock) -> Dict[str, Any]:
        return {
            "id": block.id,
            "block_id": block.block_id,
            "material_id": block.material.material_id if block.material else None,
            "block_type": block.block_type,
            "title": block.title,
            "ai_result": block.ai_result,
            "confirmed_result": block.confirmed_result,
            "status": block.status,
            "confirmed_at": block.confirmed_at.isoformat() if block.confirmed_at else None,
        }

    def to_draft_dict(self, draft: CaseIntakeDraft) -> Dict[str, Any]:
        return {
            "id": draft.id,
            "draft_id": draft.draft_id,
            "case_title": draft.case_title,
            "plaintiff": draft.plaintiff,
            "defendant": draft.defendant,
            "case_summary": draft.case_summary,
            "claims": draft.claims,
            "timeline": draft.timeline,
            "evidence_catalog": draft.evidence_catalog,
            "assessment": draft.assessment,
            "status": draft.status,
        }

    def to_detail(self, intake: LitigationIntake) -> Dict[str, Any]:
        return {
            "intake": self.to_intake_dict(intake),
            "materials": [self.to_material_dict(item) for item in intake.materials],
            "confirmation_blocks": [self.to_block_dict(block) for material in intake.materials for block in material.confirmation_blocks],
            "draft": self.to_draft_dict(intake.drafts[-1]) if intake.drafts else None,
        }

    def assess_acceptance(self, intake: LitigationIntake, case_info: Dict[str, Any]) -> Dict[str, Any]:
        """受理后分析：基于已确认材料摘要 + 案件信息，用 DeepSeek 生成专业结论。"""
        from app.services.ai_service import AIService
        case_info = self._merge_intake_case_info(intake, case_info)
        materials_summary = self._build_materials_summary(intake)
        ai = AIService()
        result = ai.assess_case_acceptance(case_info, materials_summary)
        if result.get("success"):
            return result
        return self._rule_assess_acceptance(intake, case_info, result.get("error"))

    def _merge_intake_case_info(
        self, intake: LitigationIntake, case_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """用受理单已落库的信息补齐 case_info。

        请求体传入的值优先；受理阶段录入的客户/对方/案件类型等，
        若不回填，模型会收到一份空白案件，输出「当事人信息缺失」之类无效结论。
        """
        merged = dict(case_info or {})

        def fill(key: str, value: Any) -> None:
            if value and not merged.get(key):
                merged[key] = value

        fill("customer_name", intake.customer_name)
        fill("opposite_party", intake.opposite_party)
        fill("case_type", intake.case_type)

        # 案情摘要、当事人、诉讼请求优先取最新草稿
        draft = intake.drafts[-1] if intake.drafts else None
        if draft is not None:
            fill("case_title", draft.case_title)
            fill("case_summary", draft.case_summary)
            if isinstance(draft.plaintiff, dict):
                fill("customer_name", draft.plaintiff.get("name"))
            if isinstance(draft.defendant, dict):
                fill("opposite_party", draft.defendant.get("name"))
            if not merged.get("claims") and isinstance(draft.claims, list):
                merged["claims"] = [
                    c.get("content") or c.get("claim") or str(c) if isinstance(c, dict) else str(c)
                    for c in draft.claims
                ]

        fill("case_title", intake.case_type)
        return merged

    def _build_materials_summary(self, intake: LitigationIntake) -> str:
        value_cn = {"high": "高价值", "medium": "中价值", "low": "低价值"}
        lines: List[str] = []
        for m in intake.materials:
            latest = m.analysis_results[-1] if m.analysis_results else None
            sr = latest.structured_result if latest else None
            if not isinstance(sr, dict):
                continue
            summary = sr.get("summary")
            if not summary:
                continue
            value = value_cn.get(sr.get("evidence_value"), "")
            key_facts = sr.get("key_facts") or {}
            facts_text = "；".join(f"{k}:{v}" for k, v in list(key_facts.items())[:4]) if isinstance(key_facts, dict) else ""
            lines.append(f"- [{m.file_type}] {m.file_name}（{value}）：{summary}" + (f"（关键事实：{facts_text}）" if facts_text else ""))
        return "\n".join(lines)

    def _rule_assess_acceptance(self, intake: LitigationIntake, case_info: Dict[str, Any], error: str = "") -> Dict[str, Any]:
        """LLM 失败时的规则兜底，保证前端不空数据。"""
        materials = intake.materials
        source = (case_info.get("case_summary") or "") + " " + (case_info.get("dispute_amount") or "")
        has_contract = any(k in source for k in ["合同", "协议", "订单", "借条", "欠条"])
        has_payment = any(k in source for k in ["付款", "转账", "流水", "金额", "发票", "货款"])
        has_comm = any(k in source for k in ["微信", "聊天", "录音", "承诺", "催告", "通话"])
        score = [has_contract, has_payment, has_comm, len(materials) > 0].count(True)
        recommendation = "建议受理" if score >= 3 else "可预受理，需补充材料" if score >= 1 else "暂缓受理"
        missing = [
            "" if has_contract else "基础合同/协议/订单材料",
            "" if has_payment else "付款流水、转账或金额明细",
            "" if has_comm else "聊天、录音、催告或承诺材料",
        ]
        return {
            "success": True,
            "recommendation": recommendation,
            "risk_level": "低" if score >= 3 else "中" if score >= 1 else "高",
            "risk_points": [],
            "missing_materials": [m for m in missing if m],
            "cause": {},
            "jurisdiction": {},
            "strategy_summary": "基于规则兜底生成，建议补齐材料后重新分析。",
            "next_steps": ["补齐缺失证据", "确认识别文本", "进入诉讼策略分析"],
            "source": "rule_fallback",
            "fallback_error": error or "",
        }

