"""一次性统计：从 contract_workflow_runs 取真实起止时间与 execution_time。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.workflow import ContractWorkflowRun  # noqa: E402

db = SessionLocal()
try:
    rows = (
        db.query(ContractWorkflowRun)
        .order_by(ContractWorkflowRun.id.desc())
        .limit(25)
        .all()
    )
    print(f"取到 {len(rows)} 条 workflow run（按 id 倒序）\n")
    print(f"{'id':>4} {'状态':<12}{'execution_time':>16}  起止时间")
    for r in rows:
        st = r.started_at.strftime("%m-%d %H:%M:%S") if r.started_at else "-"
        ct = r.completed_at.strftime("%m-%d %H:%M:%S") if r.completed_at else "-"
        dur = ""
        if r.started_at and r.completed_at:
            secs = (r.completed_at - r.started_at).total_seconds()
            mm, ss = divmod(int(secs), 60)
            dur = f"  [{mm}分{ss}秒]"
        print(f"{r.id:>4} {str(r.status):<12}{str(r.execution_time):>16}  {st} -> {ct}{dur}")
finally:
    db.close()
