import { useCallback, useEffect, useState } from "react";
import {
  FileText,
  Loader2,
  X,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock3,
  Send,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { PageHeader } from "../components/PageHeader";
import {
  getApprovals,
  approveStep,
  rejectStep,
  getApprovalWorkflow,
  type ApprovalStep,
} from "../../lib/api/approvals";

const TABS = [
  { key: "pending", label: "待我审核", cls: "text-amber-700 border-amber-200 bg-amber-50" },
  { key: "approved", label: "已通过", cls: "text-emerald-700 border-emerald-200 bg-emerald-50" },
  { key: "rejected", label: "已驳回", cls: "text-rose-700 border-rose-200 bg-rose-50" },
] as const;

function statusBadge(step: ApprovalStep) {
  const s = step.status || "pending";
  if (s === "approved") return { label: "已通过", cls: "border-emerald-200 bg-emerald-50 text-emerald-700" };
  if (s === "rejected") return { label: "已驳回", cls: "border-rose-200 bg-rose-50 text-rose-700" };
  if (s === "waiting") return { label: "等待前序", cls: "border-slate-200 bg-slate-100 text-slate-600" };
  return { label: "待审核", cls: "border-amber-200 bg-amber-50 text-amber-700" };
}

export function ReviewManagement() {
  const [tab, setTab] = useState<"pending" | "approved" | "rejected">("pending");
  const [items, setItems] = useState<ApprovalStep[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [comment, setComment] = useState("");
  const [acting, setActing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const statusParam = tab === "approved" ? "approved" : tab === "rejected" ? "rejected" : "pending";
      const res = await getApprovals(statusParam, undefined, "my_pending");
      setItems(res.items || []);
    } catch (e: any) {
      setError(e?.message || "加载审批列表失败");
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (step: ApprovalStep) => {
    setDetailLoading(true);
    setComment("");
    try {
      const wfId = step.workflow_public_id || String(step.workflow_id);
      const wf = await getApprovalWorkflow(wfId);
      setDetail({ step, workflow: wf });
    } catch (e: any) {
      setError(e?.message || "加载审批详情失败");
    } finally {
      setDetailLoading(false);
    }
  };

  const doApprove = async () => {
    if (!detail) return;
    setActing(true);
    setError("");
    try {
      await approveStep(detail.step.id, comment || undefined);
      setDetail(null);
      void load();
    } catch (e: any) {
      setError(e?.message || "通过失败");
    } finally {
      setActing(false);
    }
  };

  const doReject = async () => {
    if (!detail) return;
    if (!comment.trim()) {
      setError("驳回时必须填写驳回意见");
      return;
    }
    setActing(true);
    setError("");
    try {
      await rejectStep(detail.step.id, comment.trim());
      setDetail(null);
      void load();
    } catch (e: any) {
      setError(e?.message || "驳回失败");
    } finally {
      setActing(false);
    }
  };

  const contractOf = (step: ApprovalStep) => step.contract || {};

  return (
    <div className="max-w-6xl space-y-8 pb-32 pt-8">
      <PageHeader
        title="审核工作台"
        description="审核员专用：查看待我审核的合同，审阅 AI 分析结果后通过或驳回。"
      />

      {/* Tab */}
      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((t) => {
          const cnt = t.key === tab ? items.length : 0;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                "inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-black transition-colors",
                tab === t.key ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-accent"
              )}
            >
              {t.label}
              <span className={cn("rounded-full px-1.5 py-0.5 text-[9px]", tab === t.key ? "bg-white/25" : "bg-muted")}>
                {cnt}
              </span>
            </button>
          );
        })}
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs font-bold text-rose-700">
          <AlertTriangle className="mr-1.5 inline-block h-3.5 w-3.5" /> {error}
        </div>
      )}

      {loading ? (
        <div className="flex flex-col items-center justify-center rounded-[1.5rem] border border-dashed border-border bg-card/60 px-8 py-16 text-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <div className="mt-4 text-sm font-black text-foreground">正在加载审批列表…</div>
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-[1.5rem] border border-dashed border-border bg-card/60 px-8 py-16 text-center">
          <ShieldCheck className="h-10 w-10 text-muted-foreground/30" />
          <div className="mt-3 text-sm font-black text-foreground">该状态下暂无审批任务</div>
          <div className="mt-1 text-xs font-bold text-muted-foreground">律师提交合同审核后会出现在这里</div>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((step) => {
            const c = contractOf(step);
            const sb = statusBadge(step);
            return (
              <button
                key={step.id}
                onClick={() => void openDetail(step)}
                className="flex w-full items-center gap-4 rounded-2xl border border-border bg-card p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
              >
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/5 text-primary">
                  <FileText className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-black text-foreground">{c.title || "未命名合同"}</span>
                    {step.workflow_risk_level && (
                      <span className="rounded-full border border-primary/20 bg-primary/5 px-2 py-0.5 text-[9px] font-black text-primary">
                        风险 {step.workflow_risk_level}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] font-bold text-muted-foreground">
                    <span>{c.contract_number || c.contract_code || "未编号"}</span>
                    {step.submitted_by_name && <span>提交：{step.submitted_by_name}</span>}
                    {step.created_at && <span>时间：{new Date(step.created_at).toLocaleString("zh-CN")}</span>}
                  </div>
                </div>
                <span className={cn("shrink-0 rounded-full border px-3 py-1 text-[10px] font-black", sb.cls)}>
                  {sb.label}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* 详情弹窗 */}
      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-[1.5rem] border border-border bg-card shadow-xl">
            <div className="flex items-center justify-between border-b border-border px-6 py-4">
              <div className="flex items-center gap-2 text-sm font-black text-foreground">
                <ShieldCheck className="h-4 w-4 text-primary" /> 审批详情
              </div>
              <button onClick={() => setDetail(null)} className="text-muted-foreground hover:text-rose-600">
                <X className="h-4 w-4" />
              </button>
            </div>

            {detailLoading ? (
              <div className="flex flex-1 items-center justify-center p-10">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto px-6 py-5">
                {/* 合同信息 */}
                <div className="rounded-xl border border-border bg-secondary/30 p-4">
                  <div className="text-sm font-black text-foreground">{contractOf(detail.step).title || "未命名合同"}</div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] font-bold text-muted-foreground">
                    <span>编号：{contractOf(detail.step).contract_number || contractOf(detail.step).contract_code || "—"}</span>
                    <span>提交人：{detail.step.submitted_by_name || "—"}</span>
                    {detail.step.workflow_risk_level && <span>风险：{detail.step.workflow_risk_level}</span>}
                  </div>
                </div>

                {/* AI 审核摘要 */}
                {detail.workflow?.summary && (
                  <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                    <div className="mb-1 text-[10px] font-black tracking-widest text-amber-700">AI 审核摘要</div>
                    <div className="text-xs font-medium leading-6 text-amber-950">{detail.workflow.summary}</div>
                  </div>
                )}

                {/* 合同正文 */}
                <div className="mt-3">
                  <div className="mb-1 text-[10px] font-black tracking-widest text-muted-foreground">合同正文</div>
                  <div className="max-h-52 overflow-y-auto whitespace-pre-wrap rounded-xl border border-border bg-background p-4 text-xs font-medium leading-6 text-foreground">
                    {detail.step.contract?.content || (detail.workflow?.contract?.content ?? "（暂无正文内容）")}
                  </div>
                </div>

                {/* 审批操作 */}
                {detail.step.status === "pending" ? (
                  <div className="mt-4">
                    <label className="mb-1 block text-[10px] font-black tracking-widest text-muted-foreground">
                      审批意见（驳回时必填）
                    </label>
                    <textarea
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      rows={3}
                      placeholder="填写通过说明或驳回原因…"
                      className="w-full resize-none rounded-xl border border-border bg-secondary/30 px-3 py-2 text-xs font-medium leading-5 text-foreground outline-none focus:border-primary/40"
                    />
                    <div className="mt-3 flex justify-end gap-2">
                      <button
                        onClick={() => void doReject()}
                        disabled={acting}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-black text-rose-700 transition-colors hover:bg-rose-100 disabled:opacity-50"
                      >
                        {acting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                        驳回
                      </button>
                      <button
                        onClick={() => void doApprove()}
                        disabled={acting}
                        className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-black text-primary-foreground shadow-sm transition-all hover:shadow-md disabled:opacity-50"
                      >
                        {acting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                        通过
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 rounded-xl border border-border bg-secondary/30 p-4 text-xs font-bold text-muted-foreground">
                    <Clock3 className="mr-1.5 inline-block h-3.5 w-3.5" />
                    该任务已处理（{statusBadge(detail.step).label}）
                    {detail.step.comments && <div className="mt-2 text-foreground/80">意见：{detail.step.comments}</div>}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
