"""诉讼模块 HTTP 路由。

本文件在「诉讼模块被整体抽除」后按原有设计重建：调用既有的
litigation_service / litigation_intake_service 暴露能力，不重复实现业务逻辑。

前缀约定：main.py 会以 settings.API_V1_PREFIX（/api）挂载本路由，
因此对外完整路径为 /api/litigation/...
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Any
import io
import logging

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.litigation_service import LitigationService
from app.services.litigation_intake_service import LitigationIntakeService
from app.schemas.litigation_intake import (
    IntakeCreateRequest,
    ConfirmationUpdateRequest,
    CaseDraftUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/litigation", tags=["诉讼管理"])

# 单个文书导出名 -> build_pretrial_package_files 生成的文件名
_EXPORT_FILE_MAP = {
    "evidence-catalog": "02-证据目录.md",
    "evidence-favorable": "02-有利点证据目录.md",
    "evidence-unfavorable": "02-不利点证据目录.md",
}


# --------------------------------------------------------------------------- #
# 案件 / 阶段查看
# --------------------------------------------------------------------------- #
@router.get("/cases")
def list_cases(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationService(db)
    cases = svc.list_cases(limit=limit)
    items = []
    for c in cases:
        items.append({
            "id": c.id,
            "case_id": c.case_id,
            "case_title": c.case_title,
            "case_summary": c.case_summary,
            "status": c.status,
            "status_label": svc.status_label(c.status),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })
    return {"items": items, "total": len(items)}


@router.get("/cases/{case_id}")
def get_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationService(db)
    detail = svc.get_case_detail(case_id)
    if not detail:
        raise HTTPException(status_code=404, detail="案件不存在")
    return detail


@router.get("/cases/{case_id}/evidence")
def get_evidence(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationService(db)
    payload = svc.get_evidence_payload(case_id)
    if not payload:
        raise HTTPException(status_code=404, detail="证据数据不存在")
    return payload


# --------------------------------------------------------------------------- #
# 文书导出（.md 单件 + .zip 整包）
# --------------------------------------------------------------------------- #
@router.get("/cases/{case_id}/exports/{doc}.md")
def export_doc(
    case_id: str,
    doc: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationService(db)
    case = svc.get_case_by_public_id(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案件不存在")
    target = _EXPORT_FILE_MAP.get(doc)
    if not target:
        raise HTTPException(status_code=404, detail="未知文书类型")
    files = svc.build_pretrial_package_files(case)
    content = files.get(target)
    if content is None:
        raise HTTPException(status_code=404, detail="该文书尚未生成")
    return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")


@router.get("/cases/{case_id}/exports/{doc}.pdf")
def export_doc_pdf(
    case_id: str,
    doc: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """用 reportlab 渲染 markdown 为 PDF（STSong-Light 内置中文支持）。
    证据目录类（evidence-catalog/favorable/unfavorable）走 Platypus 卡片式（图+4 字段），
    其他文书走 canvas 简单文本流。"""
    import io
    import re as _re
    from pathlib import Path
    from urllib.parse import quote
    from fastapi.responses import Response as FastAPIResponse

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.colors import HexColor as _Hex

    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))

    svc = LitigationService(db)
    case = svc.get_case_by_public_id(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案件不存在")
    target = _EXPORT_FILE_MAP.get(doc)
    if not target:
        raise HTTPException(status_code=404, detail="未知文书类型")
    files = svc.build_pretrial_package_files(case)
    content = files.get(target)
    if content is None:
        raise HTTPException(status_code=404, detail="该文书尚未生成")

    buf = io.BytesIO()

    # ===== 证据目录类（草图卡片式：左缩略图 + 右 4 字段）=====
    if doc in ("evidence-catalog", "evidence-favorable", "evidence-unfavorable"):
        evidence_payload = svc.get_evidence_payload(case_id) or {}
        catalog = evidence_payload.get("evidence_catalog") or []
        items = evidence_payload.get("items") or []  # DB 层（含 file_path/ocr_text/entities/evidence_id）
        # 按 evidence_name 建索引（items 找文件路径用）
        items_by_name = {it.get("evidence_name"): it for it in items}
        # 用 catalog 过滤（catalog 有 useful 字段，items 没有）
        if doc == "evidence-favorable":
            catalog = [it for it in catalog if it.get("useful") is True]
        elif doc == "evidence-unfavorable":
            catalog = [it for it in catalog if it.get("useful") is False]
        # items 顺序（按文件路径 + 摘要优先），便于缩略图
        merged = []
        for ci in catalog:
            ii = items_by_name.get(ci.get("evidence_name")) or {}
            merged.append({**ci, **ii})  # items（file_path/ocr_text）覆盖 catalog（useful/level）

        doc_title = {"evidence-catalog": "证据目录", "evidence-favorable": "有利点证据目录", "evidence-unfavorable": "不利点证据目录"}[doc]

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('T', parent=styles['Heading1'], fontName='STSong-Light', fontSize=18, leading=24, textColor=_Hex('#0C447C'), alignment=TA_LEFT)
        subtitle2 = ParagraphStyle('S', parent=styles['Normal'], fontName='STSong-Light', fontSize=11, leading=16, textColor=_Hex('#444441'))
        ev_title = ParagraphStyle('ET', parent=styles['Heading2'], fontName='STSong-Light', fontSize=13, leading=18, textColor=_Hex('#185FA5'))
        ev_body = ParagraphStyle('EB', parent=styles['Normal'], fontName='STSong-Light', fontSize=10, leading=15, textColor=_Hex('#2C2C2A'))
        ev_field_label = ParagraphStyle('FL', parent=styles['Normal'], fontName='STSong-Light', fontSize=10, leading=15, textColor=_Hex('#854F0B'))

        story = [Paragraph(doc_title, title_style), Spacer(1, 0.3*cm)]
        story.append(Paragraph(f"案件：{case.case_title or '未命名案件'} · 导出时间：{Path(__file__).stat().st_mtime and ''}详见正文", subtitle2))
        story.append(Spacer(1, 0.5*cm))

        if not merged:
            story.append(Paragraph("暂无符合条件的证据。", ev_body))
        else:
            for idx, it in enumerate(merged, start=1):
                # 左侧缩略图（图嵌入；无文件/视频/音频用占位）
                media_cell = _make_thumb_cell(it)
                # merged 已合并 catalog（useful/level/summary）+ items（file_path/ocr_text/entities）
                ai = it.get("entities") or {}
                summary = ai.get("summary") or it.get("summary") or it.get("ocr_text") or "（AI 未生成总结）"
                level = ai.get("evidence_level") or it.get("evidence_level") or "中"
                if level in ("A", "高"): level_txt = "高"
                elif level in ("B", "中"): level_txt = "中"
                else: level_txt = "低"
                useful = ai.get("useful") if ai.get("useful") is not None else it.get("useful")
                key_info = ai.get("key_facts") or ai.get("key_info") or it.get("proof_purpose") or "—"
                if isinstance(key_info, (list, dict)):
                    key_info = "、".join(str(v) for v in (key_info if isinstance(key_info, list) else key_info.values()))
                reason = ai.get("proof_purpose") or it.get("proof_purpose") or "—"
                use_label = "有利点" if doc == "evidence-favorable" else ("不利点" if doc == "evidence-unfavorable" else "说明")

                # 第一行显示文件位置（路径），只知道文件名没法定位文件；路径缺失时回落文件名
                file_loc = (it.get("file_path") or "").strip().replace("\\", "/")
                title_line = file_loc if file_loc else (it.get("evidence_name") or "未命名证据")
                title_line = title_line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

                right_html = (
                    f'<b>{idx:02d}. {title_line}</b><br/>'
                    f'<font color="#854F0B"><b>① 总结的文字</b></font>：{_re.sub(r"[\n\r]+", " ", summary or "")[:280]}<br/>'
                    f'<font color="#854F0B"><b>② 重要等级</b></font>：{level_txt}<br/>'
                    f'<font color="#854F0B"><b>③ 重点信息</b></font>：{_re.sub(r"[\n\r]+", " ", str(key_info))[:280]}<br/>'
                    f'<font color="#854F0B"><b>④ {use_label}</b></font>：{_re.sub(r"[\n\r]+", " ", str(reason))[:280]}'
                )

                tbl = Table([[media_cell, Paragraph(right_html, ev_body)]], colWidths=[5.5*cm, 11.5*cm])
                tbl.setStyle(TableStyle([
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('LEFTPADDING', (0,0), (-1,-1), 8),
                    ('RIGHTPADDING', (0,0), (-1,-1), 8),
                    ('TOPPADDING', (0,0), (-1,-1), 10),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 10),
                    ('LINEBELOW', (0,0), (-1,-1), 0.5, _Hex('#85B7EB')),
                    ('BACKGROUND', (0,0), (-1,-1), _Hex('#F5FAFE')),
                ]))
                story.append(tbl)
                story.append(Spacer(1, 0.3*cm))

        SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8*cm, rightMargin=1.8*cm, topMargin=1.8*cm, bottomMargin=1.8*cm).build(story)
        buf.seek(0)
        return FastAPIResponse(
            content=buf.getvalue(), media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(target.replace('.md','') + '.pdf')}"},
        )

    # ===== 其他文书：canvas 简单文本流 =====
    import textwrap
    from reportlab.pdfgen import canvas
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin_x = 50
    margin_top = height - 60
    margin_bottom = 60
    line_height = 14
    max_chars_per_line = 52
    y = margin_top
    c.setFont('STSong-Light', 10)
    for raw_line in content.split('\n'):
        line = raw_line.rstrip()
        wrapped = textwrap.wrap(line, width=max_chars_per_line, replace_whitespace=False, drop_whitespace=False) or [""]
        for chunk in wrapped:
            if y < margin_bottom:
                c.showPage()
                y = margin_top
                c.setFont('STSong-Light', 10)
            c.drawString(margin_x, y, chunk)
            y -= line_height
        y -= line_height // 2
    c.save()
    buf.seek(0)
    filename = f"{target.replace('.md','')}.pdf"
    return FastAPIResponse(
        content=buf.getvalue(), media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


def _make_thumb_cell(item: dict):
    """缩略图 cell：图直接嵌 / 视频/音频占位 / 没有就空。返回 Table cell。"""
    from reportlab.platypus import Paragraph
    from reportlab.platypus import Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor as _Hex
    from reportlab.lib.enums import TA_CENTER

    file_path = item.get("file_path")
    ftype = (item.get("evidence_type") or item.get("file_type") or "").lower()
    # 尝试从 file_path 读取本地图片 base64 嵌入
    if file_path and ftype.startswith("image"):
        try:
            from pathlib import Path as _P
            p = _P(file_path)
            if p.exists():
                img = RLImage(str(p), width=5*72/2.54, height=5*72/2.54, kind='proportional')
                return img
        except Exception:
            pass
    # 视频/音频占位
    placeholder_style = ParagraphStyle('PH', parent=getSampleStyleSheet()['Normal'], fontName='STSong-Light', fontSize=10, textColor=_Hex('#5F5E5A'), alignment=TA_CENTER)
    if ftype.startswith("video"):
        return Paragraph("[视频]<br/>点击播放原文件", placeholder_style)
    if ftype.startswith("audio"):
        return Paragraph("[音频]<br/>点击播放原文件", placeholder_style)
    return Paragraph("（无图）", placeholder_style)


# --------------------------------------------------------------------------- #
# 受理 / 上传（两步流程的入口）
# --------------------------------------------------------------------------- #
@router.post("/intake")
def create_intake(
    request: IntakeCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationIntakeService(db)
    intake = svc.create_intake(request, current_user)
    return {"intake_id": intake.intake_id, "status": intake.status}


@router.post("/intakes")
def create_intakes_alias(
    request: IntakeCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return create_intake(request, db, current_user)


@router.post("/intake/{intake_id}/files")
async def upload_intake_files(
    intake_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationIntakeService(db)
    intake = svc.get_intake(intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="受理记录不存在")
    try:
        saved = await svc.save_uploaded_files(intake, files)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "intake_id": intake_id,
        "saved": [svc.to_material_dict(m) for m in saved],
        "status": intake.status,
    }


@router.post("/intake/{intake_id}/materials/analyze")
async def analyze_intake_materials(
    intake_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对已上传材料按类型调用真实 AI（图片视觉 / 音频转写 / 字段抽取），生成确认块。"""
    svc = LitigationIntakeService(db)
    intake = svc.get_intake(intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="受理记录不存在")
    try:
        return await svc.analyze_materials(intake)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"材料分析失败: {str(exc)}") from exc


@router.post("/intake/{intake_id}/materials/{material_id}/analyze")
async def analyze_intake_material(
    intake_id: str,
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """单文件 AI 分析（逐文件调用，供前端进度条实时更新）。"""
    svc = LitigationIntakeService(db)
    intake = svc.get_intake(intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="受理记录不存在")
    material = next((m for m in intake.materials if m.material_id == material_id), None)
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    try:
        return await svc.analyze_one_material(intake, material)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"材料分析失败: {str(exc)}") from exc


@router.get("/intake/{intake_id}/materials/{material_id}/file")
def get_material_file(
    intake_id: str,
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """材料原始文件流（图片/音频/视频预览用）。FileResponse 支持 Range，视频可拖动进度。"""
    from pathlib import Path
    from fastapi.responses import FileResponse

    svc = LitigationIntakeService(db)
    intake = svc.get_intake(intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="受理记录不存在")
    material = next((m for m in intake.materials if m.material_id == material_id), None)
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    path = Path(material.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path,
        filename=material.file_name or path.name,
        content_disposition_type="inline",
    )


@router.get("/cases/{case_id}/materials/{material_id}/file")
def get_case_material_file(
    case_id: str,
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """案件级证据目录中材料的原始文件流（图片/音频/视频缩略图/播放用）。"""
    from pathlib import Path
    from fastapi.responses import FileResponse

    svc = LitigationService(db)
    case = svc.get_case_by_public_id(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案件不存在")
    # 材料从案件 evidence_items 取（关联原 intake 材料路径）
    item = next((e for e in (case.evidence_items or []) if e.evidence_id == material_id), None)
    if not item or not item.file_path:
        raise HTTPException(status_code=404, detail="材料文件不存在")
    path = Path(item.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path,
        filename=item.evidence_name or path.name,
        content_disposition_type="inline",
    )


@router.get("/intake/{intake_id}")
def get_intake(
    intake_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationIntakeService(db)
    intake = svc.get_intake(intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="受理记录不存在")
    return svc.to_detail(intake)


@router.post("/intake/{intake_id}/assess")
def assess_intake(
    intake_id: str,
    body: Dict[str, Any] = {},
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationIntakeService(db)
    intake = svc.get_intake(intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="受理记录不存在")
    result = svc.assess_acceptance(intake, body or {})
    return result


@router.post("/intake/{intake_id}/archive")
def archive_intake_case(
    intake_id: str,
    request: Dict[str, Any] = {},
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationIntakeService(db)
    intake = svc.get_intake(intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="受理记录不存在")
    assessment = request.get("assessment") or {}
    case_info = request.get("case_info") or {}
    target_case_id = request.get("target_case_id") or None
    return svc.archive_intake(intake, current_user, case_info, assessment, target_case_id=target_case_id)


@router.post("/intake/{intake_id}/draft")
def save_intake_draft(
    intake_id: str,
    request: CaseDraftUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationIntakeService(db)
    intake = svc.get_intake(intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="受理记录不存在")
    draft = svc.save_draft(intake, request)
    return svc.to_draft_dict(draft)


@router.post("/intake/{intake_id}/confirm")
def confirm_intake_block(
    intake_id: str,
    request: ConfirmationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = LitigationIntakeService(db)
    intake = svc.get_intake(intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="受理记录不存在")
    block = svc.update_confirmation(
        request.block_id, request.confirmed_result, request.status, current_user
    )
    if not block:
        raise HTTPException(status_code=404, detail="确认块不存在")
    return svc.to_block_dict(block)
