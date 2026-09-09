import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router";
import {
  ArrowLeft,
  Save,
  ShieldCheck,
  AlertTriangle,
  CheckCircle,
  CheckCircle2,
  Send,
  Loader2,
  Scale,
  BookOpen,
  Plus,
  Trash2,
  Edit3,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { PageHeader } from "../components/PageHeader";
import { type ReviewDocumentResponse, type ReviewIssue } from "../../lib/api/review";
import { createContractFromContent, submitContractApproval } from "../../lib/api/contracts";

const SEVERITY_OPTIONS = [
  { value: "high", label: "高风险", cls: "bg-red-500 text-white border border-red-600" },
  { value: "medium", label: "中风险", cls: "bg-amber-500 text-white border border-amber-600" },
  { value: "low", label: "提示", cls: "bg-slate-200 text-slate-700 border border-slate-400" },
];

function severityMeta(value?: string) {
  return SEVERITY_OPTIONS.find((s) => s.value === value) || SEVERITY_OPTIONS[2];
}

export function ContractReview() {
  const navigate = useNavigate();
  const location = useLocation();
  const [result, setResult] = useState<ReviewDocumentResponse | null>(null);
  const [title, setTitle] = useState("合同审核结果");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [resolved, setResolved] = useState<Set<string>>(new Set());
  const [expandedIssue, setExpandedIssue] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [submittedInfo, setSubmittedInfo] = useState<{ id: number; workflowId?: string } | null>(null);
  const [submitError, setSubmitError] = useState("");
  const [contractId, setContractId] = useState<number | null>(null);

  useEffect(() => {
    const state = location.state as { result?: ReviewDocumentResponse; title?: string; content?: string; contractId?: number } | null;
    if (state?.result) {
      setResult(state.result);
      if (state.title) setTitle(state.title);
      if (state.content) setContent(state.content);
      if (state.contractId) setContractId(state.contractId);
      sessionStorage.setItem("lastReviewResult", JSON.stringify(state.result));
      if (state.title) sessionStorage.setItem("lastReviewTitle", state.title);
      if (state.content) sessionStorage.setItem("lastReviewContent", state.content);
      if (state.contractId) sessionStorage.setItem("lastReviewContractId", String(state.contractId));
      return;
    }
    const stored = sessionStorage.getItem("lastReviewResult");
    const storedTitle = sessionStorage.getItem("lastReviewTitle");
    const storedContent = sessionStorage.getItem("lastReviewContent");
    const storedContractId = sessionStorage.getItem("lastReviewContractId");
    if (stored) {
      try { setResult(JSON.parse(stored)); } catch { /* ignore */ }
    }
    if (storedTitle) setTitle(storedTitle);
    if (storedContent) setContent(storedContent);
    if (storedContractId) setContractId(Number(storedContractId));
  }, [location.state]);

  const updateIssue = (idx: number, patch: Partial<ReviewIssue>) => {
    if (!result) return;
    const next = { ...result };
    const issues = [...(next.issues || [])];
    issues[idx] = { ...issues[idx], ...patch };
    next.issues = issues;
    setResult(next);
  };

  const removeIssue = (idx: number) => {
    if (!result) return;
    const next = { ...result };
    next.issues = (next.issues || []).filter((_, i) => i !== idx);
    setResult(next);
  };

  const addIssue = () => {
    if (!result) return;
    const next = { ...result };
    next.issues = [...(next.issues || []), { type: "custom", severity: "medium", clause: "", description: "", suggestion: "" }];
    setResult(next);
  };

  const handleSave = () => {
    if (!result) return;
    sessionStorage.setItem("lastReviewResult", JSON.stringify(result));
    setSavedAt(new Date().toLocaleTimeString("zh-CN"));
    setTimeout(() => setSavedAt(null), 2000);
  };

  const handleSubmitApproval = async () => {
    if (!content.trim()) {
      setSubmitError("合同正文为空，无法提交审核");
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    try {
      let targetId = contractId;
      if (!targetId) {
        // 没带合同 ID（旧入口粘贴的文本）才新建草稿合同
        const contract = await createContractFromContent({
          title: title === "合同审核结果" ? `合同审核-${new Date().toISOString().slice(0, 10)}` : title,
          contract_type: "contract",
          content: content.trim(),
        });
        targetId = contract.id;
      }
      const resp = await submitContractApproval(targetId, {
        summary: result?.suggestions?.join("；") || undefined,
        risk_score: typeof result?.overall_score === "number" ? result.overall_score : undefined,
        risk_level: result?.review_status || undefined,
      });
      setSubmittedInfo({ id: targetId, workflowId: resp?.workflow?.workflow_id || resp?.workflow_id });
    } catch (e: any) {
      setSubmitError(e?.message || "提交审核失败，请确认后端已启动");
    } finally {
      setSubmitting(false);
    }
  };

  if (!result) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center gap-4 pb-20 pt-8 text-center">
        <ShieldCheck className="h-12 w-12 text-muted-foreground/30" />
        <div className="text-sm font-bold text-muted-foreground">没有可显示的审核结果，请先上传合同并完成 AI 审核。</div>
        <button onClick={() => navigate("/approvals")} className="inline-flex items-center gap-2 rounded-2xl bg-primary px-5 py-3 text-xs font-black text-primary-foreground shadow-sm hover:opacity-90">
          去审核合同
        </button>
      </div>
    );
  }

  const issues = result.issues || [];
  const overallScore = result.overall_score ?? result.dimensions?.overall?.score;
  const status = result.review_status || "completed";
  const statusMeta = status === "pass" || status === "approved"
    ? { label: "已通过", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" }
    : status === "warning" || status === "needs_revision"
    ? { label: "需修改", cls: "bg-amber-50 text-amber-700 border-amber-200" }
    : { label: "审核完成", cls: "bg-sky-50 text-sky-700 border-sky-200" };

  const paragraphs = content.split(/\n+/).map((p) => p.trim()).filter(Boolean);

  const matchIssue = (issue: ReviewIssue, text: string, paraIndex: number) => {
    const clause = (issue.clause || "").trim();
    if (!clause) return false;
    if (/^\d+$/.test(clause)) return Number(clause) === paraIndex + 1;
    return text.includes(clause) || clause.includes(text.slice(0, 10));
  };
  const issuesOfParagraph = (text: string, paraIndex: number) =>
    issues.filter((it) => matchIssue(it, text, paraIndex));

  const toggleResolved = (key: string) => {
    setResolved((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleExpand = (key: string) => {
    setExpandedIssue((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="max-w-7xl space-y-8 pb-20 pt-8">
      <PageHeader
        title={title}
        description="逐段展示合同全文，问题条款红色标注并给出修改建议，可直接编辑并确认修改。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => navigate("/approvals")} className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-card px-4 py-2 text-xs font-black text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
              <ArrowLeft className="h-3.5 w-3.5" /> 返回审核
            </button>
            <button onClick={handleSave} className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-card px-4 py-2 text-xs font-black text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
              <Save className="h-4 w-4" /> 保存修改
            </button>
            {submittedInfo ? (
              <span className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-black text-emerald-700">
                <CheckCircle2 className="h-4 w-4" /> 已提交审核{submittedInfo.workflowId ? ` · ${submittedInfo.workflowId}` : ""}
              </span>
            ) : (
              <button onClick={() => void handleSubmitApproval()} disabled={submitting} className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-black text-primary-foreground shadow-sm transition-all hover:shadow-md disabled:opacity-50">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {submitting ? "提交中…" : "提交审核"}
              </button>
            )}
          </div>
        }
      />
      {submitError && (
        <div className="inline-flex items-center gap-1.5 rounded-xl border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-700">
          <AlertTriangle className="h-3.5 w-3.5" /> {submitError}
        </div>
      )}
      {savedAt && (
        <div className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700">
          <CheckCircle className="h-3.5 w-3.5" /> 已保存（{savedAt}）
        </div>
      )}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-[1.5rem] border border-border bg-card p-5 shadow-sm">
          <div className="text-3xl font-black text-primary">{overallScore ?? "—"}</div>
          <div className="mt-1 text-[10px] font-black tracking-widest text-muted-foreground">综合评分</div>
        </div>
        <div className={cn("rounded-[1.5rem] border p-5 shadow-sm", statusMeta.cls)}>
          <div className="text-lg font-black">{statusMeta.label}</div>
          <div className="mt-1 text-[10px] font-black tracking-widest opacity-70">审核状态</div>
        </div>
        <div className="rounded-[1.5rem] border border-border bg-card p-5 shadow-sm">
          <div className="text-3xl font-black text-foreground">{issues.length}</div>
          <div className="mt-1 text-[10px] font-black tracking-widest text-muted-foreground">待修改点</div>
        </div>
        <div className="rounded-[1.5rem] border border-border bg-card p-5 shadow-sm">
          <div className="text-3xl font-black text-foreground">
            {(result.suggestions?.length || 0) + issues.length}
          </div>
          <div className="mt-1 text-[10px] font-black tracking-widest text-muted-foreground">分析条目</div>
        </div>
      </section>

      {paragraphs.length > 0 && (
        <section className="rounded-[1.75rem] border border-border bg-card p-6 shadow-sm">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-black text-foreground">合同全文审阅</h2>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-black text-muted-foreground">共 {paragraphs.length} 段 · 标注 {issues.length} 处问题</span>
              <button
                onClick={() => setResolved((prev) => {
                  const next = new Set(prev);
                  paragraphs.forEach((_p, pIdx) => {
                    issuesOfParagraph(_p, pIdx).forEach((_it, iIdx) => next.add(`${pIdx}-${iIdx}`));
                  });
                  const matchedIdx = new Set<number>();
                  paragraphs.forEach((_p, pIdx) => {
                    issuesOfParagraph(_p, pIdx).forEach((_it) => {
                      const i = issues.indexOf(_it);
                      if (i >= 0) matchedIdx.add(i);
                    });
                  });
                  issues.forEach((_it, i) => {
                    if (!matchedIdx.has(i)) next.add(`unmatched-${i}`);
                  });
                  return next;
                })}
                disabled={issues.length === 0}
                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-[10px] font-black text-emerald-700 transition-colors hover:bg-emerald-100 disabled:opacity-40"
              >
                <CheckCircle2 className="h-3 w-3" /> 一键修改所有
              </button>
            </div>
          </div>

          <div>
            {paragraphs.map((para, pIdx) => {
              const paraIssues = issuesOfParagraph(para, pIdx);
              const hasIssue = paraIssues.length > 0;
              return (
                <div key={pIdx} className={cn("py-2.5", pIdx > 0 && "border-t border-border/40")}>
                  <div className="flex items-start gap-3 px-2">
                    <span className={cn("mt-0.5 inline-flex h-5 w-8 shrink-0 items-center justify-center rounded-md text-[10px] font-black",
                      hasIssue ? paraIssues.every((_it, i) => resolved.has(`${pIdx}-${i}`)) ? "bg-emerald-500 text-white" : "bg-rose-500 text-white" : "bg-secondary text-muted-foreground")}>
                      {pIdx + 1}
                    </span>
                    <textarea
                      value={para}
                      onChange={(e) => {
                        const newParas = paragraphs.slice();
                        newParas[pIdx] = e.target.value;
                        setContent(newParas.join("\n"));
                      }}
                      rows={Math.max(1, Math.ceil(para.length / 60))}
                      disabled={hasIssue && paraIssues.every((_it, i) => resolved.has(`${pIdx}-${i}`))}
                      className={cn("w-full resize-none border-0 bg-transparent px-1 py-0 text-sm leading-7 outline-none focus:bg-yellow-50/40 focus:ring-1 focus:ring-primary/20 disabled:cursor-not-allowed",
                        hasIssue ? paraIssues.every((_it, i) => resolved.has(`${pIdx}-${i}`)) ? "font-black text-emerald-900 line-through decoration-emerald-400/50" : "font-black text-rose-950" : "font-medium text-foreground")}
                    />
                  </div>

                  {hasIssue && paraIssues.map((issue, iIdx) => {
                    const gIdx = issues.indexOf(issue);
                    const key = `${pIdx}-${iIdx}`;
                    const open = expandedIssue.has(key);
                    const done = resolved.has(key);
                    const meta = severityMeta(issue.severity);
                    return (
                      <div key={key} className="mt-2 ml-[44px]">
                        {!open && (
                          <button onClick={() => toggleExpand(key)} className={cn("flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-[11px] font-black transition-colors",
                            done ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100")}>
                            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                            <span className="truncate">
                              {done ? `已一键修改：${issue.suggestion || issue.description || ""}` : `此条款存在 1 处问题：${issue.description || "（未描述问题）"}`}
                            </span>
                            <span className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-full border border-rose-300 bg-card px-2.5 py-0.5 text-[10px] font-black text-rose-700">
                              展开修改建议 <ChevronDown className="h-3 w-3" />
                            </span>
                          </button>
                        )}

                        {open && (
                          <div className={cn("rounded-2xl border p-3.5 transition-colors", done ? "border-emerald-300 bg-emerald-50/60" : "border-amber-200 bg-amber-50/50")}>
                            <div className="mb-2.5 flex flex-wrap items-center gap-2">
                              <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-black", meta.cls)}>{meta.label}</span>
                              <span className="text-[10px] font-black tracking-widest text-muted-foreground">段内问题 {iIdx + 1}</span>
                              {done ? (
                                <span className="ml-auto inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-emerald-500 px-3 py-1 text-[10px] font-black text-white">
                                  <CheckCircle className="h-3 w-3" /> 已一键修改
                                </span>
                              ) : (
                                <>
                                  <button onClick={() => toggleResolved(key)} className="ml-auto inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-emerald-50 px-3 py-1 text-[10px] font-black text-emerald-700 transition-colors hover:bg-emerald-100">
                                    <CheckCircle className="h-3 w-3" /> 一键修改
                                  </button>
                                  <button onClick={() => toggleExpand(key)} className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-3 py-1 text-[10px] font-black text-muted-foreground transition-colors hover:bg-accent">
                                    <ChevronUp className="h-3 w-3" /> 收起
                                  </button>
                                </>
                              )}
                            </div>
                            <div className="space-y-2">
                              <div>
                                <div className="mb-0.5 flex items-center gap-1 text-[9px] font-black tracking-widest text-rose-600">
                                  <Scale className="h-3 w-3" /> 理由
                                </div>
                                <textarea value={issue.description} onChange={(e) => updateIssue(gIdx, { description: e.target.value })} rows={2} disabled={done} placeholder={issue.description ? undefined : "问题描述（理由）"} className="w-full resize-none rounded-md border border-rose-200 bg-rose-50/40 px-2 py-1.5 text-xs font-bold leading-5 text-rose-950 outline-none placeholder:font-medium placeholder:text-rose-400 focus:border-rose-400 focus:bg-white disabled:opacity-60" />
                              </div>
                              <div>
                                <div className="mb-0.5 flex items-center gap-1 text-[9px] font-black tracking-widest text-sky-700">
                                  <BookOpen className="h-3 w-3" /> 法律依据
                                </div>
                                <textarea value={issue.legal_basis ?? ""} onChange={(e) => updateIssue(gIdx, { legal_basis: e.target.value })} rows={2} disabled={done} placeholder={issue.legal_basis ? undefined : "引用的法条/合同条款"} className="w-full resize-none rounded-md border border-sky-200 bg-sky-50/40 px-2 py-1.5 text-xs font-medium leading-5 text-sky-950 outline-none placeholder:font-medium placeholder:text-sky-400 focus:border-sky-400 focus:bg-white disabled:opacity-60" />
                              </div>
                              <div>
                                <div className="mb-0.5 flex items-center gap-1 text-[9px] font-black tracking-widest text-orange-700">
                                  <Edit3 className="h-3 w-3" /> 修改建议
                                </div>
                                <textarea value={issue.suggestion ?? ""} onChange={(e) => updateIssue(gIdx, { suggestion: e.target.value })} rows={2} disabled={done} placeholder={issue.suggestion ? undefined : "AI 未生成修改建议，请根据理由与法律依据手动补充…"} className="w-full resize-none rounded-md border border-orange-200 bg-orange-50/40 px-2 py-1.5 text-xs font-bold leading-5 text-orange-950 outline-none placeholder:font-medium placeholder:text-orange-400 focus:border-orange-400 focus:bg-white disabled:opacity-60" />
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}

            {(() => {
              const matchedIdx = new Set<number>();
              paragraphs.forEach((_p, pIdx) => {
                issuesOfParagraph(_p, pIdx).forEach((_it) => {
                  const i = issues.indexOf(_it);
                  if (i >= 0) matchedIdx.add(i);
                });
              });
              const unmatched = issues.filter((_, i) => !matchedIdx.has(i));
              if (unmatched.length === 0) return null;
              return (
                <div className="mt-6 border-t-2 border-dashed border-amber-300 pt-5">
                  <div className="mb-3 flex items-center gap-2">
                    <AlertTriangle className="h-3.5 w-3.5 text-amber-700" />
                    <h3 className="text-xs font-black text-amber-900">待处理建议（未关联到正文段落 · {unmatched.length} 条）</h3>
                  </div>
                  <div className="space-y-3">
                    {unmatched.map((issue, uIdx) => {
                      const gIdx = issues.indexOf(issue);
                      const key = `unmatched-${gIdx}`;
                      const done = resolved.has(key);
                      const meta = severityMeta(issue.severity);
                      return (
                        <div key={key} className={cn("rounded-2xl border p-4 transition-colors", done ? "border-emerald-300 bg-emerald-50/60" : "border-amber-200 bg-amber-50/50")}>
                          <div className="mb-2.5 flex flex-wrap items-center gap-2">
                            <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-black", meta.cls)}>{meta.label}</span>
                            <span className="text-[10px] font-black tracking-widest text-muted-foreground">未匹配问题 {uIdx + 1}</span>
                            {issue.clause && (
                              <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-black text-muted-foreground">涉及：{issue.clause}</span>
                            )}
                            {done ? (
                              <span className="ml-auto inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-emerald-500 px-3 py-1 text-[10px] font-black text-white">
                                <CheckCircle className="h-3 w-3" /> 已一键修改
                              </span>
                            ) : (
                              <button onClick={() => toggleResolved(key)} className="ml-auto inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-emerald-50 px-3 py-1 text-[10px] font-black text-emerald-700 transition-colors hover:bg-emerald-100">
                                <CheckCircle className="h-3 w-3" /> 一键修改
                              </button>
                            )}
                          </div>
                          <div className="space-y-2">
                            <div>
                              <div className="mb-0.5 flex items-center gap-1 text-[9px] font-black tracking-widest text-rose-600">
                                <Scale className="h-3 w-3" /> 理由
                              </div>
                              <textarea value={issue.description} onChange={(e) => updateIssue(gIdx, { description: e.target.value })} rows={1} disabled={done} className="w-full resize-none rounded-md border border-rose-200 bg-rose-50/40 px-2 py-1 text-xs font-bold leading-5 text-rose-950 outline-none focus:border-rose-400 focus:bg-white disabled:opacity-60" />
                            </div>
                            {issue.legal_basis && (
                              <div>
                                <div className="mb-0.5 flex items-center gap-1 text-[9px] font-black tracking-widest text-sky-700">
                                  <BookOpen className="h-3 w-3" /> 法律依据
                                </div>
                                <p className="rounded-md border border-sky-200 bg-sky-50/40 px-2 py-1 text-xs font-medium leading-5 text-sky-950">{issue.legal_basis}</p>
                              </div>
                            )}
                            <div>
                              <div className="mb-0.5 flex items-center gap-1 text-[9px] font-black tracking-widest text-orange-700">
                                <Edit3 className="h-3 w-3" /> 修改建议
                              </div>
                              <textarea value={issue.suggestion} onChange={(e) => updateIssue(gIdx, { suggestion: e.target.value })} rows={1} disabled={done} className="w-full resize-none rounded-md border border-orange-200 bg-orange-50/40 px-2 py-1 text-xs font-bold leading-5 text-orange-950 outline-none focus:border-orange-400 focus:bg-white disabled:opacity-60" />
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}
          </div>
        </section>
      )}

      {result.suggestions && result.suggestions.length > 0 && (
        <section className="rounded-[1.75rem] border border-border bg-card p-6 shadow-sm">
          <h2 className="mb-4 text-sm font-black text-foreground">整体优化建议</h2>
          <ul className="space-y-2">
            {result.suggestions.map((s, i) => (
              <li key={i} className="flex gap-2 rounded-xl border border-border bg-secondary/30 px-4 py-3 text-xs font-medium text-foreground">
                <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />{s}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
