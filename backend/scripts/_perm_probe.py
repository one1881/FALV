"""权限改动验证：确认子代理只能读到分配给自己的 skill。

2026-09-10 P0 改造配套验证。预期：
  /skills/drafting-skill/SKILL.md         -> 可读（分配给起草）
  /skills/legal-risk-check-skill/SKILL.md -> permission denied（未分配给起草）
"""
import asyncio
import uuid

from app.a2a_servers import agent_runtime as rt


async def probe(agent, target: str) -> str:
    cfg = {"configurable": {"thread_id": "permprobe-" + uuid.uuid4().hex[:8]}}
    prompt = (
        f"只做一件事：调用 read_file 读取 {target}，"
        "然后把工具返回的原始内容（或错误信息）原样贴出来，不要做别的。"
    )
    res = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]}, config=cfg)
    msgs = res.get("messages") if isinstance(res, dict) else (res.model_dump().get("messages") or [])
    for m in msgs:
        if type(m).__name__ == "ToolMessage":
            return str(getattr(m, "content", ""))
    return "(未产生工具调用)"


async def main() -> None:
    agent = rt._get_agent("drafting")
    for target in [
        "/skills/drafting-skill/SKILL.md",
        "/skills/legal-risk-check-skill/SKILL.md",
    ]:
        out = await probe(agent, target)
        flat = out[:200].replace("\n", " ")
        if "denied" in out.lower():
            verdict = "已被拒绝 ✓"
        elif len(out) > 300:
            verdict = "可读 ✓"
        else:
            verdict = "未知"
        print(f"[{verdict}] {target}")
        print(f"          返回: {flat}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
