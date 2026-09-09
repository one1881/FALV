import io
import zipfile
from datetime import datetime
from pathlib import Path as FilePath
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.litigation import (
    CaseParty,
    CauseOpinion,
    EvidenceItem,
    FactEvidenceLink,
    FactIssue,
    JurisdictionOpinion,
    LitigationCase,
    LitigationWorkflowResult,
)


class LitigationService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def status_label(status: Optional[str]) -> str:
        labels = {
            "draft": "受理中",
            "accepted": "办理中",
            "active": "办理中",
            "processing": "办理中",
            "completed": "已完成",
            "closed": "已完成",
            "rejected": "不予受理",
            "archived": "已归档",
        }
        return labels.get(status or "", status or "受理中")

    @staticmethod
    def is_completed(status: Optional[str]) -> bool:
        return status in {"completed", "closed", "archived"}

    def generate_case_id(self) -> str:
        prefix = datetime.now().strftime("CASE-%Y%m%d-")
        last = (
            self.db.query(LitigationCase)
            .filter(LitigationCase.case_id.like(f"{prefix}%"))
            .order_by(LitigationCase.case_id.desc())
            .first()
        )
        next_number = int(last.case_id[-4:]) + 1 if last else 1
        return f"{prefix}{next_number:04d}"

    def generate_evidence_id(self) -> str:
        prefix = datetime.now().strftime("EVI-%Y%m%d-")
        return f"{prefix}{uuid4().hex[:12].upper()}"

    def create_case_from_result(self, user_id: int, context: Dict[str, Any], result: Dict[str, Any]) -> LitigationCase:
        intake = result.get("intake", {})
        draft = result.get("draft", {})
        case = LitigationCase(
            case_id=self.generate_case_id(),
            customer_id=context.get("customer_id"),
            case_title=context.get("case_title") or draft.get("case_title") or intake.get("case_title") or "未命名案件",
            case_summary=context.get("case_summary") or draft.get("case_summary") or intake.get("case_summary"),
            claims=context.get("claims") or draft.get("claims") or [],
            status="processing",
            created_by=user_id,
        )
        self.db.add(case)
        self.db.flush()

        for role_key, party_type in (("plaintiff", "plaintiff"), ("defendant", "defendant")):
            party = context.get(role_key) or {}
            if party:
                self.db.add(CaseParty(
                    case_id=case.id,
                    party_type=party_type,
                    entity_type=party.get("entity_type"),
                    name=party.get("name"),
                    id_number=party.get("id_number"),
                    credit_code=party.get("credit_code"),
                    address=party.get("address"),
                    phone=party.get("phone"),
                    enterprise_info=party.get("enterprise_info"),
                ))

        evidence_files = context.get("evidence_files") or result.get("materials") or draft.get("evidence_catalog") or []
        catalog_by_name = {
            (item.get("evidence_name") or item.get("file_name")): item
            for item in draft.get("evidence_catalog", [])
            if item.get("evidence_name") or item.get("file_name")
        }
        for item in evidence_files:
            catalog_item = catalog_by_name.get(item.get("file_name") or item.get("evidence_name"), {})
            self.db.add(EvidenceItem(
                evidence_id=self.generate_evidence_id(),
                case_id=case.id,
                evidence_type=item.get("file_type") or item.get("evidence_type"),
                evidence_name=item.get("file_name") or item.get("evidence_name"),
                file_path=item.get("file_path"),
                file_hash=item.get("file_hash"),
                ocr_text=item.get("ocr_text") or item.get("analysis_text") or item.get("source_text") or catalog_item.get("source_text"),
                entities=item.get("entities") or item.get("key_info") or catalog_item.get("key_info"),
                proof_purpose=item.get("proof_purpose") or catalog_item.get("proof_purpose"),
            ))

        for fact in result.get("evidence", {}).get("evidence_chain", {}).get("facts", []):
            self.db.add(FactIssue(
                case_id=case.id,
                fact_description=fact.get("description"),
                sufficiency=fact.get("sufficiency"),
                confidence=fact.get("confidence"),
            ))

        primary_cause = result.get("cause", {}).get("primary_cause", {})
        if primary_cause:
            self.db.add(CauseOpinion(
                case_id=case.id,
                cause_name=primary_cause.get("name"),
                cause_code=primary_cause.get("code"),
                is_primary=True,
                confidence=primary_cause.get("confidence"),
                reasoning=primary_cause.get("reasoning"),
                legal_basis=primary_cause.get("legal_basis"),
            ))

        jurisdiction = result.get("jurisdiction", {})
        if jurisdiction:
            self.db.add(JurisdictionOpinion(
                case_id=case.id,
                court_name=jurisdiction.get("primary_court"),
                is_primary=True,
                confidence=jurisdiction.get("confidence"),
                legal_basis=jurisdiction.get("legal_basis"),
            ))

        self.db.add(LitigationWorkflowResult(
            case_id=case.id,
            action="full_litigation",
            status=result.get("status", "success"),
            payload=result,
        ))

        self.db.commit()
        self.db.refresh(case)
        return case

    def list_cases(self, limit: int = 50) -> List[LitigationCase]:
        return (
            self.db.query(LitigationCase)
            .order_by(LitigationCase.created_at.desc())
            .limit(limit)
            .all()
        )

    def append_evidence_to_case(self, case: LitigationCase, evidence_files: List[Dict[str, Any]]) -> int:
        """把受理单的已确认材料追加进一个已有案件（归档到已有案件小库用）。"""
        added = 0
        for item in evidence_files or []:
            self.db.add(EvidenceItem(
                evidence_id=self.generate_evidence_id(),
                case_id=case.id,
                evidence_type=item.get("file_type") or item.get("evidence_type"),
                evidence_name=item.get("file_name") or item.get("evidence_name"),
                file_path=item.get("file_path"),
                file_hash=item.get("file_hash"),
                ocr_text=item.get("ocr_text") or item.get("analysis_text") or item.get("source_text"),
                entities=item.get("entities") or item.get("key_info"),
                proof_purpose=item.get("proof_purpose"),
            ))
            added += 1
        self.db.flush()
        return added

    def get_case_by_public_id(self, case_public_id: str) -> Optional[LitigationCase]:
        return self.db.query(LitigationCase).filter(LitigationCase.case_id == case_public_id).first()

    def get_latest_result(self, case: LitigationCase) -> Dict[str, Any]:
        # 优先取 full_litigation 主结果（含 draft/evidence_catalog 等完整上下文）。
        # workflow_results 按 created_at desc 排序，同一秒插入的 stage 记录可能排前面，
        # 若盲取 [0] 会拿到 evidence_catalog/strategy 等派生 stage，导致下游拿不到证据目录。
        for item in case.workflow_results:
            if item.action == "full_litigation":
                return item.payload if item.payload else {}
        latest = case.workflow_results[0] if case.workflow_results else None
        return latest.payload if latest else {}

    def _stage_payload(self, case: LitigationCase, stage: str) -> Dict[str, Any]:
        record = next((item for item in case.workflow_results if item.action == stage), None)
        if record:
            return record.payload or {}
        latest = self.get_latest_result(case)
        fallback_map = {
            "intake_report": self._build_intake_report(case, latest),
            "strategy": latest.get("strategy", {}),
            "evidence_catalog": latest.get("draft", {}).get("evidence_catalog") or latest.get("evidence_catalog", []),
            "trial_preparation": self._build_trial_preparation(latest),
            "pretrial_package": latest.get("pretrial_package", {}),
        }
        return fallback_map.get(stage, {})

    def save_stage_payload(self, case_public_id: str, stage: str, payload: Dict[str, Any], status: str = "completed") -> Optional[Dict[str, Any]]:
        case = self.get_case_by_public_id(case_public_id)
        if not case:
            return None
        record = next((item for item in case.workflow_results if item.action == stage), None)
        normalized = self._normalize_stage_payload(case, stage, payload, status)
        if record:
            record.payload = normalized
            record.status = status
        else:
            self.db.add(LitigationWorkflowResult(case_id=case.id, action=stage, status=status, payload=normalized))
        self.db.commit()
        return normalized

    def generate_stage_payload(self, case_public_id: str, stage: str) -> Optional[Dict[str, Any]]:
        case = self.get_case_by_public_id(case_public_id)
        if not case:
            return None
        latest = self.get_latest_result(case)
        if stage == "intake_report":
            payload = self._build_intake_report(case, latest)
        elif stage == "strategy":
            payload = latest.get("strategy", {}) or self._build_strategy_report(case, latest)
        elif stage == "evidence_catalog":
            payload = latest.get("draft", {}).get("evidence_catalog") or latest.get("evidence_catalog", [])
        elif stage == "trial_preparation":
            payload = self._build_trial_preparation(latest)
        elif stage == "pretrial_package":
            payload = self._build_pretrial_package(case, latest)
        else:
            payload = {}
        return self.save_stage_payload(case_public_id, stage, payload)

    def get_stage_payload(self, case_public_id: str, stage: str) -> Optional[Dict[str, Any]]:
        case = self.get_case_by_public_id(case_public_id)
        if not case:
            return None
        # _stage_payload 已经返回存储的 record.payload（内部已包含 case_id/stage/status/payload/updated_at 等字段），
        # 不要再用 _normalize_stage_payload 包一层，否则 routes 里的 `.get("payload")` 会取到嵌套 wrapper，导致真实数据失效。
        return self._stage_payload(case, stage)

    def _normalize_stage_payload(self, case: LitigationCase, stage: str, payload: Any, status: str) -> Dict[str, Any]:
        return {
            "case_id": case.case_id,
            "stage": stage,
            "status": status,
            "version": 1,
            "payload": payload if payload is not None else {},
            "updated_at": datetime.now().isoformat(),
        }

    def _build_intake_report(self, case: LitigationCase, latest: Dict[str, Any]) -> Dict[str, Any]:
        assessment = latest.get("assessment", {})
        evidence_catalog = latest.get("draft", {}).get("evidence_catalog") or latest.get("evidence_catalog", [])
        return {
            "case_title": case.case_title,
            "case_summary": case.case_summary,
            "parties": [{"type": party.party_type, "name": party.name, "address": party.address, "phone": party.phone} for party in case.parties],
            "claims": case.claims or [],
            "recommendation": assessment.get("recommendation") or "可预受理，需结合证据进一步确认",
            "risk_level": assessment.get("risk_level") or "中",
            "timeline": latest.get("draft", {}).get("timeline") or latest.get("timeline", []),
            "evidence_summary": evidence_catalog,
            "missing_materials": assessment.get("missing_materials") or latest.get("missing_materials", []),
            "next_steps": assessment.get("next_steps") or ["确认识别文本", "补齐缺失证据", "进入诉讼策略分析"],
        }

    def _build_strategy_report(self, case: LitigationCase, latest: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "summary": "围绕案由、诉讼请求、构成要件、举证责任和抗辩回应形成原告方诉讼打法。",
            "claims": case.claims or [],
            "cause": latest.get("cause", {}),
            "jurisdiction": latest.get("jurisdiction", {}),
            "risk": latest.get("risk", {}),
        }

    def _build_trial_preparation(self, latest: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "cross_examination": latest.get("cross_examination", []),
            "judge_questions": latest.get("judge_questions", []),
            "trial_outline": latest.get("trial_outline", {}),
            "defense_predictions": latest.get("defense_predictions", []),
        }

    def _build_pretrial_package(self, case: LitigationCase, latest: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "case_title": case.case_title,
            "documents": [
                {"name": "受理分析报告", "stage": "intake_report", "status": "ready"},
                {"name": "诉讼策略分析报告", "stage": "strategy", "status": "ready"},
                {"name": "证据目录", "stage": "evidence_catalog", "status": "ready"},
                {"name": "质证意见、模拟法官询问与庭审提纲", "stage": "trial_preparation", "status": "ready"},
            ],
            "export_formats": ["Word", "PDF", "Excel"],
            "completion_notes": ["导出前请核对证据页码、原件状态、金额口径和律师确认内容。"],
        }

    def get_case_detail(self, case_public_id: str) -> Optional[Dict[str, Any]]:
        case = self.get_case_by_public_id(case_public_id)
        if not case:
            return None
        return {
            "id": case.id,
            "case_id": case.case_id,
            "case_title": case.case_title,
            "customer_id": case.customer_id,
            "case_summary": case.case_summary,
            "claims": case.claims or [],
            "status": case.status,
            "status_label": self.status_label(case.status),
            "is_completed": self.is_completed(case.status),
            "created_by": case.created_by,
            "intake_lawyer_id": case.created_by,
            "intake_lawyer_name": case.creator.full_name if case.creator else None,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "parties": [
                {
                    "id": party.id,
                    "party_type": party.party_type,
                    "entity_type": party.entity_type,
                    "name": party.name,
                    "id_number": party.id_number,
                    "credit_code": party.credit_code,
                    "address": party.address,
                    "phone": party.phone,
                    "enterprise_info": party.enterprise_info,
                }
                for party in case.parties
            ],
            "latest_result": self.get_latest_result(case),
        }

    def get_evidence_payload(self, case_public_id: str) -> Optional[Dict[str, Any]]:
        case = self.get_case_by_public_id(case_public_id)
        if not case:
            return None
        latest = self.get_latest_result(case)
        # 优先读 stage_payload（已被 LLM 重新抽取/补全），没有再退回归档草稿
        # 注意：stage_payload 可能是 {case_id, stage, ..., payload: <real>} 包裹形态（payload 可能是 list 或 dict），也可能直接就是 items 列表
        stage_payload = self._stage_payload(case, "evidence_catalog")
        stage_items = []
        stage_stats = {}
        inner_payload = stage_payload.get("payload") if isinstance(stage_payload, dict) else None
        if isinstance(stage_payload, dict):
            stage_items = (
                stage_payload.get("items")
                or stage_payload.get("evidence_catalog")
                or (
                    inner_payload.get("items")
                    if isinstance(inner_payload, dict)
                    else (inner_payload if isinstance(inner_payload, list) else None)
                )
                or (inner_payload.get("evidence_catalog") if isinstance(inner_payload, dict) else None)
                or []
            )
            stage_stats = (
                stage_payload.get("extraction_stats")
                or (inner_payload.get("extraction_stats") if isinstance(inner_payload, dict) else None)
                or {}
            )
        elif isinstance(stage_payload, list):
            stage_items = stage_payload
        draft_items = latest.get("draft", {}).get("evidence_catalog") or latest.get("evidence_catalog", []) or []
        # 小库直读：归档时确认过的材料已固化进 case.evidence_items，目录以它为第一数据源；
        # draft/stage 目录只用来补充 useful/evidence_level 等律师确认字段，不再决定目录内容。
        enrich_index = {}
        for item in (stage_items if isinstance(stage_items, list) else []) + (draft_items if isinstance(draft_items, list) else []):
            if isinstance(item, dict):
                key = (item.get("evidence_name") or item.get("file_name") or "").strip()
                if key:
                    enrich_index.setdefault(key, item)
        if case.evidence_items:
            catalog = []
            for idx, ev in enumerate(case.evidence_items, start=1):
                name = (ev.evidence_name or "").strip()
                extra = enrich_index.get(name, {})
                ai = ev.entities if isinstance(ev.entities, dict) else {}
                useful = ai.get("useful") if ai.get("useful") is not None else extra.get("useful")
                catalog.append({
                    "evidence_no": idx,
                    "evidence_name": name or "未命名证据",
                    "source_file": name or extra.get("source_file") or "—",
                    "evidence_type": ev.evidence_type or extra.get("evidence_type") or extra.get("group_name") or "—",
                    "proof_purpose": ai.get("proof_purpose") or ev.proof_purpose or extra.get("proof_purpose") or "—",
                    "summary": ai.get("summary") or ev.ocr_text or extra.get("summary") or "",
                    "useful": useful,
                    "evidence_level": ai.get("evidence_level") or extra.get("evidence_level"),
                    "group_hint": extra.get("group_hint"),
                    "page_range": extra.get("page_range"),
                })
        else:
            catalog = stage_items or draft_items
        return {
            "case": self.get_case_detail(case_public_id),
            "summary": latest.get("evidence", {}),
            "evidence_catalog": catalog,
            "items": [
                {
                    "id": item.id,
                    "evidence_id": item.evidence_id,
                    "evidence_type": item.evidence_type,
                    "evidence_name": item.evidence_name,
                    "file_path": item.file_path,
                    "file_hash": item.file_hash,
                    "ocr_text": item.ocr_text,
                    "entities": item.entities,
                    "proof_purpose": item.proof_purpose,
                    "status": item.status,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in case.evidence_items
            ],
            "extraction_stats": stage_stats,
        }

    def get_analysis_payload(self, case_public_id: str) -> Optional[Dict[str, Any]]:
        case = self.get_case_by_public_id(case_public_id)
        if not case:
            return None
        latest = self.get_latest_result(case)
        return {
            "case": self.get_case_detail(case_public_id),
            "cause": latest.get("cause", {}),
            "jurisdiction": latest.get("jurisdiction", {}),
            "risk": latest.get("risk", {}),
            "facts": [
                {
                    "id": fact.id,
                    "fact_description": fact.fact_description,
                    "sufficiency": fact.sufficiency,
                    "confidence": fact.confidence,
                }
                for fact in case.facts
            ],
            "strategy": latest.get("strategy", {}),
            "evidence_catalog": latest.get("draft", {}).get("evidence_catalog") or latest.get("evidence_catalog", []),
            "defense_predictions": latest.get("defense_predictions", []),
            "cross_examination": latest.get("cross_examination", []),
            "judge_questions": latest.get("judge_questions", []),
            "trial_outline": latest.get("trial_outline", {}),
            "pretrial_package": latest.get("pretrial_package", {}),
        }

    def get_pleading_payload(self, case_public_id: str) -> Optional[Dict[str, Any]]:
        case = self.get_case_by_public_id(case_public_id)
        if not case:
            return None
        latest = self.get_latest_result(case)
        return {
            "case": self.get_case_detail(case_public_id),
            "pleading": latest.get("pleading", {}),
            "evidence": latest.get("evidence", {}),
        }

    def export_evidence_catalog_csv(self, case_public_id: str) -> Optional[str]:
        stage = self.get_stage_payload(case_public_id, "evidence_catalog")
        if not stage:
            return None
        rows = stage.get("payload") or []
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("evidence_catalog") or []
        lines = ["序号,证据名称,证据类型,页码,证明目的,对应待证事实,原件状态"]
        for index, item in enumerate(rows, start=1):
            def clean(value: Any) -> str:
                text = str(value or "").replace('"', '""').replace("\n", " ")
                return f'"{text}"'
            lines.append(",".join([
                clean(item.get("evidence_no") or index),
                clean(item.get("evidence_name")),
                clean(item.get("evidence_type") or item.get("group_name")),
                clean(item.get("page_range")),
                clean(item.get("proof_purpose")),
                clean(item.get("related_fact")),
                clean(item.get("original_status")),
            ]))
        return "﻿" + "\n".join(lines)

    def export_pretrial_package_markdown(self, case_public_id: str) -> Optional[str]:
        case = self.get_case_by_public_id(case_public_id)
        if not case:
            return None
        files = self.build_pretrial_package_files(case)
        parts = [f"# 庭前材料包：{case.case_title or case.case_id}", ""]
        for name, content in files.items():
            if name.endswith(".csv"):
                parts.append(f"## {name}\n\n```csv\n{content}\n```")
            else:
                parts.append(content)
        return "\n\n---\n\n".join(parts)

    def export_pretrial_package_zip(self, case_public_id: str) -> Optional[bytes]:
        case = self.get_case_by_public_id(case_public_id)
        if not case:
            return None
        files = self.build_pretrial_package_files(case)
        buffer = io.BytesIO()
        folder = f"{case.case_id}-庭前材料包"
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(f"{folder}/{name}", content)
            original_dir = f"{folder}/05-原始材料"
            included = 0
            for index, item in enumerate(case.evidence_items, start=1):
                if not item.file_path:
                    continue
                fp = FilePath(item.file_path)
                if fp.exists() and fp.is_file():
                    try:
                        zf.write(fp, f"{original_dir}/{index:02d}-{fp.name}")
                        included += 1
                    except Exception:
                        continue
            if included == 0:
                zf.writestr(
                    f"{original_dir}/README.txt",
                    "本目录无原始材料文件（可能未上传文件或文件已被移动）。\n证据信息请参考 02-证据目录.csv。\n",
                )
        return buffer.getvalue()

    def build_pretrial_package_files(self, case: LitigationCase) -> Dict[str, str]:
        intake = self.get_stage_payload(case.case_id, "intake_report") or {}
        strategy = self.get_stage_payload(case.case_id, "strategy") or {}
        evidence = self.get_stage_payload(case.case_id, "evidence_catalog") or {}
        trial = self.get_stage_payload(case.case_id, "trial_preparation") or {}
        pretrial = self.get_stage_payload(case.case_id, "pretrial_package") or {}
        return {
            "00-案件总览.md": self._render_overview_md(case, intake, strategy, evidence, trial, pretrial),
            "01-证据册封面.md": self._render_cover_md(case, intake),
            "02-证据目录.md": self._render_evidence_md(case, evidence, intake),
            "02-证据目录.csv": self.export_evidence_catalog_csv(case.case_id) or "序号,证据名称,证据类型,页码,证明目的,对应待证事实,原件状态\n",
            "02-有利点证据目录.md": self._render_evidence_pdf_md(case, evidence, intake, True),
            "02-不利点证据目录.md": self._render_evidence_pdf_md(case, evidence, intake, False),
            "03-诉讼策略书.md": self._render_strategy_md(strategy),
            "04-发问提纲.md": self._render_questionnaire_md(case, trial),
            "05-质证提纲.md": self._render_trial_prep_md(trial),
            "06-法庭辩论词.md": self._render_closing_argument_md(case, trial, strategy),
            "07-法官问答.md": self._render_judge_qa_md(case, trial),
            "08-开庭公文包清单.md": self._render_court_brief_md(case, intake),
        }

    @staticmethod
    def _md_escape(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            text = "、".join(str(item) for item in value)
        else:
            text = str(value if value is not None else "")
        return text.replace("|", "\\|").replace("\n", "<br/>")

    @staticmethod
    def _md_list(items: Any) -> str:
        if not items:
            return "- 无"
        if isinstance(items, str):
            return f"- {items}"
        if isinstance(items, dict):
            items = list(items.items())
        lines = []
        for item in items:
            if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], str):
                lines.append(f"- **{item[0]}**：{item[1]}")
            elif isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("title")
                    or item.get("evidence_name")
                    or item.get("description")
                    or item.get("fact_description")
                    or item.get("question")
                )
                if name:
                    lines.append(f"- {name}")
                else:
                    lines.append(f"- {item}")
            else:
                lines.append(f"- {item}")
        return "\n".join(lines)

    @staticmethod
    def _md_table(headers: List[str], rows: Any, keys: Optional[List[str]] = None) -> str:
        head = "| " + " | ".join(headers) + " |\n| " + " | ".join(["---"] * len(headers)) + " |"
        if not rows:
            return head + "\n| - |"
        lines = [head]
        for row in rows:
            if isinstance(row, dict) and keys:
                cells = [LitigationService._md_escape(row.get(key)) for key in keys]
            elif isinstance(row, (list, tuple)):
                cells = [LitigationService._md_escape(cell) for cell in row]
            else:
                cells = [LitigationService._md_escape(row)]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    @staticmethod
    def _render_risk_md(risk: Any) -> str:
        if isinstance(risk, dict):
            return "\n".join(f"- **{key}**：{value}" for key, value in risk.items() if value)
        return LitigationService._md_list(risk)

    def _render_overview_md(self, case: LitigationCase, intake: Dict, strategy: Dict, evidence: Dict, trial: Dict, pretrial: Dict) -> str:
        lines = [
            "# 案件总览",
            "",
            f"- **案件编号**：{case.case_id}",
            f"- **案件名称**：{case.case_title or '未命名案件'}",
            f"- **案件状态**：{self.status_label(case.status)}",
            f"- **导出时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 材料包内容",
            "1. `01-受理分析报告.md` —— 受理判断、风险初判、时间线与下一步",
            "2. `02-证据目录.csv` —— 证据清单（编号、名称、证明目的、页码）",
            "3. `03-诉讼策略报告.md` —— 案由、管辖、攻防与风险取舍",
            "4. `04-庭审准备包.md` —— 质证意见、模拟法官问答、庭审提纲",
            "5. `05-原始材料/` —— 上传的原始证据文件",
            "",
            "## 进度",
        ]
        steps = [
            ("受理分析报告", intake.get("status")),
            ("证据目录", evidence.get("status")),
            ("诉讼策略报告", strategy.get("status")),
            ("庭审准备包", trial.get("status")),
            ("庭前材料包", pretrial.get("status")),
        ]
        for name, status in steps:
            lines.append(f"- [{'x' if status == 'completed' else ' '}] {name}")
        return "\n".join(lines)

    def _render_evidence_rows(self, evidence: Dict, useful: Optional[bool] = None) -> List[Dict[str, Any]]:
        rows = evidence.get("payload") or []
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("evidence_catalog") or []
        if not isinstance(rows, list):
            return []
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_useful = row.get("useful")
            if useful is True and row_useful is not True:
                continue
            if useful is False and row_useful is not False:
                continue
            result.append(row)
        return result

    def _render_evidence_pdf_md(self, case: LitigationCase, evidence: Dict, intake: Dict, useful: bool) -> str:
        rows = self._render_evidence_rows(evidence, useful)
        case_meta = intake.get("payload") if isinstance(intake.get("payload"), dict) else {}
        case_no = case_meta.get("case_no") or "（ ）XX 刑初字第 XX 号"
        cause = case_meta.get("cause_name") or case.case_title or "见案件详情"
        today = datetime.now().strftime("%Y 年 %m 月 %d 日")
        title = "有利点证据目录" if useful else "不利点证据目录"
        intro = "本页仅收录对我方有利的证据。" if useful else "本页仅收录对我方不利的证据。"

        lines = [
            f"# {title}",
            "",
            f"- **案号**：{case_no}",
            f"- **案由**：{cause}",
            f"- **案件名称**：{case.case_title or '未命名案件'}",
            f"- **导出时间**：{today}",
            f"- **说明**：{intro}",
            "",
        ]

        if not rows:
            lines += ["## 证据目录", "", "- 无符合条件的证据。"]
            return "\n".join(lines)

        for index, row in enumerate(rows, start=1):
            evidence_name = row.get("evidence_name") or row.get("name") or f"证据 {index}"
            summary = row.get("summary") or row.get("ocr_text") or row.get("analysis_text") or row.get("source_text") or "无"
            importance = row.get("evidence_level") or row.get("importance") or "中"
            if importance == "A":
                importance = "高"
            elif importance == "B":
                importance = "中"
            elif importance == "C":
                importance = "低"
            key_info = row.get("key_info") or row.get("entities") or row.get("proof_purpose") or "无"
            opposite_label = "不利点" if useful else "有利点"
            opposite_reason = row.get("proof_purpose") or row.get("summary") or "无"
            time_text = row.get("time_range") or row.get("page_range") or row.get("page") or "无"
            media_kind = row.get("file_type") or row.get("evidence_type") or row.get("group_name") or row.get("type") or "材料"

            lines += [
                f"## {index}. {evidence_name}",
                f"- **总结的文字**：{summary}",
                f"- **重要等级**：{importance}",
                f"- **重点信息**：{self._md_escape(key_info)}",
                f"- **类型**：{media_kind}",
                f"- **时间戳**：{time_text}",
                f"- **{opposite_label}**：{self._md_escape(opposite_reason)}",
                "",
            ]

        return "\n".join(lines)

    def _render_evidence_md(self, case: LitigationCase, evidence: Dict, intake: Dict) -> str:
        rows = evidence.get("payload") or []
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("evidence_catalog") or []
        case_meta = intake.get("payload") if isinstance(intake.get("payload"), dict) else {}
        case_no = case_meta.get("case_no") or "（ ）XX 刑初字第 XX 号"
        cause = case_meta.get("cause_name") or "见案件详情"
        today = datetime.now().strftime("%Y 年 %m 月 %d 日")

        lines = [
            "# 证据目录（法院当庭接收格式）",
            "",
            "## 封面信息",
            "",
            f"- **案号**：{case_no}",
            f"- **案由**：{cause}",
            "- **提交人**：________________（被告人辩护人 / 被害人诉讼代理人）",
            "- **提交法院**：________________",
            f"- **提交日期**：{today}",
            "- **份数**：正本壹套、副本贰套",
            "",
            "## 证据目录表",
            "",
        ]

        if rows:
            lines.append(self._md_table(
                ["序号", "证据名称", "证据来源", "证据种类", "证明目的", "页码"],
                rows,
                ["evidence_no", "evidence_name", "evidence_source", "evidence_type", "proof_purpose", "page_range"],
            ))
        else:
            lines.append(self._md_table(
                ["序号", "证据名称", "证据来源", "证据种类", "证明目的", "页码"],
                [
                    {"evidence_no": "01", "evidence_name": "报警回执、受案登记表、立案决定书", "evidence_source": "XX 派出所 / XX 分局", "evidence_type": "书证", "proof_purpose": "证明案发时间、报案事实、案件来源合法", "page_range": "1-3"},
                    {"evidence_no": "02", "evidence_name": "被害人/被告人讯问笔录", "evidence_source": "公安侦查卷宗", "evidence_type": "言词证据", "proof_purpose": "还原案发现场冲突起因、行为过程", "page_range": "4-15"},
                    {"evidence_no": "03", "evidence_name": "证人证言笔录", "evidence_source": "公安卷宗/我方自行取证", "evidence_type": "言词证据", "proof_purpose": "佐证核心事实，补强证据链", "page_range": "16-22"},
                    {"evidence_no": "04", "evidence_name": "法医学人体损伤程度鉴定书", "evidence_source": "XX 司法鉴定中心", "evidence_type": "鉴定意见", "proof_purpose": "证明伤情等级与损害后果", "page_range": "23-30"},
                    {"evidence_no": "05", "evidence_name": "病历、诊断证明、医疗费票据", "evidence_source": "XX 医院", "evidence_type": "书证", "proof_purpose": "证明伤情真实性、治疗过程与实际损失", "page_range": "31-42"},
                    {"evidence_no": "06", "evidence_name": "现场监控视频/录音及文字转录稿", "evidence_source": "现场调取/当事人留存", "evidence_type": "视听资料", "proof_purpose": "直观还原冲突全过程", "page_range": "43-50"},
                    {"evidence_no": "07", "evidence_name": "伤情照片、现场照片", "evidence_source": "公安机关拍摄/当事人拍摄", "evidence_type": "书证/物证照片", "proof_purpose": "直观展示被害人受伤状态", "page_range": "51-55"},
                ],
                ["evidence_no", "evidence_name", "evidence_source", "evidence_type", "proof_purpose", "page_range"],
            ))

        lines += [
            "",
            "## 装订实务规则（法院硬性要求）",
            "",
            self._md_list([
                "1. 全部材料统一 A4 复印、右侧装订，每页右下角连续页码，与目录一一对应；",
                "2. 音视频资料必须附带逐字文字转录稿 + 时间节点，无转录稿法庭不予采信；",
                "3. 开庭携带全部证据原件备查，复印件提交法院归档；",
                "4. 必备三套：法院一套、对方一套、律师自用一套；",
                "5. 提交人签字：________________ &nbsp; 日期：________________",
            ]),
        ]
        return "\n".join(lines)

    def _render_court_brief_md(self, case: LitigationCase, intake: Dict) -> str:
        case_meta = intake.get("payload") if isinstance(intake.get("payload"), dict) else {}
        today = datetime.now().strftime("%Y-%m-%d")
        lines = [
            "# 律师开庭公文包最终清单",
            "",
            f"- **案件名称**：{case.case_title or '—'}",
            f"- **案号**：{case.case_id}",
            "- **出庭日期**：________________",
            "- **律师**：________________",
            f"- **清单确认日期**：{today}",
            "",
            "## 出门前对照打勾（☐）",
            "",
            self._md_list([
                "1. ☐ 律所函、授权委托书、律师证复印件（交法院归档）",
                "2. ☐ 起诉书 / 量刑建议书 / 开庭传票（提前打印 3 份）",
                "3. ☐ 证据册三套（法院一套、对方一套、律师自用一套，A4 装订 + 连续页码）",
                "4. ☐ 律师内部工作底稿：诉讼策略书 / 发问提纲 / 质证提纲 / 辩论词 / 法官问答预案",
                "5. ☐ 证据原件袋（按证据目录编号，原件单独装袋贴签）",
                "6. ☐ 视频 U 盘 + 完整文字转录稿（时间节点清楚）+ 备用 U 盘",
                "7. ☐ 案件时间线 A4 纸（手写便签亦可，关键日期/事件一目了然）",
                "8. ☐ 委托人手书授权委托书原件 / 当事人身份证复印件",
                "9. ☐ 笔记本 / 签字笔 / 录音笔（庭后第一时间记录庭审要点）",
                "10. ☐ 律师执业证原件 + 名片若干（与对方律师交换联系方式）",
            ]),
            "",
            "## 当庭核对清单（开场 5 分钟内完成）",
            "",
            self._md_list([
                "1. ☐ 双方当事人 / 代理人身份核对无误",
                "2. ☐ 证据原件已清点，复印件备份已在手",
                "3. ☐ 音视频设备播放正常，转录稿已标注时间节点",
                "4. ☐ 法官当庭提出新证据时立即补办质证意见",
                "5. ☐ 庭审结束前递交书面质证意见与代理词",
            ]),
            "",
            "## 庭后 24 小时必办",
            "",
            self._md_list([
                "1. ☐ 整理庭审笔录要点 + 法官提问原话摘录",
                "2. ☐ 比对当庭新主张与原诉讼策略，调整下一步",
                "3. ☐ 补充提交代理意见或补充质证意见（按法院要求）",
                "4. ☐ 通知委托人就庭审关键节点与判决预期",
            ]),
            "",
            "---",
            "",
            f"_清单版本：{today} · 关联案件：{case.case_id}_",
        ]
        return "\n".join(lines)

    def _render_cover_md(self, case: LitigationCase, intake: Dict) -> str:
        case_meta = intake.get("payload") if isinstance(intake.get("payload"), dict) else {}
        today = datetime.now().strftime("%Y 年 %m 月 %d 日")
        plaintiff = next((p for p in case.parties if p.party_type == "plaintiff"), None)
        defendant = next((p for p in case.parties if p.party_type == "defendant"), None)
        lines = [
            "# 证据册封面",
            "",
            "---",
            "",
            "## 【证据材料】",
            "",
            f"- **案由**：{case_meta.get('cause_name') or case.case_title or 'XX 纠纷'} 一案",
            "- **提交人**：________________（被告人辩护人 / 被害人诉讼代理人）",
            f"- **对方当事人**：原告 {plaintiff.name if plaintiff else '________________'}，被告 {defendant.name if defendant else '________________'}",
            "- **提交法院**：________________ 人民法院",
            "- **案号**：________________（ ）字第 ____ 号",
            f"- **提交日期**：{today}",
            "- **份数**：正本壹套、副本贰套",
            "",
            "---",
            "",
            "_本封面与证据目录、证据材料、装订实务规则一同成册，提交法院当庭接收。_",
        ]
        return "\n".join(lines)

    def _render_closing_argument_md(self, case: LitigationCase, trial: Dict, strategy: Dict) -> str:
        p = trial.get("payload") or {}
        sp = strategy.get("payload") or {}
        case_meta = p.get("case_meta") or sp.get("case_meta") or {}
        case_title = case_meta.get("case_title") or case.case_title or "本案"
        lawyer_role = case_meta.get("lawyer_role") or "代理律师"
        today = datetime.now().strftime("%Y 年 %m 月 %d 日")

        cause = sp.get("cause") or {}
        primary = cause.get("primary_cause") or {}
        cause_name = primary.get("name") or case_meta.get("cause_name") or "本案争议"
        legal_basis = primary.get("legal_basis") or "依据现行民事/刑事相关法律规定"
        claims = sp.get("claims") or case_meta.get("claims") or []
        claim_text = ""
        if claims:
            parts = []
            for claim in claims:
                if isinstance(claim, dict):
                    parts.append(claim.get("description") or claim.get("amount") or str(claim))
                else:
                    parts.append(str(claim))
            claim_text = "、".join(parts)

        closing = p.get("closing_argument")
        if isinstance(closing, dict) and closing.get("intro"):
            body = closing["intro"] + "\n\n"
            for sec in closing.get("sections") or []:
                body += f"**{sec.get('title', '一')}**\n\n{sec.get('body', '')}\n\n"
            if closing.get("ending"):
                body += closing["ending"] + "\n"
            ending = f"代理人：________________   {today}"
        else:
            body = (
                "审判长、审判员：\n\n"
                f"本人系 {lawyer_role}，就 {case_title.replace('案', '')} 一案，结合今日庭审调查、举证质证，发表如下代理意见，请法庭予以采纳。\n\n"
                "**一、本案事实层面**\n\n"
                f"结合全案证据，本案案由为 {cause_name}，案发起因、行为过程及损害后果已经查清。\n\n"
                "**二、证据层面**\n\n"
                "本案现有证据已经形成完整证据链，对应证据均具备真实性、合法性、关联性，能够排他性证明本案核心事实。\n\n"
                "**三、法律适用层面**\n\n"
                f"{legal_basis}。本案事实符合该条法律规定之构成要件，应当依法支持我方主张。\n\n"
                "**四、诉讼请求**\n\n"
                + (f"综上，恳请法庭依法判令：{claim_text}。" if claim_text else "综上，恳请法庭依法支持我方全部诉讼请求。")
                + "\n\n"
                f"辩护人/代理人：________________   {today}"
            )
            ending = ""
        lines = ["# 法庭辩论词（当庭宣读稿）", "", f"- **案件名称**：{case_title}", f"- **办案身份**：{lawyer_role}", f"- **制作日期**：{today}", "", "---", "", body, ending or f"代理人：________________   {today}"]
        return "\n".join(lines)

    def _render_judge_qa_md(self, case: LitigationCase, trial: Dict) -> str:
        p = trial.get("payload") or {}
        case_meta = p.get("case_meta") or {}
        today = datetime.now().strftime("%Y 年 %m 月 %d 日")
        judge_qs = p.get("judge_questions")
        lines = ["# 法官高频提问 + 标准答案预案", "", f"- **案件名称**：{case_meta.get('case_title') or case.case_title or '—'}", f"- **制作日期**：{today}", "", "---", ""]
        if judge_qs:
            lines += ["## 标准问答清单", self._md_table(["法官问题", "标准答案预案"], judge_qs, ["question", "answer"]), ""]
        else:
            lines += [
                "## 标准问答清单（庭前必须背诵）",
                self._md_table(
                    ["法官问题", "标准答案预案"],
                    [
                        {"question": "1. 你方认为本案主要责任在谁一方？依据是什么？", "answer": "本案主要责任由对方承担。依据在案证据（笔录、视频、证人证言、对账单、签收单），对方行为直接引发本案，证据链完整、真实合法。"},
                        {"question": "2. 本案损害后果/请求金额是否完全由对方造成？有无其他因素？", "answer": "结合病历及鉴定意见，本案损害后果（完全/部分）系对方本次行为直接造成，无其他介入因素，因果关系完整、唯一、合法。"},
                        {"question": "3. 双方证言存在矛盾，你方如何解释？", "answer": "言词证据因细节记忆存在细微偏差属正常现象，但核心事实高度吻合，不影响本案基本事实认定，细微矛盾不影响定案。"},
                        {"question": "4. 是否愿意调解/赔偿？调解方案是什么？", "answer": "我方愿意积极化解纠纷，在合法合理范围内积极履行义务（具体方案：______），恳请法庭结合全案情况依法裁判。"},
                        {"question": "5. 原告证据是否充足？如有不足如何补强？", "answer": "我方现有证据已能证明核心请求事实，关键证据已核对原件并附转录，庭前已要求对方庭后补充质证意见。"},
                    ],
                    ["question", "answer"],
                ),
                "",
            ]
        lines += ["## 应答技巧", self._md_list([
            "1. **语气**：平静、清晰、对法官保持目光接触；",
            "2. **节奏**：先复述法官问题，再分段作答，避免抢答；",
            "3. **限度**：仅答必要事实，不主动扩大陈述范围；",
            "4. **依据**：关键回答必带证据编号（\"依据证据 03 对账单\"）；",
            "5. **留白**：对未掌握事项直接表达\"庭后核实提交书面意见\"。",
        ]), "", "---", "", f"_预案版本：{today} · 使用前请律师核对案件具体事实_"]
        return "\n".join(lines)

    def _render_questionnaire_md(self, case: LitigationCase, trial: Dict) -> str:
        p = trial.get("payload") or {}
        case_meta = p.get("case_meta") or {}
        lawyer_role = case_meta.get("lawyer_role") or "代理律师"
        today = datetime.now().strftime("%Y 年 %m 月 %d 日")

        lines = [
            "# 庭审发问提纲",
            "",
            f"- **案件名称**：{case_meta.get('case_title') or case.case_title or '—'}",
            f"- **办案身份**：{lawyer_role}",
            f"- **制作日期**：{today}",
            "",
            "---",
            "",
            "## 一、通用标准发问（按庭审身份选用）",
            "",
        ]

        questions_defendant = p.get("questions_to_defendant") or [
            "1. 案发当日具体时间、地点，事件如何引发？",
            "2. 对方是否存在先行辱骂、推搡、动手或其他不当行为？",
            "3. 你/对方实施了哪些具体行为？方式、力度、次数？",
            "4. 实施行为时的主观目的是什么？是否刻意造成损害？",
            "5. 事后如何处置？是否主动配合调查？是否愿意赔偿？",
        ]
        lines += [
            "### （辩护方）对被告人发问（注意避免诱导性提问）",
            self._md_list(questions_defendant),
            "",
            "### （控方/代理人）对被害人/证人发问（按时间顺序展开）",
        ]
        questions_witness = p.get("questions_to_witness") or [
            "1. 冲突完整经过？哪一方率先引发？",
            "2. 对方具体实施了哪些行为？细节如何？",
            "3. 现场其他在场人员有哪些？是否能到庭作证？",
            "4. 受伤后就医过程是否连续、真实？",
        ]
        lines += self._md_list(questions_witness)

        lines += [
            "",
            "## 二、本案定制发问（结合争议焦点）",
            "",
            self._md_list([
                "针对【争议焦点 1：基础法律关系】的发问：________________",
                "针对【争议焦点 2：履行事实】的发问：________________",
                "针对【争议焦点 3：是否违约/侵权】的发问：________________",
                "针对【争议焦点 4：金额/责任】的发问：________________",
            ]),
            "",
            "## 三、发问技巧与禁忌",
            "",
            self._md_list([
                "1. **先易后难**：先用事实性问题开场，再追问主观方面；",
                "2. **闭合式为主**：能用\"是/否\"回答的提问优先，便于对方明确表态；",
                "3. **一句一答**：避免多个问题组合提问，防止选择性回答；",
                "4. **不诱导**：诱导性问题法官可制止，反而损害可信度；",
                "5. **记清回应**：对方回答可能与庭审笔录不一致，庭后核对。",
            ]),
            "",
            "---",
            f"_提纲版本：{today} · 使用前请核对本案具体争议焦点_",
        ]
        return "\n".join(lines)

    def _render_intake_report_md(self, intake: Dict, evidence: Dict) -> str:
        p = intake.get("payload") or {}
        lines = [
            "# 受理分析报告",
            "",
            "## 案件信息",
            f"- **案件名称**：{p.get('case_title') or '—'}",
            f"- **案情摘要**：{p.get('case_summary') or '无'}",
            "",
            "## 当事人",
            self._md_table(["角色", "名称", "地址", "电话"], p.get("parties") or [], ["type", "name", "address", "phone"]),
            "",
            "## 诉讼请求",
        ]
        claims = p.get("claims") or []
        if claims:
            for claim in claims:
                lines.append(f"- {claim.get('description') or claim.get('amount') if isinstance(claim, dict) else claim}")
        else:
            lines.append("- 无")
        lines += ["", "## 受理判断", f"- **建议**：{p.get('recommendation') or '—'}", f"- **风险等级**：{p.get('risk_level') or '—'}"]
        timeline = p.get("timeline") or []
        if timeline:
            lines += ["", "## 关键时间线", self._md_table(["时间", "事件"], timeline, ["date", "event"])]
        evidence_rows = evidence.get("payload") or []
        if isinstance(evidence_rows, dict):
            evidence_rows = evidence_rows.get("items") or evidence_rows.get("evidence_catalog") or []
        if evidence_rows:
            lines += ["", "## 证据概况", self._md_table(["编号", "证据名称", "证明目的"], evidence_rows, ["evidence_no", "evidence_name", "proof_purpose"])]
        missing = p.get("missing_materials") or []
        lines += ["", "## 缺失材料", self._md_list(missing), "", "## 下一步", self._md_list(p.get("next_steps") or [])]
        return "\n".join(lines)

    def _render_strategy_md(self, strategy: Dict) -> str:
        p = strategy.get("payload") or {}
        case_meta = p.get("case_meta") or {}
        cause = p.get("cause") or {}
        primary = cause.get("primary_cause") or {}
        jurisdiction = p.get("jurisdiction") or {}
        risk = p.get("risk") or {}
        claims = p.get("claims") or case_meta.get("claims") or []
        today = datetime.now().strftime("%Y 年 %m 月 %d 日")

        lines = ["# 诉讼策略书", ""]
        lines += [
            f"- **案件名称**：{case_meta.get('case_title') or '—'}",
            f"- **案号**：{case_meta.get('case_id') or '—'}",
            f"- **办案身份**：{case_meta.get('lawyer_role') or '—'}",
            f"- **制作日期**：{today}",
            "",
            "## 一、案件核心争议焦点",
        ]
        dispute_focus = p.get("dispute_focus") or [
            "1. 本次争议的法律关系是否成立；",
            "2. 我方是否已按约履行；",
            "3. 对方是否构成违约或侵权；",
            "4. 责任承担范围与金额计算依据。",
        ]
        lines += self._md_list(dispute_focus)

        lines += ["", "## 二、整体诉讼目标", ""]
        if p.get("overall_goal"):
            lines.append(p["overall_goal"])
        else:
            plaintiff = case_meta.get("lawyer_role") in ("原告代理人", "原告")
            if plaintiff:
                lines.append("完整固定对方违约事实与损害后果，追究对方全部民事责任，争取全额支持我方诉讼请求并附以合理费用。")
            else:
                lines.append("弱化我方过错责任，排除不利因果关系，争取减轻责任、调整责任比例或依法免责。")

        lines += ["", "## 三、我方优势证据", ""]
        strong = p.get("strong_evidence") or case_meta.get("strong_evidence") or [
            "已核对原件的关键证据；对己方主张能直接证明的原始凭证；对方自认或签字确认的文件；视听资料与文字转录稿。"
        ]
        lines.append(self._md_list(strong))

        lines += ["", "## 四、薄弱风险点与应对预案", ""]
        risks = p.get("risk_points") or []
        if risks:
            for risk_item in risks:
                risk_text = risk_item.get("risk") if isinstance(risk_item, dict) else str(risk_item)
                response_text = risk_item.get("response") if isinstance(risk_item, dict) else ""
                lines.append(f"- **风险**：{risk_text or '—'}")
                if response_text:
                    lines.append(f"  - **应对**：{response_text}")
        else:
            lines.append(self._md_list([
                "风险：单一证据缺失可能影响关键事实认定 → 应对：庭前补强同类证据或申请证人出庭",
                "风险：证据形式瑕疵可能被质疑合法性 → 应对：核对原件提交时间、补强取得方式说明",
                "风险：对方提出反诉或抵消主张 → 应对：归集抗辩证据并准备书面应对意见",
            ]))

        lines += ["", "## 五、对方攻防方向预判", ""]
        opponent = p.get("opponent_predictions") or [
            "1. 对证据真实性、合法性、关联性提出异议；",
            "2. 主张事实抗辩、诉讼时效抗辩或免责事由；",
            "3. 提出反诉、抵消或部分履行主张。",
        ]
        lines += self._md_list(opponent)

        if claims:
            lines += ["", "## 附、诉讼请求清单"]
            for claim in claims:
                if isinstance(claim, dict):
                    lines.append(f"- {claim.get('description') or claim.get('amount') or claim}")
                else:
                    lines.append(f"- {claim}")

        if risk:
            lines += ["", "## 风险评级", self._render_risk_md(risk)]

        lines += ["", "---", f"_代理人：________________   {today}_"]
        return "\n".join(lines)

    def _render_trial_prep_md(self, trial: Dict) -> str:
        p = trial.get("payload") or {}
        case_meta = p.get("case_meta") or {}
        lawyer_role = case_meta.get("lawyer_role") or "代理律师"
        case_title = case_meta.get("case_title") or "本案"
        today = datetime.now().strftime("%Y 年 %m 月 %d 日")

        lines = ["# 庭审备战全套底稿", ""]
        lines += [
            f"- **案件名称**：{case_title}",
            f"- **办案身份**：{lawyer_role}",
            f"- **制作日期**：{today}",
            "",
            "---",
            "",
            "## 模块 1 · 庭审发问提纲",
            "",
        ]

        questions_defendant = p.get("questions_to_defendant") or [
            "案发当日具体时间、地点，冲突如何引发？",
            "对方是否存在先行辱骂、推搡、动手行为？",
            "你是否实施相应行为？行为方式、力度、次数？",
            "你实施行为的主观目的是什么？是否刻意给对方造成损害？",
            "案发后是否主动配合调查、是否认罪悔罪、是否愿意赔偿？",
        ]
        lines += [
            "### 对被告人/对方当事人发问（按所处身份选用）",
            self._md_list(questions_defendant),
            "",
            "### 对被害人/证人发问（控方举证时使用）",
        ]
        questions_witness = p.get("questions_to_witness") or [
            "冲突发生的完整经过？谁率先引发？",
            "对方具体实施了哪些行为？细节如何？",
            "现场有无其他在场人员，能否证明？",
            "事后处置过程是否连续、真实？",
        ]
        lines += self._md_list(questions_witness)

        lines += [
            "",
            "---",
            "",
            "## 模块 2 · 逐项质证提纲（万能四维度）",
            "",
            "**通用句式**：对 XX 证据：真实性 ☐无异议 ☐有异议；合法性 ☐无异议 ☐有异议；关联性 ☐无异议 ☐有异议；证明目的 ☐全部认可 ☐不予全部认可。具体理由：XXXXXXXX。",
            "",
        ]
        cross = p.get("cross_examination") or []
        if cross:
            lines += ["### 我方逐项质证意见", self._md_table(["证据编号", "证据名称", "可能异议", "回应意见"], cross, ["evidence_no", "evidence_name", "possible_objection", "response_opinion"]), ""]
        else:
            lines += [
                "### 我方逐项质证意见（待核对每项证据后逐项填写）",
                self._md_table(
                    ["证据编号", "证据名称", "异议维度", "具体理由"],
                    [
                        {"evidence_no": "01", "evidence_name": "（按证据目录编号）", "possible_objection": "真实性/合法性/关联性", "response_opinion": "针对异议的具体理由"},
                    ],
                    ["evidence_no", "evidence_name", "possible_objection", "response_opinion"],
                ),
                "",
            ]

        lines += [
            "### 高频证据专项质证句式",
            self._md_list([
                "【鉴定意见】若对鉴定程序、送检样本、伤情依据、因果关系有异议，可提出：本次鉴定未区分既往损伤与本次新发伤情，全部归责于本次冲突依据不足。",
                "【言词笔录】笔录内容前后矛盾、与现场视频不符，无其他佐证，不能单独作为定案依据。",
                "【视听资料】截取片段不完整、无完整转录、无法反映全程事实，不能完整证明对方主张。",
                "【书证复印件】应当庭出示原件，对方仅出示复印件的，真实性不予认可。",
            ]),
            "",
            "---",
            "",
            "## 模块 3 · 法庭辩论词（当庭宣读）",
            "",
        ]

        closing = p.get("closing_argument") or {}
        if isinstance(closing, dict) and closing.get("intro"):
            lines.append("### 第一轮完整辩论（当庭宣读）")
            lines += [closing["intro"]]
            for section in closing.get("sections") or []:
                lines.append(f"**{section.get('title', '一')}**")
                lines.append(section.get("body", ""))
            if closing.get("ending"):
                lines.append(closing["ending"])
        else:
            lines += [
                "### 第一轮完整辩论（可直接当庭宣读）",
                "",
                "审判长、审判员：",
                "",
                f"本人系本案当事人 {case_title.replace('案', '')} 的委托诉讼代理人。结合今日庭审调查、举证质证，发表如下代理意见，请法庭予以采纳。",
                "",
                "**一、本案事实层面**",
                "",
                "结合全案证据，本案案发起因、行为过程与损害后果已经查清。",
                "",
                "**二、证据层面**",
                "",
                "本案现有证据已经形成完整的证据链，能够互相印证、排他性证明本案核心事实。",
                "",
                "**三、法律适用层面**",
                "",
                "依据本案事实与现行法律规定，本案应当依法认定对方当事人承担相应法律责任。",
                "",
                "**四、量刑/处理意见**",
                "",
                "结合本案过错程度、赔偿谅解、认罪态度、初犯偶犯等情节，恳请法庭依法对当事人依法裁判。",
                "",
                "综上，恳请法庭查清全案事实，依法公正裁判。",
                "",
            ]
        lines += [f"代理人/辩护人：________________   {today}", "", "---", "", "## 模块 4 · 法官高频提问 + 标准答案", ""]

        judge_qs = p.get("judge_questions") or []
        if judge_qs:
            lines += ["### 模拟法官询问（庭前背诵 4-8 条）", self._md_table(["问题", "参考回答"], judge_qs, ["question", "answer"]), ""]
        else:
            lines += [
                "### 模拟法官询问（庭前必须背诵的 4 条标准问答）",
                self._md_table(
                    ["法官问题", "标准答案"],
                    [
                        {"question": "你方认为本案主要过错/违约方是谁？依据是什么？", "answer": "本案主要责任应当由对方承担。依据在案证据，XX 笔录、视频与证人证言能够证明 XX 行为引发本案，对方在本案中存在明显过错。"},
                        {"question": "本案损害后果/请求金额是否完全由对方行为造成？", "answer": "结合病历、鉴定意见与因果关系，本案损害后果（完全/部分）系本次行为造成，无其他介入因素，因果关系完整、唯一。"},
                        {"question": "双方证言存在矛盾，你方如何解释？", "answer": "言词证据对细节记忆存在偏差属正常，但核心事实高度吻合，不影响本案基本事实认定，细微矛盾不影响定案。"},
                        {"question": "是否愿意调解/赔偿？方案是什么？", "answer": "我方愿意积极化解矛盾，在合法合理范围内积极履行义务，恳请法庭结合全案情况依法裁判。"},
                    ],
                    ["question", "answer"],
                ),
                "",
            ]

        lines += [
            "---",
            "",
            "## 模块 5 · 被告抗辩回应预案",
            "",
        ]
        defenses = p.get("defense_predictions") or []
        if defenses:
            lines.append(self._md_table(["被告可能抗辩", "我方回应", "对应证据"], defenses, ["defense", "response", "evidence_names"]))
        else:
            lines.append(self._md_table(
                ["被告可能抗辩", "我方回应", "对应证据"],
                [
                    {"defense": "未收到货物 / 金额有争议", "response": "以签收记录和对方对账确认为据，引述录音中承认欠款的表述。", "evidence_names": "对账单 / 签收单 / 录音转录"},
                    {"defense": "质量瑕疵 / 双方均有过错", "response": "比对合同约定的质量标准与异议期限，未在期限内提出视为认可。", "evidence_names": "合同 / 质检记录 / 沟通记录"},
                    {"defense": "诉讼时效经过 / 主体不适格", "response": "核对催收记录与时效中断证据，核实对方主体准确名称。", "evidence_names": "催款记录 / 工商登记"},
                ],
                ["defense", "response", "evidence_names"],
            ))

        return "\n".join(lines)
