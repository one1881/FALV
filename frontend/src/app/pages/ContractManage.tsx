import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { motion } from "motion/react";
import {
  FilePlus,
  Search,
  FileType2,
  FileDown,
  Eye,
  FolderOpen,
  ChevronDown,
  CheckCircle2,
  Clock,
  Archive,
  AlertTriangle,
  FileText,
  Trash2,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { getCurrentUser } from "../auth";
import { PageHeader } from "../components/PageHeader";
import { archiveContract, getContracts, deleteContract, downloadContractDocx, downloadContractPdf, type Contract } from "../../lib/api/contracts";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";

// ==========================================
// 合同管理页：展示数据库状态并提供归档、删除等操作。
// ==========================================

type ContractStatus = "draft" | "drafting" | "pending" | "approved" | "rejected" | "archived";

function normalizeContractStatus(status?: string): ContractStatus {
  switch (status) {
    case "drafting":
      return "drafting";
    case "review":
    case "pending":
      return "pending";
    case "reviewing":
      return "pending";
    case "final":
    case "approved":
    case "active":
      return "approved";
    case "rejected":
      return "rejected";
    case "archived":
    case "expired":
      return "archived";
    default:
      return "draft";
  }
}

interface ContractItem {
  id: string;
  contractNumber: string;
  name: string;
  type: string;
  typeValue: string;
  owner: string;
  creatorLabel: string;
  ownerLawyerLabel: string;
  completedLabel: string;
  statusLabel: string;
  status: ContractStatus;
  createdAt: string;
  updatedAt: string;
  content: string;
  riskFlag?: boolean;
}

const STATUS_META: Record<ContractStatus, { label: string; cls: string; step: number }> = {
  draft: { label: "草稿", cls: "bg-slate-100 text-slate-600 border-slate-200", step: 0 },
  drafting: { label: "起草中", cls: "bg-blue-50 text-blue-700 border-blue-100", step: 1 },
  pending: { label: "待审核", cls: "bg-amber-50 text-amber-700 border-amber-100", step: 2 },
  approved: { label: "已通过", cls: "bg-emerald-50 text-emerald-700 border-emerald-100", step: 3 },
  rejected: { label: "已驳回", cls: "bg-rose-50 text-rose-700 border-rose-100", step: 3 },
  archived: { label: "已归档", cls: "bg-sky-50 text-sky-700 border-sky-100", step: 4 },
};

const TYPE_OPTIONS = ["全部类型", "服务合同", "采购合同", "劳动合同", "租赁合同", "销售合同", "保密协议"];

function formatDateTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).replace(/\//g, "-");
}

function lawyerLabel(name?: string, id?: number) {
  return name || (id ? `律师ID ${id}` : "—");
}

function isContractCompleted(contract: Contract) {
  return Boolean(contract.is_completed ?? contract.completed ?? ["approved", "archived", "final"].includes(contract.status));
}

// 后端响应 → 页面列表数据（加载/删除/归档后统一走这个，保证口径一致）
function toContractItems(response: { items?: Contract[] }): ContractItem[] {
  return (response.items || []).map((c: Contract) => ({
    id: String(c.id),
    contractNumber: c.contract_number || c.contract_code || `CT-${String(c.id).padStart(4, "0")}`,
    name: c.title || "未命名合同",
    type: c.contract_type || "未分类",
    typeValue: c.contract_type || "unknown",
    owner: c.customer_name || "未指定客户",
    creatorLabel: lawyerLabel(c.created_by_name, c.created_by),
    ownerLawyerLabel: lawyerLabel(c.owner_lawyer_name, c.owner_lawyer_id || c.created_by),
    completedLabel: isContractCompleted(c) ? "是" : "否",
    statusLabel: c.status_label || STATUS_META[normalizeContractStatus(c.status)].label,
    status: normalizeContractStatus(c.status),
    createdAt: formatDateTime(c.created_at),
    updatedAt: formatDateTime(c.updated_at || c.created_at),
    content: c.content || "",
    riskFlag: false,
  }));
}

const containerVariants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};
const itemVariants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] } },
};

export function ContractManage() {
  const navigate = useNavigate();
  const currentUser = getCurrentUser();
  const isReviewer = currentUser?.role === "reviewer";
  const [searchParams, setSearchParams] = useSearchParams();
  const readStatusParam = (): "all" | "draft" | "drafting" | "pending" | "approved" | "rejected" | "archived" => {
    const raw = searchParams.get("status");
    if (raw === "draft" || raw === "drafting" || raw === "pending" || raw === "approved" || raw === "rejected" || raw === "archived") {
      return raw;
    }
    return "all";
  };
  const [tab, setTab] = useState<"all" | "draft" | "drafting" | "pending" | "approved" | "rejected" | "archived">(readStatusParam);
  const [keyword, setKeyword] = useState("");
  const [typeFilter, setTypeFilter] = useState("全部类型");
  const [items, setItems] = useState<ContractItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewItem, setPreviewItem] = useState<ContractItem | null>(null);

  useEffect(() => {
    const nextTab = readStatusParam();
    setTab((current) => (current === nextTab ? current : nextTab));
  }, [searchParams]);

  // 加载合同列表
  useEffect(() => {
    const loadContracts = async () => {
      try {
        setLoading(true);
        const response = await getContracts({
          page: 1,
          page_size: 100,
          status: tab === "all" ? undefined : tab,
        });

        // 转换API数据到本地格式
        const converted: ContractItem[] = (response.items || []).map((c: Contract) => ({
          id: String(c.id),
          contractNumber: c.contract_number || c.contract_code || `CT-${String(c.id).padStart(4, "0")}`,
          name: c.title || "未命名合同",
          type: c.contract_type || "未分类",
          typeValue: c.contract_type || "unknown",
          owner: c.customer_name || "未指定客户",
          creatorLabel: lawyerLabel(c.created_by_name, c.created_by),
          ownerLawyerLabel: lawyerLabel(c.owner_lawyer_name, c.owner_lawyer_id || c.created_by),
          completedLabel: isContractCompleted(c) ? "是" : "否",
          statusLabel: c.status_label || STATUS_META[normalizeContractStatus(c.status)].label,
          status: normalizeContractStatus(c.status),
          createdAt: formatDateTime(c.created_at),
          updatedAt: formatDateTime(c.updated_at || c.created_at),
          content: c.content || "",
          riskFlag: false,
        }));

        setItems(converted);
        setError(null);
      } catch (err: any) {
        setError(err.message || "加载合同列表失败");
        console.error("Failed to load contracts:", err);
        setItems([]);
      } finally {
        setLoading(false);
      }
    };
    loadContracts();
  }, [tab]);

  const counts = {
    all: items.length,
    draft: items.filter((c) => c.status === "draft").length,
    drafting: items.filter((c) => c.status === "drafting").length,
    pending: items.filter((c) => c.status === "pending").length,
    approved: items.filter((c) => c.status === "approved").length,
    rejected: items.filter((c) => c.status === "rejected").length,
    archived: items.filter((c) => c.status === "archived").length,
  };

  const filtered = items.filter((c) => {
    if (tab !== "all" && c.status !== tab) return false;
    if (keyword && !c.name.includes(keyword) && !c.owner.includes(keyword)) return false;
    if (typeFilter !== "全部类型" && !c.type.includes(typeFilter.replace("合同", ""))) return false;
    return true;
  });

  // 批量操作
  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };
  const batchArchive = async () => {
    const candidates = items.filter((item) => selected.has(item.id) && item.status === "approved");
    if (candidates.length === 0) {
      setError("只有审批通过的合同可以归档");
      return;
    }
    try {
      await Promise.all(candidates.map((item) => archiveContract(Number(item.id), "合同管理批量归档")));
      setSelected(new Set());
      const response = await getContracts({ page: 1, page_size: 100 });
      setItems(toContractItems(response));
    } catch (archiveError: any) {
      setError(archiveError?.message || "批量归档失败");
    }
  };
  const batchDelete = async () => {
    if (!selected.size || !window.confirm("确认删除选中的合同吗？删除后不可恢复。")) return;
    try {
      await Promise.all(Array.from(selected).map((id) => deleteContract(Number(id))));
      setSelected(new Set());
      // 删除后强制从后端重拉列表，杜绝本地状态与库不同步
      const response = await getContracts({ page: 1, page_size: 100 });
      setItems(toContractItems(response));
      setError(null);
    } catch (deleteError: any) {
      setError(deleteError?.message || "批量删除失败");
    }
  };
  const deleteOne = async (item: ContractItem) => {
    if (!window.confirm(`确认删除「${item.name}」吗？删除后不可恢复。`)) return;
    try {
      await deleteContract(Number(item.id));
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(item.id);
        return next;
      });
      const response = await getContracts({ page: 1, page_size: 100 });
      setItems(toContractItems(response));
      setError(null);
    } catch (deleteError: any) {
      setError(deleteError?.message || "删除失败");
    }
  };

  // Word 下载（真正的 .docx，后端 python-docx 生成，避免伪 .doc 乱码）
  const downloadWord = async (item: ContractItem) => {
    try {
      const { blob, filename } = await downloadContractDocx(item.name || "合同", item.content || "");
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

  // PDF 下载（后端 reportlab 生成真正的 PDF 文件，直接下载）
  const downloadPdf = async (item: ContractItem) => {
    try {
      const { blob, filename } = await downloadContractPdf(item.name || "合同", item.content || "");
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

  const TABS: { key: typeof tab; label: string; count: number }[] = [
    { key: "all", label: "全部", count: counts.all },
    { key: "pending", label: "待审核", count: counts.pending },
    { key: "approved", label: "已通过", count: counts.approved },
    { key: "rejected", label: "已驳回", count: counts.rejected },
    // 起草中/草稿/已归档只有律师（创建方）可见；审核员只看到已提交审核的
    ...(isReviewer
      ? []
      : [
          { key: "draft", label: "草稿", count: counts.draft },
          { key: "drafting", label: "起草中", count: counts.drafting },
          { key: "archived", label: "已归档", count: counts.archived },
        ]),
  ];

  const allChecked = filtered.length > 0 && filtered.every((c) => selected.has(c.id));
  const handleTabChange = (nextTab: typeof tab) => {
    setTab(nextTab);
    const nextParams = new URLSearchParams(searchParams);
    if (nextTab === "all") nextParams.set("status", "all");
    else nextParams.set("status", nextTab);
    setSearchParams(nextParams);
  };
  const toggleAll = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allChecked) filtered.forEach((c) => next.delete(c.id));
      else filtered.forEach((c) => next.add(c.id));
      return next;
    });
  };

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="show"
      className="flex flex-col gap-8 h-full pt-10 pb-20 max-w-7xl relative z-10"
    >
      {/* Header */}
      <motion.div variants={itemVariants} className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <PageHeader
          title="合同管理"
          description="按「草稿 → 起草中 → 待审核 → 通过/驳回 → 归档」流转管理合同状态，统一展示律师负责人和完成情况。"
        />
        <button
          onClick={() => navigate("/drafting/contracts")}
          className="inline-flex items-center gap-2 rounded-2xl bg-primary px-5 py-3 text-xs font-black uppercase tracking-[0.24em] text-primary-foreground shadow-sm transition-all hover:shadow-md hover:-translate-y-0.5"
        >
          <FilePlus className="w-4 h-4" /> 新建合同
        </button>
      </motion.div>

      {/* 列表卡片 */}
      <motion.div variants={itemVariants} className="rounded-[1.75rem] border border-border bg-card shadow-sm overflow-hidden">
        {/* Tab + 搜索 */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-border bg-secondary/30 px-6 py-4">
          <div className="flex items-center gap-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => handleTabChange(t.key)}
                className={cn(
                  "flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold tracking-widest transition-colors",
                  tab === t.key
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}
              >
                {t.label}
                <span className={cn(
                  "rounded-full px-1.5 py-0.5 text-[9px] font-black",
                  tab === t.key ? "bg-white/20 text-white" : "bg-muted text-muted-foreground"
                )}>
                  {t.count}
                </span>
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/60" />
              <input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索合同名称 / 归属部门"
                className="h-9 w-56 rounded-xl border border-border bg-card pl-9 pr-3 text-xs font-bold text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-primary/40"
              />
            </div>
            <div className="relative">
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="h-9 appearance-none rounded-xl border border-border bg-card pl-3 pr-8 text-xs font-bold text-foreground outline-none focus:border-primary/40 cursor-pointer"
              >
                {TYPE_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/60 pointer-events-none" />
            </div>
          </div>
        </div>

        {/* 批量操作条 */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-border bg-primary/5">
          <label className="flex items-center gap-2 text-xs font-bold text-foreground cursor-pointer select-none">
            <input type="checkbox" checked={allChecked} onChange={toggleAll} className="w-4 h-4 accent-primary" />
            全选（{selected.size} 项已选）
          </label>
          <div className="flex items-center gap-2">
            <button
              onClick={batchArchive}
              disabled={selected.size === 0}
              className="flex items-center gap-1.5 rounded-xl border border-sky-200 bg-sky-50 px-3 py-1.5 text-[11px] font-black tracking-widest text-sky-700 transition-colors hover:bg-sky-100 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Archive className="w-3.5 h-3.5" /> 批量归档
            </button>
            <button
              onClick={batchDelete}
              disabled={selected.size === 0}
              className="flex items-center gap-1.5 rounded-xl border border-rose-200 bg-rose-50 px-3 py-1.5 text-[11px] font-black tracking-widest text-rose-700 transition-colors hover:bg-rose-100 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Trash2 className="w-3.5 h-3.5" /> 批量删除
            </button>
          </div>
        </div>

        {/* 列表 */}
        <div className="divide-y divide-border">
          {filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <FileText className="w-8 h-8 text-muted-foreground/30" />
              <div className="text-xs font-bold text-muted-foreground">暂无符合条件的合同</div>
            </div>
          )}
          {filtered.map((c) => {
            const st = STATUS_META[c.status] || STATUS_META.draft;
            const isSel = selected.has(c.id);
            return (
              <div key={c.id} className={cn("flex items-center gap-4 px-6 py-4 hover:bg-accent/40 transition-colors", isSel && "bg-primary/5")}>
                <input
                  type="checkbox"
                  checked={isSel}
                  onChange={() => toggleSelect(c.id)}
                  className="w-4 h-4 accent-primary shrink-0"
                />
                <div className={cn(
                  "w-9 h-9 shrink-0 rounded-xl border flex items-center justify-center",
                  c.riskFlag ? "bg-rose-50 border-rose-100 text-rose-600" : "bg-primary/8 border-primary/10 text-primary"
                )}>
                  {c.riskFlag ? <AlertTriangle className="w-4 h-4" /> : <FileText className="w-4 h-4" />}
                </div>
                <div className="flex-1 min-w-0">
                  <button
                    onClick={() => navigate(`/drafting/editor/${c.id}`)}
                    className="block text-sm font-black text-foreground truncate hover:text-primary transition-colors"
                    title="点击打开合同编辑器"
                  >
                    {c.name}
                    {c.riskFlag && <span className="ml-2 align-middle text-[9px] font-black tracking-widest text-rose-600 bg-rose-50 border border-rose-200 rounded-full px-1.5 py-0.5">审查高风险</span>}
                  </button>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground tracking-widest">
                    <span>{c.contractNumber}</span>
                    <span className="w-px h-3 bg-border" />
                    <span>创建时间：{c.createdAt}</span>
                    <span className="w-px h-3 bg-border" />
                    <span>更新时间：{c.updatedAt}</span>
                    <span className="w-px h-3 bg-border" />
                    <span>创建律师：{c.creatorLabel}</span>
                    <span className="w-px h-3 bg-border" />
                    <span>负责律师：{c.ownerLawyerLabel}</span>
                    <span className="w-px h-3 bg-border" />
                    <span>状态：{c.statusLabel}</span>
                    <span className="w-px h-3 bg-border" />
                    <span>是否完成：{c.completedLabel}</span>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  <span className={cn("px-2.5 py-1 text-[10px] font-black tracking-widest rounded-full border shrink-0", st.cls)}>
                    {st.label}
                  </span>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    onClick={() => setPreviewItem(c)}
                    title="预览"
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                  >
                    <Eye className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => downloadWord(c)}
                    title="下载 Word（.doc）"
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:border-emerald-400/50 hover:text-emerald-600"
                  >
                    <FileType2 className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => downloadPdf(c)}
                    title="下载 PDF"
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                  >
                    <FileDown className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => deleteOne(c)}
                    title="删除"
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:border-rose-300 hover:bg-rose-50 hover:text-rose-600"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-between border-t border-border bg-secondary/20 px-6 py-3">
          <span className="text-[10px] font-bold text-muted-foreground tracking-widest uppercase">
            共 {filtered.length} 条记录
          </span>
          <span className="text-[10px] font-bold text-muted-foreground tracking-widest uppercase">
            第 1 / 1 页
          </span>
        </div>
      </motion.div>

      {/* 合同预览弹窗 */}
      <Dialog open={!!previewItem} onOpenChange={(open) => !open && setPreviewItem(null)}>
        <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>{previewItem?.name || "合同预览"}</DialogTitle>
            <DialogDescription>
              {previewItem ? (
                <span>
                  {previewItem.contractNumber} · {previewItem.statusLabel} · 负责律师：
                  {previewItem.ownerLawyerLabel}
                </span>
              ) : (
                <span>合同详情</span>
              )}
            </DialogDescription>
          </DialogHeader>
          {previewItem && (
            <div className="flex-1 min-h-0 overflow-y-auto rounded-xl border border-border bg-card p-6">
              <div
                className="text-sm leading-relaxed text-foreground whitespace-pre-wrap"
                dangerouslySetInnerHTML={{
                  __html:
                    previewItem.content ||
                    '<p class="text-center text-muted-foreground py-12">暂无合同正文</p>',
                }}
              />
            </div>
          )}
          <DialogFooter className="mt-4 gap-2">
            <button
              type="button"
              onClick={() => setPreviewItem(null)}
              className="rounded-xl border border-border bg-card px-4 py-2 text-xs font-black tracking-widest transition-colors hover:bg-accent"
            >
              关闭
            </button>
            {previewItem && (
              <button
                type="button"
                onClick={() => {
                  setPreviewItem(null);
                  navigate(`/drafting/editor/${previewItem.id}`);
                }}
                className="rounded-xl bg-primary px-4 py-2 text-xs font-black tracking-widest text-primary-foreground transition-colors hover:bg-primary/90"
              >
                去编辑
              </button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
}

function now(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
