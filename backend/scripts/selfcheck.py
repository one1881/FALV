#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一律通（YI LV TONG）后端启动自检脚本
====================================
目的：在「真正跑业务」之前，确定性地回答“能不能出结果”。

检查项：
  1. 依赖导入：fastapi / deepagents / langchain_openai / openai / sqlalchemy
     —— deepagents 与 langchain_openai 是 deepagents_service 的顶层依赖，
        缺失会导致后端 import 阶段直接崩溃（main.py 顶层 import contracts）。
  2. 路由模块可加载：contracts / drafting / review / agent
     —— 这些模块在文件顶部 import deepagents_service，是最容易在启动时炸的地方。
  3. 模型配置：主模型 / QWEN_VL_API_KEY / QWEN_VL_MODEL
  4. 数据库连通：DATABASE_URL（pg8000）
  5. 主模型真实可达：发起一次最小 chat.completions 调用（决定“出结果”与否）
  6. deepagents skill 结构：必须是 skills/<name>/SKILL.md 目录形式
     —— 散装 .md 会被 deepagents 静默忽略，接口仍返回 200，
        但起草/审核内容会退化为占位骨架，是最难发现的降级。
  7. 三大板块出结果能力判定

用法：
  cd backend
  python scripts/selfcheck.py
退出码：全部通过 0；存在阻断项 1；仅存在非阻断告警 2。
"""
import os
import sys
import traceback

# 让脚本无论在哪个目录执行都能 import app
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(HERE)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"


def hr(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def section_imports():
    hr("1) 依赖导入")
    mods = ["fastapi", "uvicorn", "sqlalchemy", "openai", "deepagents", "langchain_openai"]
    results = {}
    for m in mods:
        try:
            __import__(m)
            print(f"  {PASS}  {m}")
            results[m] = True
        except Exception as e:
            print(f"  {FAIL}  {m}  -> {type(e).__name__}: {e}")
            results[m] = False
    return results


def section_routers():
    hr("2) 路由模块可加载（顶层 deepagents 依赖）")
    routers = ["auth", "contracts", "drafting", "review", "agent", "litigation", "approvals", "customers", "stats", "workspace", "mcp"]
    ok = True
    for r in routers:
        try:
            __import__(f"app.routes.{r}")
            print(f"  {PASS}  app.routes.{r}")
        except Exception as e:
            print(f"  {FAIL}  app.routes.{r}  -> {type(e).__name__}: {e}")
            ok = False
    return ok


def load_settings():
    try:
        from app.core.config import settings
        return settings
    except Exception as e:
        print(f"  {FAIL}  无法加载 settings: {e}")
        return None


def section_keys(settings):
    hr("3) 模型配置（Key / 模型名）")
    if settings is None:
        return {}
    keys = ["QWEN_API_KEY", "QWEN_MODEL", "QWEN_VL_API_KEY", "QWEN_VL_MODEL", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"]
    # 模型优先级：QWEN_* 为主，DEEPSEEK_* 仅作兼容回退
    out = {}
    for k in keys:
        v = getattr(settings, k, None)
        if v and str(v).strip():
            # 只显示长度，绝不打印明文
            print(f"  {PASS}  {k}  (已配置, 长度={len(str(v).strip())})")
            out[k] = True
        else:
            print(f"  {FAIL}  {k}  未配置/为空")
            out[k] = False
    return out


def section_db(settings):
    hr("4) 数据库连通（DATABASE_URL）")
    if settings is None:
        return False
    url = getattr(settings, "DATABASE_URL", None)
    if not url:
        print(f"  {FAIL}  DATABASE_URL 未配置")
        return False
    try:
        from sqlalchemy import create_engine, text
        eng = create_engine(url, pool_pre_ping=True)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        print(f"  {PASS}  PostgreSQL 连通 ({str(url).split('@')[-1] if '@' in str(url) else url})")
        return True
    except Exception as e:
        print(f"  {FAIL}  数据库不可达 -> {type(e).__name__}: {str(e)[:160]}")
        return False


def section_deepseek(settings):
    hr("5) 主模型真实可达（最小 chat 调用）")
    if settings is None:
        return (False, "")
    key = getattr(settings, "primary_llm_api_key", None) or getattr(settings, "QWEN_API_KEY", None) or getattr(settings, "DEEPSEEK_API_KEY", None)
    model = getattr(settings, "primary_llm_model", None) or getattr(settings, "QWEN_MODEL", None) or getattr(settings, "DEEPSEEK_MODEL", None)
    if not key or not model:
        print(f"  {FAIL}  Key 或 Model 缺失，跳过真实调用")
        return (False, "")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "请只回复两个字：正常"}],
            max_tokens=60,
        )
        content = (r.choices[0].message.content or "").strip()
        if content:
            print(f"  {PASS}  主模型调用成功，模型={model}，回包='{content}'")
            return (True, content)
        print(f"  {FAIL}  主模型返回空内容")
        return (False, "")
    except Exception as e:
        print(f"  {FAIL}  主模型调用失败 -> {type(e).__name__}: {str(e)[:200]}")
        return (False, "")


def section_skills():
    """校验 deepagents skill 目录结构。

    这是最隐蔽的失败点：deepagents 0.7.11 只识别「含 SKILL.md 的目录」，
    散装 .md 会被静默忽略——不报错、不告警，但起草/审核的产出会退化成占位骨架。
    """
    hr("6) deepagents skill 结构（静默失败点）")
    skill_dir = os.path.join(BACKEND_ROOT, "skills")
    if not os.path.isdir(skill_dir):
        print(f"  {FAIL}  skills 目录不存在: {skill_dir}")
        return False

    valid, invalid_dirs, stray_md = [], [], []
    for name in sorted(os.listdir(skill_dir)):
        if name.startswith("_"):  # 归档目录（_archive 等）不参与 skill 检查
            continue
        path = os.path.join(skill_dir, name)
        if os.path.isdir(path):
            (valid if os.path.isfile(os.path.join(path, "SKILL.md")) else invalid_dirs).append(name)
        elif name.endswith(".md"):
            stray_md.append(name)

    ok = True
    if valid:
        print(f"  {PASS}  可加载 skill {len(valid)} 个: {', '.join(valid)}")
    else:
        print(f"  {FAIL}  没有任何可加载 skill（deepagents 需要 skills/<name>/SKILL.md）")
        ok = False
    if invalid_dirs:
        print(f"  {WARN}  以下目录缺 SKILL.md，将被忽略: {', '.join(invalid_dirs)}")
    if stray_md:
        print(f"  {WARN}  顶层散装 .md 会被静默忽略，需转为目录: {', '.join(stray_md)}")

    # 同时校验代码侧是否按目录方式收集（避免只改目录不改代码 → skill 列表变空）
    try:
        from app.services.deepagents_service import DeepAgentsService
        collected = DeepAgentsService._build_skill_documents(
            type("S", (), {"_skill_dir": lambda self: __import__("pathlib").Path(skill_dir)})()
        )
        if len(collected) == len(valid) and collected:
            print(f"  {PASS}  代码侧收集到 {len(collected)} 个 skill，与磁盘一致")
        else:
            print(f"  {FAIL}  代码侧收集到 {len(collected)} 个，磁盘有 {len(valid)} 个 → 收集逻辑与目录结构不匹配")
            ok = False
    except Exception as e:
        print(f"  {WARN}  无法校验代码侧收集逻辑 -> {type(e).__name__}: {str(e)[:120]}")
    return ok


def section_verdict(imports, routers_ok, keys, db_ok, ds_reach, skills_ok=True):
    hr("7) 三大板块出结果能力判定")
    # 路由模块能否全部加载 = 后端能否启动
    if not routers_ok:
        print(f"  {FAIL}  路由模块无法全部加载（见第 2 项），后端无法启动，三大板块均无法经 HTTP 出结果。")
        print("\n--- 小结 ---")
        print("  🔴 存在阻断项（路由 import 失败），请先补齐缺失依赖后重跑。")
        return 1
    deepagents_ok = imports.get("deepagents", False) and imports.get("langchain_openai", False)
    key_ok = keys.get("QWEN_API_KEY", False) and keys.get("QWEN_MODEL", False)
    ai_chain = deepagents_ok and key_ok and ds_reach[0]

    # 起草 / 审核：强依赖主模型 + deepagents，无兜底
    if ai_chain and skills_ok:
        print(f"  {PASS}  【起草】合同 AI 生成  → 可出真实结果")
        print(f"  {PASS}  【审核】多智能体审查  → 可出真实结果")
    elif ai_chain and not skills_ok:
        print(f"  {WARN}  【起草/审核】AI 链路正常，但 skill 未被正确加载（见第 6 项）")
        print(f"        → 接口会返回 200，但内容会退化为占位骨架，属静默降级，务必修复")
    else:
        reasons = []
        if not deepagents_ok:
            reasons.append("deepagents/langchain_openai 未安装(后端起不来)")
        if not key_ok:
            reasons.append("Qwen Key/Model 缺失")
        if not ds_reach[0]:
            reasons.append("Qwen 网络不可达")
        print(f"  {FAIL}  【起草/审核】强依赖 AI 链路，当前无法出结果：{'; '.join(reasons)}")

    # 诉讼：主模型成功出 AI 结果；失败也有规则兜底（永远非空）
    if ds_reach[0]:
        print(f"  {PASS}  【诉讼】受理分析  → 可出真实 AI 结果，且 LLM 失败时仍有规则兜底")
    else:
        print(f"  {WARN}  【诉讼】主模型不可达，但内置规则兜底 _rule_assess_acceptance 仍可返回非空受理结论（降级）")

    # 纯数据类（列表/详情/审批 CRUD）依赖数据库
    if db_ok:
        print(f"  {PASS}  数据类操作（列表/详情/建合同/提交审批/审批通过驳回/诉讼受理 CRUD）依赖 PostgreSQL，当前可达")
    else:
        print(f"  {FAIL}  数据类操作依赖 PostgreSQL，当前不可达 → 页面可开但增删查改会报错")

    print("\n--- 小结 ---")
    if ai_chain and db_ok and skills_ok:
        print("  🟢 三大板块均可跑出结果（AI 真实生成 + 数据持久化）。")
        return 0
    if ai_chain and db_ok and not skills_ok:
        print("  🟡 链路通但 skill 未加载：接口 200 而内容为占位骨架，请先修复第 6 项。")
        return 2
    if (not ai_chain) and db_ok:
        print("  🟡 数据层可用；AI 出结果被阻断（依赖缺失或主模型不可达），诉讼仍有兜底。")
        return 2
    print("  🔴 存在阻断项，请先解决上方 FAIL。")
    return 1


def main():
    print("========== 一律通后端启动自检 ==========")
    imports = section_imports()
    routers_ok = section_routers()
    settings = load_settings()
    keys = section_keys(settings)
    db_ok = section_db(settings)
    ds_reach = section_deepseek(settings)
    skills_ok = section_skills()
    code = section_verdict(imports, routers_ok, keys, db_ok, ds_reach, skills_ok)
    sys.exit(code)


if __name__ == "__main__":
    main()
