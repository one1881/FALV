from typing import Optional

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.agent import AgentExecuteRequest
from app.services.ai_service import get_ai_service
from app.services.deepagents_service import get_deepagents_service
from app.services.review_service import ReviewService

router = APIRouter(prefix="/review", tags=["文书审核"])


def _extract_doc_via_word(data: bytes) -> str:
    """用本机 Word COM 解析 .doc 旧版格式（python-docx 不支持 .doc）。"""
    import os
    import tempfile
    try:
        import win32com.client
        import pythoncom
    except ImportError as e:  # noqa: BLE001
        raise HTTPException(
            status_code=422,
            detail=f"解析 .doc 需要 pywin32 库：{e}，请先安装或用 Word/WPS 将其另存为 .docx 格式后重新上传。",
        )
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0  # wdAlertsNone
        with tempfile.TemporaryDirectory() as tmp:
            doc_path = os.path.join(tmp, "doc_in.doc")
            txt_path = os.path.join(tmp, "doc_out.txt")
            with open(doc_path, "wb") as f:
                f.write(data)
            doc = word.Documents.Open(doc_path, ReadOnly=True)
            try:
                # wdFormatText = 2，Word COM 另存为纯文本
                doc.SaveAs2(txt_path, FileFormat=2)
            finally:
                doc.Close(False)
            with open(txt_path, "r", encoding="gbk", errors="ignore") as f:
                return f.read()
    finally:
        if word:
            try:
                word.Quit()
            except Exception:  # noqa: BLE001
                pass
        pythoncom.CoUninitialize()


def _extract_text_from_bytes(filename: str, data: bytes) -> str:
    """按扩展名提取文档正文：支持 .txt / .docx / .pdf，.doc 老格式明确提示转换。"""
    name = (filename or "").lower()
    try:
        if name.endswith(".txt") or name.endswith(".md"):
            return data.decode("utf-8", errors="ignore")
        if name.endswith(".docx"):
            import io
            from docx import Document
            doc = Document(io.BytesIO(data))
            paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        paras.append(" | ".join(cells))
            return "\n".join(paras)
        if name.endswith(".pdf"):
            import io
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages = []
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    if t.strip():
                        pages.append(t)
            return "\n\n".join(pages)
        if name.endswith(".doc"):
            return _extract_doc_via_word(data)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"文档解析失败：{e}")
    raise HTTPException(status_code=422, detail="仅支持 .txt / .docx / .pdf 格式的文档解析")


@router.post("/extract-text")
async def extract_document_text(
    payload: dict,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """提取上传文档的正文文本（base64 传入），供审核结果页展示合同全文。"""
    filename = payload.get("filename", "")
    base64_content = payload.get("base64", "")
    if not base64_content:
        raise HTTPException(status_code=422, detail="缺少文件内容")
    import base64
    try:
        data = base64.b64decode(base64_content.split(",")[-1])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"文件内容解析失败：{e}")
    text = _extract_text_from_bytes(filename, data)
    return {"filename": filename, "content": text, "chars": len(text)}


@router.post("/review-document")
async def review_document(context: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response = await get_deepagents_service().execute(
        f"review:review_document:{current_user.id}",
        AgentExecuteRequest(task_type="review", action="review_document", context=context).model_dump(),
    )
    if response.get("status") == "failed":
        # 显式报错，避免前端把“AI 服务失败”误当成“合同无风险点/未识别出内容”
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=response.get("error") or "AI 审查任务执行失败，请稍后重试",
        )
    result = response.get("result")
    if not isinstance(result, dict) or not result:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI 审查未返回结构化结果，请检查模型配置后重试",
        )
    ReviewService(db).create_review_record(
        reviewer_id=current_user.id,
        result=result,
        contract_id=context.get("contract_id"),
        document_type=context.get("document_type"),
    )
    return result


@router.post("/review-document-async")
async def review_document_async(context: dict, current_user: User = Depends(get_current_user)):
    """异步提交审核任务：立即返回 task_key，前端轮询进度。

    审核是分钟级 agent 循环，同步等待容易被浏览器/代理掐断报"请求超时"，
    改为提交后轮询，前端还能展示实时进度。
    """
    if not (context.get("content") or "").strip():
        raise HTTPException(status_code=422, detail="缺少合同正文内容")
    service = get_deepagents_service()
    task_key = f"review:review_document:{current_user.id}:{uuid.uuid4().hex[:8]}"
    request = AgentExecuteRequest(task_type="review", action="review_document", context=context).model_dump()
    snapshot = service.start_execute(task_key, request)
    return {
        "task_key": task_key,
        "status": snapshot.get("status", "running"),
        "poll_url": f"/api/review/tasks/{task_key}",
    }


@router.get("/tasks/{task_key}")
async def get_review_task(
    task_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """轮询审核任务快照：status=completed 时返回完整结构化结果（含已落库的记录 id）。"""
    service = get_deepagents_service()
    task = service.get_task(task_key)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期（服务可能重启过）")
    # 属主校验：task_key 形如 review:review_document:{user_id}:{rand}
    parts = task_key.split(":")
    if len(parts) >= 3 and str(current_user.id) != parts[2]:
        raise HTTPException(status_code=403, detail="无权查看该任务")

    # 完成后幂等落一条审核记录（与同步链路行为一致）
    if task.get("status") == "completed" and not task.get("record_created"):
        result = task.get("result")
        if isinstance(result, dict) and result:
            ctx = task.get("context") or {}
            record = ReviewService(db).create_review_record(
                reviewer_id=current_user.id,
                result=result,
                contract_id=ctx.get("contract_id"),
                document_type=ctx.get("document_type"),
            )
            task_obj = service._tasks.get(task_key)
            if task_obj is not None:
                task_obj.record_created = True
                task_obj.review_record_id = getattr(record, "id", None)
            task = service.get_task(task_key) or task

    # 轮询响应瘦身：合同全文不再随每次轮询回传
    slim = dict(task)
    ctx = slim.get("context") or {}
    if isinstance(ctx, dict) and "content" in ctx:
        slim["context"] = {k: v for k, v in ctx.items() if k != "content"}
    return slim


@router.get("/records")
def list_review_records(
    contract_id: Optional[int] = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    """历史审查记录：默认返回最近 limit 条；传 contract_id 则只看某合同的历史。"""
    records = ReviewService(db).list_records(limit=max(1, min(limit, 100)), contract_id=contract_id)
    return {"status": "success", "total": len(records), "records": [ReviewService.to_dict(r) for r in records]}


@router.post("/apply-suggestion")
async def apply_suggestion(payload: dict, current_user: User = Depends(get_current_user)):  # noqa: ARG001
    """一键修改：把某条审核建议真正应用到对应段落，返回 LLM 改写后的段落文本。

    AIService 是同步客户端，必须经线程池调用（工程红线：async 路由禁止直调同步 SDK）。
    """
    paragraph = str(payload.get("paragraph") or "").strip()
    issue = payload.get("issue") or {}
    description = str(issue.get("description") or "").strip()
    suggestion = str(issue.get("suggestion") or "").strip()
    legal_basis = str(issue.get("legal_basis") or "").strip()
    if not paragraph:
        raise HTTPException(status_code=422, detail="缺少待修改的段落原文")
    if not suggestion and not description:
        raise HTTPException(status_code=422, detail="缺少修改建议/问题描述，无法改写")

    call = await run_in_threadpool(
        get_ai_service().apply_clause_revision,
        paragraph,
        description,
        suggestion,
        legal_basis,
    )
    if not call.get("ok"):
        raise HTTPException(status_code=502, detail=f"AI 改写失败：{call.get('error', '未知错误')}")
    return {
        "revised": call.get("revised", ""),
        "unchanged": call.get("unchanged", False),
    }
