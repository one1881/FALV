import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router";

/** 松散抽取 JSON 文本里指定字符串字段（容忍裸换行等非法 JSON），找不到返回空串 */
function extractJsonStringFieldLoose(text: string, field: string): string {
  const m = text.match(new RegExp(`"${field}"\\s*:\\s*"`));
  if (!m || m.index === undefined) return "";
  let i = m.index + m[0].length;
  let out = "";
  while (i < text.length) {
    const ch = text[i];
    if (ch === '"') break; // 未转义收尾引号（\" 已被转义分支整体消费）
    if (ch === "\\" && i + 1 < text.length) {
      const nxt = text[i + 1];
      out += nxt === "n" ? "\n" : nxt === "r" ? "\r" : nxt === "t" ? "\t" : nxt;
      i += 2;
      continue;
    }
    out += ch === "\n" || ch === "\r" ? "\n" : ch;
    i += 1;
  }
  return out;
}

/**
 * 兜底解包：历史合同可能把 {"content": {...}} 整体序列化存成了正文，
 * 导致编辑器渲染出一坨原始 JSON。这里循环解出内层纯文本。
 */
function unwrapJsonContent(raw: string): string {
  const s = (raw || "").trim();
  if (!s.startsWith("{")) return raw;
  try {
    let cur: unknown = JSON.parse(s);
    for (let i = 0; i < 5; i++) {
      if (cur && typeof cur === "object" && !Array.isArray(cur)) {
        const obj = cur as Record<string, unknown>;
        if (typeof obj.content === "string" && obj.content.trim()) {
          // 解出的是纯文本，换行转 <br> 才能在 contenteditable 里正常分段
          return obj.content.replace(/\n/g, "<br>");
        }
        if (obj.content && typeof obj.content === "object") {
          cur = obj.content;
          continue;
        }
      }
      break;
    }
  } catch {
    /* 不是合法 JSON，走下面的松散抽取 */
  }
  // 合法解析失败但形如信封（模型输出带裸换行等）：松散抽 content 字段
  if (s.includes('"content"')) {
    const extracted = extractJsonStringFieldLoose(s, "content");
    if (extracted.trim().length > 80) {
      return extracted.replace(/\n/g, "<br>");
    }
  }
  return raw;
}

import {
  Save,
  FileType2,
  FileDown,
  CheckCircle,
  Loader2,
  AlertTriangle,
  Edit3,
  Bold,
  Italic,
  Underline,
  Strikethrough,
  AlignLeft,
  AlignCenter,
  AlignRight,
  List,
  ListOrdered,
  Type,
  ChevronDown,
  X,
  ShieldCheck,
  History as HistoryIcon,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { getContract, updateContract, downloadContractDocx, downloadContractPdf, type ContractDetail } from "../../lib/api/contracts";
import {
  getReviewRecords,
  recordToResponse,
  type ReviewDocumentResponse,
  type ReviewIssue,
  type ReviewRecordItem,
} from "../../lib/api/review";

export function ContractEditor() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialType = searchParams.get("type") || "";

  const editorRef = useRef<HTMLDivElement>(null);
  const syncedRef = useRef(false);
  const [contract, setContract] = useState<ContractDetail | null>(null);
  const [title, setTitle] = useState("");
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewResult, setReviewResult] = useState<ReviewDocumentResponse | null>(null);
  const [activeReviewIssue, setActiveReviewIssue] = useState<number | null>(null);
  const [fontSize, setFontSize] = useState("16px");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyRecords, setHistoryRecords] = useState<ReviewRecordItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    syncedRef.current = false;
    setContract(null);
    setHtml("");
    setError("");
    setMessage("");
    setReviewResult(null);
    setReviewOpen(false);
    const load = async () => {
      try {
        const data = await getContract(Number(id));
        setContract(data);
        setTitle(data.title || initialType || "未命名合同");
        const content = unwrapJsonContent(data.html_content || data.content || "");
        setHtml(content);
      } catch (err: any) {
        setError(err?.message || "加载合同失败");
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [id, initialType]);

  // 加载完成且编辑器 DOM 已挂载后，把正文同步到编辑器（仅同步一次，避免覆盖用户输入）
  useEffect(() => {
    if (syncedRef.current) return;
    if (loading) return;
    if (!editorRef.current) return;
    editorRef.current.innerHTML = html || "";
    syncedRef.current = true;
  }, [loading, html]);

  const execCommand = (command: string, value: string | undefined = undefined) => {
    document.execCommand(command, false, value);
    editorRef.current?.focus();
    syncHtml();
  };

  const syncHtml = () => {
    if (editorRef.current) {
      setHtml(editorRef.current.innerHTML);
    }
  };

  const handleSave = async () => {
    if (!contract) return;
    setSaving(true);
    try {
      const content = editorRef.current?.innerHTML || html;
      await updateContract(contract.id, { title, content });
      setMessage("保存成功");
      setTimeout(() => setMessage(""), 2000);
    } catch (err: any) {
      setError(err?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const downloadWord = async () => {
    const content = editorRef.current?.innerHTML || html;
    try {
      const { blob, filename } = await downloadContractDocx(title || "合同", content);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err?.message || "下载失败");
    }
  };

  const downloadPdf = async () => {
    const content = editorRef.current?.innerHTML || html;
    try {
      const { blob, filename } = await downloadContractPdf(title || "合同", content);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err?.message || "导出 PDF 失败");
    }
  };

  // 不直接跑 AI：跳到「合同审核」页并带入当前合同正文，由用户在该页点「开始审核」
  const handleReview = () => {
    if (!contract) return;
    const content = editorRef.current?.innerText || editorRef.current?.innerHTML || html;
    navigate("/approvals", {
      state: { prefillContent: content, prefillTitle: title, contractId: contract.id },
    });
  };

  const updateReviewIssue = (idx: number, patch: Partial<ReviewIssue>) => {
    if (!reviewResult) return;
    const next = { ...reviewResult };
    const issues = [...(next.issues || [])];
    issues[idx] = { ...issues[idx], ...patch };
    next.issues = issues;
    setReviewResult(next);
  };

  const removeReviewIssue = (idx: number) => {
    if (!reviewResult) return;
    const next = { ...reviewResult };
    next.issues = (next.issues || []).filter((_, i) => i !== idx);
    setReviewResult(next);
    if (activeReviewIssue === idx) setActiveReviewIssue(null);
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center pb-20 pt-8">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  const allIssues = reviewResult?.issues || [];
  const overallScore = reviewResult?.overall_score ?? reviewResult?.dimensions?.overall?.score;
  const reviewStatus = reviewResult?.review_status || "pass";
  const statusMeta =
    reviewStatus === "pass" || reviewStatus === "approved"
      ? { label: "已通过", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" }
      : reviewStatus === "warning" || reviewStatus === "needs_revision"
      ? { label: "需修改", cls: "bg-amber-50 text-amber-700 border-amber-200" }
      : { label: "审核完成", cls: "bg-sky-50 text-sky-700 border-sky-200" };

  return (
    <div className="flex h-[calc(100vh-64px)] flex-col">
      {/* Top bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border bg-card px-6 py-3">
        <div className="flex items-center gap-3 min-w-0">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="min-w-[200px] max-w-md border-none bg-transparent text-lg font-black text-foreground outline-none placeholder:text-muted-foreground"
            placeholder="合同标题"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-black text-primary-foreground shadow-sm hover:opacity-90 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            保存合同
          </button>
          <button
            onClick={downloadWord}
            className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-card px-4 py-2 text-xs font-black text-foreground transition-colors hover:bg-accent"
          >
            <FileType2 className="h-3.5 w-3.5" /> 下载 Word
          </button>
          <button
            onClick={downloadPdf}
            className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-card px-4 py-2 text-xs font-black text-foreground transition-colors hover:bg-accent"
          >
            <FileDown className="h-3.5 w-3.5" /> 下载 PDF
          </button>
          <button
            onClick={handleReview}
            className="inline-flex items-center gap-1.5 rounded-xl border border-primary/30 bg-primary/10 px-4 py-2 text-xs font-black text-primary transition-colors hover:bg-primary/20"
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            送去合同审查
          </button>
          <button
            onClick={() => {
              setHistoryOpen(true);
              if (contract) {
                setHistoryLoading(true);
                getReviewRecords({ contractId: Number(contract.id), limit: 20 })
                  .then(setHistoryRecords)
                  .catch(() => setHistoryRecords([]))
                  .finally(() => setHistoryLoading(false));
              }
            }}
            title="查看这份合同的历史审查记录"
            className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-card px-4 py-2 text-xs font-black text-foreground transition-colors hover:bg-accent"
          >
            <HistoryIcon className="h-3.5 w-3.5" /> 审查历史
          </button>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-secondary/30 px-6 py-2">
        <span className="text-xs font-bold text-muted-foreground">正文</span>
        <div className="h-4 w-px bg-border" />
        <div className="relative">
          <select
            value={fontSize}
            onChange={(e) => {
              setFontSize(e.target.value);
              execCommand("fontSize", e.target.value);
            }}
            className="h-8 appearance-none rounded-lg border border-border bg-card pl-2 pr-6 text-xs font-bold text-foreground outline-none focus:border-primary/40"
          >
            <option value="12px">12px</option>
            <option value="14px">14px</option>
            <option value="16px">16px</option>
            <option value="18px">18px</option>
            <option value="20px">20px</option>
            <option value="24px">24px</option>
          </select>
          <ChevronDown className="absolute right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        </div>
        <div className="h-4 w-px bg-border" />
        <ToolButton onClick={() => execCommand("bold")} label="加粗" icon={Bold} />
        <ToolButton onClick={() => execCommand("italic")} label="斜体" icon={Italic} />
        <ToolButton onClick={() => execCommand("underline")} label="下划线" icon={Underline} />
        <ToolButton onClick={() => execCommand("strikeThrough")} label="删除线" icon={Strikethrough} />
        <div className="h-4 w-px bg-border" />
        <ToolButton onClick={() => execCommand("justifyLeft")} label="左对齐" icon={AlignLeft} />
        <ToolButton onClick={() => execCommand("justifyCenter")} label="居中对齐" icon={AlignCenter} />
        <ToolButton onClick={() => execCommand("justifyRight")} label="右对齐" icon={AlignRight} />
        <div className="h-4 w-px bg-border" />
        <ToolButton onClick={() => execCommand("insertUnorderedList")} label="无序列表" icon={List} />
        <ToolButton onClick={() => execCommand("insertOrderedList")} label="有序列表" icon={ListOrdered} />
      </div>

      {/* Messages */}
      {message && (
        <div className="mx-6 mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-bold text-emerald-700">
          <CheckCircle className="mr-1.5 inline-block h-3.5 w-3.5" /> {message}
        </div>
      )}
      {error && (
        <div className="mx-6 mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-bold text-rose-700">
          <AlertTriangle className="mr-1.5 inline-block h-3.5 w-3.5" /> {error}
        </div>
      )}

      {/* Editor + review panel */}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-auto bg-secondary/20 p-8">
            <div
              ref={editorRef}
              contentEditable
              suppressContentEditableWarning
              onInput={syncHtml}
              className="min-h-[800px] w-full max-w-4xl mx-auto rounded-[1.5rem] border border-border bg-card px-10 py-12 text-sm leading-7 text-foreground shadow-sm outline-none focus:ring-2 focus:ring-primary/10"
              style={{ fontFamily: "'PingFang SC','Microsoft YaHei',sans-serif", whiteSpace: "pre-wrap" }}
            />
          </div>
        </div>

        {reviewOpen && (
          <div className="w-[380px] flex-shrink-0 overflow-y-auto border-l border-border bg-card p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-black text-foreground">条款审查结果</h3>
              <button onClick={() => setReviewOpen(false)} className="rounded-full p-1 text-muted-foreground hover:bg-accent">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className={cn("mb-4 rounded-2xl border px-4 py-3", statusMeta.cls)}>
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold">审核状态</span>
                <span className="text-xs font-black">{statusMeta.label}</span>
              </div>
              {overallScore !== undefined && (
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-xs font-bold">综合评分</span>
                  <span className="text-lg font-black">{overallScore}</span>
                </div>
              )}
            </div>

            <div className="space-y-3">
              {allIssues.length === 0 && (
                <div className="rounded-xl border border-border bg-secondary/30 px-4 py-6 text-center text-xs font-bold text-muted-foreground">
                  暂未发现问题
                </div>
              )}
              {allIssues.map((issue, idx) => (
                <div
                  key={idx}
                  className={cn(
                    "rounded-2xl border p-4 transition-colors",
                    activeReviewIssue === idx ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-accent/40"
                  )}
                  onClick={() => setActiveReviewIssue(idx)}
                >
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[10px] font-black",
                        issue.severity === "high"
                          ? "bg-red-500 text-white border-red-600"
                          : issue.severity === "medium"
                          ? "bg-amber-500 text-white border-amber-600"
                          : "bg-slate-200 text-slate-700 border-slate-400"
                      )}
                    >
                      {issue.severity === "high" ? "高风险" : issue.severity === "medium" ? "中风险" : "提示"}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        removeReviewIssue(idx);
                      }}
                      className="text-muted-foreground hover:text-rose-600"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="mb-2 text-xs font-bold text-foreground">
                    <Edit3 className="mr-1 inline-block h-3 w-3 text-muted-foreground" />
                    <input
                      value={issue.clause || ""}
                      onChange={(e) => updateReviewIssue(idx, { clause: e.target.value })}
                      placeholder="条款"
                      className="w-full border-b border-transparent bg-transparent font-bold outline-none focus:border-primary"
                    />
                  </div>
                  <textarea
                    value={issue.description}
                    onChange={(e) => updateReviewIssue(idx, { description: e.target.value })}
                    rows={2}
                    className="mb-2 w-full resize-none rounded-lg border border-border bg-secondary/30 px-2 py-1 text-xs font-medium text-foreground outline-none focus:border-primary/40"
                  />
                  <textarea
                    value={issue.suggestion}
                    onChange={(e) => updateReviewIssue(idx, { suggestion: e.target.value })}
                    rows={2}
                    className="w-full resize-none rounded-lg border border-orange-300 bg-orange-50/60 px-2 py-1 text-xs font-medium text-orange-950 outline-none focus:border-orange-500"
                    placeholder="修改建议"
                  />
                </div>
              ))}
            </div>

            {reviewResult?.suggestions && reviewResult.suggestions.length > 0 && (
              <div className="mt-5 rounded-2xl border border-border bg-secondary/30 p-4">
                <h4 className="mb-2 text-xs font-black text-foreground">优化建议</h4>
                <ul className="list-disc space-y-1 pl-4 text-xs font-medium text-muted-foreground">
                  {reviewResult.suggestions.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 审查历史弹层 */}
      {historyOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6" onClick={() => setHistoryOpen(false)}>
          <div className="max-h-[75vh] w-full max-w-2xl overflow-y-auto rounded-3xl border border-border bg-card p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-base font-black text-foreground">
                <HistoryIcon className="h-4 w-4 text-primary" /> 这份合同的审查历史
              </h3>
              <button onClick={() => setHistoryOpen(false)} className="rounded-lg p-1.5 text-muted-foreground hover:bg-secondary">
                <X className="h-4 w-4" />
              </button>
            </div>
            {historyLoading ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm font-bold text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> 正在加载审查记录…
              </div>
            ) : historyRecords.length === 0 ? (
              <div className="py-10 text-center text-sm font-bold text-muted-foreground">还没有审查记录，点「送去合同审查」跑一次 AI 审查。</div>
            ) : (
              <div className="space-y-2">
                {historyRecords.map((r) => (
                  <div key={r.id} className="flex items-center justify-between rounded-2xl border border-border bg-secondary/20 px-4 py-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-black text-foreground">{r.review_id}</span>
                        <span className={cn(
                          "rounded-full border px-2 py-0.5 text-[10px] font-black",
                          r.review_status === "pass" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : r.review_status === "fail" ? "border-red-200 bg-red-50 text-red-700" : "border-amber-200 bg-amber-50 text-amber-700"
                        )}>
                          {r.review_status_label || r.review_status}
                        </span>
                        {typeof r.overall_score === "number" && (
                          <span className="text-[10px] font-bold text-muted-foreground">评分 {(r.overall_score * 100).toFixed(0)} 分</span>
                        )}
                        <span className="text-[10px] font-bold text-muted-foreground">{Array.isArray(r.issues) ? `${r.issues.length} 个问题` : ""}</span>
                      </div>
                      <div className="mt-0.5 text-[10px] font-bold text-muted-foreground">
                        {r.reviewed_at ? new Date(r.reviewed_at).toLocaleString("zh-CN") : ""}
                      </div>
                    </div>
                    <button
                      onClick={() => {
                        setHistoryOpen(false);
                        navigate("/review/result", {
                          state: { result: recordToResponse(r), title: `${r.review_id} 审查结果`, content: "" },
                        });
                      }}
                      className="ml-3 shrink-0 rounded-xl border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-black text-primary hover:bg-primary/20"
                    >
                      查看结果
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ToolButton({ onClick, icon: Icon, label }: { onClick: () => void; icon: React.ElementType; label: string }) {
  return (
    <button
      onClick={onClick}
      title={label}
      className="flex h-8 w-8 items-center justify-center rounded-lg border border-transparent text-muted-foreground transition-colors hover:border-border hover:bg-card hover:text-foreground"
    >
      <Icon className="h-3.5 w-3.5" />
    </button>
  );
}
