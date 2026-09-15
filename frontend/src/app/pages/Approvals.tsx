import { useEffect, useState, useRef } from "react";
import { useNavigate, useLocation } from "react-router";
import {
  Upload,
  FileText,
  ShieldCheck,
  Loader2,
  AlertTriangle,
  History,
  X,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { startReviewDocumentAsync, getReviewTask, extractDocumentText, getReviewRecords, recordToResponse, type ReviewDocumentResponse, type ReviewRecordItem } from "../../lib/api/review";
import { TaskProgress } from "../../app/components/TaskProgress";
import { PageHeader } from "../components/PageHeader";

const ACCEPT_TYPES = ".txt,.doc,.docx,.pdf";

export function Approvals() {
  const navigate = useNavigate();
  const location = useLocation();
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");
  const [content, setContent] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [reviewStartedAt, setReviewStartedAt] = useState(0);
  const [error, setError] = useState("");
  const [contractId, setContractId] = useState<number | null>(null);
  const [fromEditor, setFromEditor] = useState("");
  const [recentRecords, setRecentRecords] = useState<ReviewRecordItem[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(true);

  const loadRecentRecords = () => {
    setRecordsLoading(true);
    getReviewRecords({ limit: 10 })
      .then(setRecentRecords)
      .catch(() => setRecentRecords([]))
      .finally(() => setRecordsLoading(false));
  };

  useEffect(() => {
    loadRecentRecords();
  }, []);

  // 合同编辑器「送去合同审查」跳转过来：自动带入合同正文与标题，用户确认后手动点「开始审核」
  useEffect(() => {
    const state = location.state as { prefillContent?: string; prefillTitle?: string; contractId?: number } | null;
    if (state?.prefillContent?.trim()) {
      setContent(state.prefillContent.trim());
      setFileName(state.prefillTitle || "");
      setFromEditor(state.prefillTitle || "合同编辑器");
      if (state.contractId) setContractId(state.contractId);
      // 用完即清，避免刷新时反复覆盖用户手动修改的内容
      window.history.replaceState({}, "");
    }
  }, [location.state]);

  const readTextFile = async (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error("读取文件失败"));
      reader.readAsText(file);
    });
  };

  const handleFile = async (file: File) => {
    setError("");
    const lower = file.name.toLowerCase();
    if (!lower.endsWith(".txt") && !lower.endsWith(".doc") && !lower.endsWith(".docx") && !lower.endsWith(".pdf")) {
      setError("仅支持 .txt / .doc / .docx / .pdf 格式的合同文件，其他格式请先粘贴文本");
      return;
    }
    setFileName(file.name);
    // .txt：前端直接读取
    if (lower.endsWith(".txt")) {
      try {
        const text = await readTextFile(file);
        setContent(text);
      } catch (err: any) {
        setError(err?.message || "读取失败");
      }
      return;
    }
    // .doc / .docx / .pdf：后端解析提取正文（.doc 走本机 Word COM 转换）
    try {
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("读取文件失败"));
        reader.readAsDataURL(file);
      });
      const parsed = await extractDocumentText(file.name, base64);
      if (!parsed?.content?.trim()) {
        setError("未从文件中提取到文本内容，请直接粘贴合同正文后重试");
        return;
      }
      setContent(parsed.content);
    } catch (err: any) {
      setError(err?.message || "文件解析失败，请直接粘贴合同正文后重试");
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  };

  const handleSubmit = async () => {
    if (!content.trim()) {
      setError("请先上传合同文件或粘贴合同文本");
      return;
    }
    setReviewing(true);
    setReviewStartedAt(Date.now());
    setError("");
    try {
      // 审核是分钟级 agent 循环（2026-09-11 实测：1186 字约 145s、3751 字约 205s，
      // 端到端含根代理约 193s；旧值「4-8 分钟」是 thinking_budget 修复前的数据）。
      // 同步等待会被浏览器/代理掐断报"请求超时"，故异步提交 + 轮询进度。
      const { task_key } = await startReviewDocumentAsync({
        document_type: "contract",
        contract_id: contractId ?? undefined,
        content: content.trim(),
        title: fileName || "合同审核",
      });
      const poll = async (): Promise<ReviewDocumentResponse> => {
        const deadline = Date.now() + 25 * 60 * 1000;
        while (Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 5000));
          const snap = await getReviewTask(task_key);
          if (snap.status === "completed" && snap.result) return snap.result;
          if (snap.status === "failed") throw new Error(snap.error || "AI 审核任务执行失败，请稍后重试");
        }
        throw new Error("审核任务超过 25 分钟未完成，请重试");
      };
      const data = await poll();
      // 合同原文一并带到审核结果页（逐段展示需要）
      sessionStorage.setItem("lastReviewContent", content.trim());
      navigate("/review/result", {
        state: { result: data, title: fileName || "合同审核结果", content: content.trim() },
      });
    } catch (err: any) {
      setError(err?.message || "审核失败");
      setReviewing(false);
    }
  };

  const clearAll = () => {
    setFileName("");
    setContent("");
    setError("");
    setFromEditor("");
    setContractId(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div className="max-w-5xl space-y-8 pb-20 pt-8">
      <PageHeader
        title="合同审核"
        description="上传合同文件或粘贴合同文本，AI 自动识别风险与条款问题，审核后可在线修改。"
      />

      {fromEditor && (
        <div className="inline-flex items-center gap-2 rounded-xl border border-primary/20 bg-primary/5 px-4 py-2 text-xs font-bold text-primary">
          <ShieldCheck className="h-3.5 w-3.5" />
          已从合同编辑器带入「{fromEditor}」的正文，确认无误后点下方「开始审核」
          <button onClick={() => setFromEditor("")} className="ml-1 text-muted-foreground hover:text-foreground">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <section className="rounded-[1.75rem] border border-border bg-card p-6 shadow-sm">
        <div
          onClick={() => fileRef.current?.click()}
          onDrop={handleDrop}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
            dragOver
              ? "border-primary bg-primary/5"
              : "border-border bg-secondary/30 hover:border-primary/40 hover:bg-accent/30"
          )}
        >
          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-primary/15 bg-primary/5 text-primary">
            <Upload className="h-7 w-7" />
          </div>
          <div className="text-sm font-black text-foreground">点击或拖拽上传合同文件</div>
          <div className="mt-2 text-xs font-bold text-muted-foreground">支持 .txt / .doc / .docx / .pdf</div>
          {fileName && (
            <div className="mt-4 inline-flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-2 text-xs font-bold text-foreground shadow-sm">
              <FileText className="h-3.5 w-3.5 text-primary" /> {fileName}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setFileName("");
                  setContent("");
                  if (fileRef.current) fileRef.current.value = "";
                }}
                className="ml-1 text-muted-foreground hover:text-rose-600"
              >
                ✕
              </button>
            </div>
          )}
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPT_TYPES}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
            }}
          />
        </div>

        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-black text-foreground">或直接粘贴合同文本</span>
            <button onClick={clearAll} className="text-xs font-bold text-muted-foreground hover:text-rose-600">
              清空
            </button>
          </div>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="请将合同正文粘贴到此处…"
            rows={14}
            className="w-full resize-none rounded-2xl border border-border bg-secondary/30 px-5 py-4 text-sm font-medium leading-relaxed text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
          />
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs font-bold text-rose-700">
            <AlertTriangle className="mr-1.5 inline-block h-3.5 w-3.5" /> {error}
          </div>
        )}

        <button
          onClick={() => void handleSubmit()}
          disabled={reviewing || !content.trim()}
          className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-primary px-5 py-3 text-sm font-black text-primary-foreground shadow-sm transition-all hover:shadow-md disabled:opacity-50"
        >
          {reviewing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
          {reviewing ? "AI 审核中…" : "开始审核"}
        </button>
        {reviewing && (
          <TaskProgress
            title="AI 审核合同"
            phases={["解析合同文本", "逐条分析条款", "识别风险点", "生成审核报告"]}
            startedAt={reviewStartedAt}
            // 审核耗时随文档长度近似线性（2026-09-11 实测：1186 字 145s、3751 字 205s，
            // 斜率约 0.0234 s/字、截距约 117s），乘 1.15 留余量。不传则组件按
            // 「每阶段 60 秒」估算，会让进度条提前跑满、ETA 假报（见 TaskProgress 注释）。
            estimatedTotalSeconds={Math.round((117 + 0.0234 * content.trim().length) * 1.15)}
            className="mt-4"
          />
        )}
      </section>

      {/* 最近审查记录 */}
      <section className="rounded-[1.75rem] border border-border bg-card p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-black text-foreground">
            <History className="h-4 w-4 text-primary" /> 最近审查记录
          </h3>
          <button onClick={loadRecentRecords} className="rounded-lg px-2 py-1 text-xs font-black text-muted-foreground hover:bg-secondary">
            刷新
          </button>
        </div>
        {recordsLoading ? (
          <div className="flex items-center justify-center gap-2 py-8 text-sm font-bold text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 正在加载审查记录…
          </div>
        ) : recentRecords.length === 0 ? (
          <div className="py-8 text-center text-sm font-bold text-muted-foreground">还没有审查记录，上传合同跑一次 AI 审核吧。</div>
        ) : (
          <div className="space-y-2">
            {recentRecords.map((r) => (
              <div key={r.id} className="flex items-center justify-between rounded-2xl border border-border bg-secondary/20 px-4 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
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
                    {r.contract_id && <span className="text-[10px] font-bold text-primary">合同 #{r.contract_id}</span>}
                  </div>
                  <div className="mt-0.5 text-[10px] font-bold text-muted-foreground">
                    {r.reviewed_at ? new Date(r.reviewed_at).toLocaleString("zh-CN") : ""}
                  </div>
                </div>
                <button
                  onClick={() =>
                    navigate("/review/result", {
                      state: { result: recordToResponse(r), title: `${r.review_id} 审查结果`, content: "" },
                    })
                  }
                  className="ml-3 shrink-0 rounded-xl border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-black text-primary hover:bg-primary/20"
                >
                  查看结果
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
