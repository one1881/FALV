import { Fragment, useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { cn } from "../../lib/utils";
import { Scale, Download, FileText, ShieldCheck, FolderOpen, Loader2, Music } from "lucide-react";
import { getCaseEvidence, getLitigationCases, downloadCaseDocPdf, type CaseEvidencePayload, type LitigationCaseItem } from "../../lib/api/litigation";
import { EmptyCaseHint } from "../../app/components/LitigationStageBar";
import { PageHeader } from "../components/PageHeader";
import { MediaPlayer } from "./LitigationConfirmPreview";

/** 7 大类证据标准模板（参考真实法院证据目录格式） */
const STANDARD_TEMPLATES = [
  { key: "alert", label: "报警 / 立案", desc: "报警回执、受案回执、立案通知书、出警记录" },
  { key: "statements", label: "双方笔录", desc: "询问笔录、调查笔录、陈述与申辩" },
  { key: "witness", label: "证人证言", desc: "证人身份证明、证人出庭作证申请书" },
  { key: "appraisal", label: "伤情鉴定", desc: "司法鉴定意见书、鉴定机构资质、鉴定人资格" },
  { key: "medical", label: "病历票据", desc: "门诊病历、住院记录、医疗费发票、费用清单" },
  { key: "audiovisual", label: "视听资料", desc: "录音录像原始载体、文字整理稿、截图打印件" },
  { key: "photos", label: "伤情照片", desc: "伤情照片、现场照片、拍摄时间地点说明" },
];

const EVIDENCE_COLUMNS = ["序号", "证据名称", "证据来源", "证据种类", "证明目的", "有利/证明力", "页码", "详情"];

function normalizeCatalog(payload: CaseEvidencePayload | null): any[] {
  const catalog = payload?.evidence_catalog || [];
  return Array.isArray(catalog) ? catalog : [];
}

/** 证据展开行：左侧缩略图 + 右侧 4 字段（按你画的 PDF 草图） */
function EvidenceDetailRow({ item, detail = {}, caseId }: { item: any; detail?: any; caseId: string }) {
  // 详情字段优先取 DB 层 items（evidence_id/ocr_text/entities/file_path），没有再回退目录行
  const evidenceId = detail.evidence_id || item.evidence_id;
  const itemFileUrl = evidenceId && caseId
    ? `/api/litigation/cases/${caseId}/materials/${evidenceId}/file`
    : undefined;
  const fileType = (detail.evidence_type || item.evidence_type || "").toLowerCase();
  const ai = detail.entities || item.entities || {};
  const summary = ai.summary || detail.ocr_text || item.summary || item.ocr_text || "（AI 未生成总结）";
  const useful = ai.useful ?? (detail.useful ?? item.useful);
  const level = ai.evidence_level || detail.evidence_level || item.evidence_level || "中";
  const levelLabel = level === "A" ? "高" : level === "B" ? "中" : level === "C" ? "低" : "中";
  const keyInfoRaw = ai.key_facts || ai.key_info || detail.entities || item.proof_purpose || "—";
  const keyInfo = Array.isArray(keyInfoRaw) ? keyInfoRaw.join("、")
                  : typeof keyInfoRaw === "object" ? Object.values(keyInfoRaw).join("、")
                  : String(keyInfoRaw);
  const useLabel = useful === true ? "有利点" : useful === false ? "不利点" : "说明";
  const useReason = ai.proof_purpose || detail.proof_purpose || item.proof_purpose || "—";
  const useColor = useful === true ? "emerald" : useful === false ? "rose" : "slate";

  return (
    <div className="grid gap-4 sm:grid-cols-[100px_1fr]">
      <div className="flex h-24 w-24 items-center justify-center overflow-hidden rounded-lg border border-border bg-card">
        {fileType.startsWith("image") && itemFileUrl ? (
          <MediaPlayer url={itemFileUrl} variant="image" className="h-24 w-24 object-cover" />
        ) : fileType.startsWith("video") && itemFileUrl ? (
          <MediaPlayer url={itemFileUrl} variant="video" className="h-24 w-24 object-cover" />
        ) : fileType.startsWith("audio") && itemFileUrl ? (
          <Music className="h-8 w-8 text-muted-foreground" />
        ) : (
          <FileText className="h-8 w-8 text-muted-foreground" />
        )}
      </div>
      <div className="space-y-2 text-xs">
        <Field label="① 总结的文字" value={summary} />
        <div className="grid grid-cols-3 gap-3">
          <Field label="② 重要等级" value={levelLabel} />
          <Field label="③ 重点信息" value={keyInfo} />
          <Field label="④ {useLabel}" value={useReason} color={useColor} />
        </div>
        {itemFileUrl && (fileType.startsWith("audio") || fileType.startsWith("video")) && (
          <MediaPlayer url={itemFileUrl} variant={fileType.startsWith("audio") ? "audio" : "video"} />
        )}
      </div>
    </div>
  );
}

function Field({ label, value, color = "slate" }: { label: string; value: string; color?: "slate" | "amber" | "emerald" | "rose" }) {
  const colors = {
    slate: "border-border bg-secondary/30 text-foreground",
    amber: "border-amber-300 bg-amber-50 text-amber-900",
    emerald: "border-emerald-300 bg-emerald-50 text-emerald-900",
    rose: "border-rose-300 bg-rose-50 text-rose-900",
  };
  return (
    <div className="rounded-lg border px-3 py-2">
      <div className="text-[10px] font-black uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className={"mt-1 font-medium leading-6 " + colors[color]}>{value}</div>
    </div>
  );
}

export function LitigationEvidence() {
  const [searchParams] = useSearchParams();
  const caseId = searchParams.get("case_id") || "";

  const [cases, setCases] = useState<LitigationCaseItem[]>([]);
  const [activeCase, setActiveCase] = useState(caseId);
  const [payload, setPayload] = useState<CaseEvidencePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  // 拉取案件列表
  useEffect(() => {
    getLitigationCases()
      .then((res) => {
        setCases(res.items || []);
        if (!activeCase && res.items?.length > 0) {
          const first = res.items[0];
          setActiveCase(first.case_id);
        }
      })
      .catch(() => setCases([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 拉取证据数据
  useEffect(() => {
    if (!activeCase) {
      setPayload(null);
      return;
    }
    setLoading(true);
    setError("");
    getCaseEvidence(activeCase)
      .then((data) => setPayload(data))
      .catch((e: any) => {
        setError(e?.message || "加载证据数据失败");
        setPayload(null);
      })
      .finally(() => setLoading(false));
  }, [activeCase]);

  const catalog = normalizeCatalog(payload);
  const stats = payload?.extraction_stats || {};
  const ready = catalog.length > 0;

  return (
    <div className="max-w-7xl space-y-8 pb-32 pt-8">
      {/* Hero（中性色，符合去色定稿） */}
      <PageHeader title="证据管理" description="已识别材料自动归类为法院提交格式的证据目录，可导出有利点 / 不利点 PDF。" />


      {/* 案件选择 */}
      {cases.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-[1.5rem] border border-border bg-card/90 px-6 py-4 shadow-sm">
          <div className="flex items-center gap-2 text-xs font-black text-foreground">
            <FolderOpen className="h-4 w-4 text-primary" />
            当前案件
          </div>
          <select
            value={activeCase}
            onChange={(e) => setActiveCase(e.target.value)}
            className="rounded-full border border-border bg-background px-4 py-1.5 text-xs font-bold text-foreground outline-none focus:border-primary/50"
          >
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.case_id} · {c.case_title || "未命名案件"}
              </option>
            ))}
          </select>
          <div className="ml-auto flex items-center gap-2 text-[11px] font-bold text-muted-foreground">
            <span className="rounded-full bg-primary/10 px-3 py-1 text-primary">
              {stats.llm_extracted ?? catalog.length} 项已识别
            </span>
            <span className="rounded-full bg-muted px-3 py-1">共 {catalog.length} 项</span>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs font-bold text-amber-700">
          {error}（案件可能尚未归档，可先到「案件受理」完成归档）
        </div>
      )}

      {loading ? (
        <div className="flex flex-col items-center justify-center rounded-[1.5rem] border border-dashed border-border bg-card/60 px-8 py-16 text-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <div className="mt-4 text-sm font-black text-foreground">正在加载证据目录…</div>
        </div>
      ) : !activeCase ? (
        <EmptyCaseHint />
      ) : (
        <section className="space-y-5">
          {/* 证据目录（法院提交格式） */}
          <div className="overflow-hidden rounded-[1.5rem] border border-border bg-card/90 shadow-sm">
            <div className="flex flex-wrap items-center gap-3 border-b border-border px-6 py-5">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-primary" />
                <div className="text-sm font-black text-foreground">证据目录（法院提交格式）</div>
              </div>
              <span className="rounded-full bg-primary/10 px-3 py-1 text-[10px] font-black text-primary">
                {payload?.case?.case_id || activeCase}
              </span>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => downloadCaseDocPdf(activeCase, "evidence-favorable", "有利点.pdf")}
                  className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300/50 px-4 py-1.5 text-[11px] font-bold text-emerald-700 transition-colors hover:bg-emerald-50"
                >
                  <Download className="h-3.5 w-3.5" /> 下载有利点 PDF
                </button>
                <button
                  type="button"
                  onClick={() => downloadCaseDocPdf(activeCase, "evidence-unfavorable", "不利点.pdf")}
                  className="inline-flex items-center gap-1.5 rounded-full border border-rose-300/50 px-4 py-1.5 text-[11px] font-bold text-rose-700 transition-colors hover:bg-rose-50"
                >
                  <Download className="h-3.5 w-3.5" /> 下载不利点 PDF
                </button>
              </div>
            </div>

            {catalog.length === 0 ? (
              <div className="flex flex-col items-center justify-center px-8 py-16 text-center">
                <ShieldCheck className="h-10 w-10 text-muted-foreground/50" />
                <div className="mt-4 text-sm font-black text-foreground">证据目录尚未生成</div>
                <div className="mt-2 max-w-md text-xs font-bold leading-6 text-muted-foreground">
                  归档案件并完成材料识别后，这里会自动生成按法院格式排列的证据目录。
                </div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left">
                  <thead>
                    <tr className="border-b border-border bg-muted/50">
                      {EVIDENCE_COLUMNS.map((col) => (
                        <th key={col} className="px-5 py-3 text-[11px] font-black tracking-widest text-muted-foreground">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {catalog.map((item: any, idx: number) => {
                      const expanded = expandedIdx === idx;
                      return (
                        <Fragment key={idx}>
                          <tr
                            className={cn(
                              "cursor-pointer border-b border-border/60 transition-colors hover:bg-muted/30",
                              expanded && "bg-accent/30"
                            )}
                            onClick={() => setExpandedIdx(expanded ? null : idx)}
                          >
                            <td className="px-5 py-3.5 text-xs font-bold text-muted-foreground">
                              {item.evidence_no ?? idx + 1}
                            </td>
                            <td className="px-5 py-3.5 text-xs font-black text-foreground">
                              {item.evidence_name || item.name || "未命名证据"}
                              {item.group_hint && (
                                <span className="ml-2 rounded-full bg-primary/10 px-2 py-0.5 text-[9px] font-bold text-primary">
                                  {item.group_hint}
                                </span>
                              )}
                            </td>
                            <td className="px-5 py-3.5 text-xs font-bold text-muted-foreground">
                              {item.source_file || item.evidence_source || item.source || "—"}
                            </td>
                            <td className="px-5 py-3.5 text-xs font-bold text-muted-foreground">
                              {item.evidence_type || item.group_name || item.type || "—"}
                            </td>
                            <td className="px-5 py-3.5 text-xs font-bold leading-6 text-foreground/80">
                              {item.proof_purpose || item.purpose || "—"}
                            </td>
                            <td className="px-5 py-3.5">
                              <div className="flex flex-wrap items-center gap-1.5">
                                {item.useful !== undefined && item.useful !== null ? (
                                  <span
                                    className={cn(
                                      "rounded-full border px-2 py-0.5 text-[9px] font-black",
                                      item.useful ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-rose-200 bg-rose-50 text-rose-700",
                                    )}
                                  >
                                    {item.useful ? "有利" : "不利"}
                                  </span>
                                ) : null}
                                {item.evidence_level ? (
                                  <span
                                    className={cn(
                                      "rounded-full border px-2 py-0.5 text-[9px] font-black",
                                      item.evidence_level === "A"
                                        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                                        : item.evidence_level === "B"
                                        ? "border-amber-200 bg-amber-50 text-amber-700"
                                        : "border-slate-200 bg-slate-100 text-slate-600",
                                    )}
                                  >
                                    证明力 {item.evidence_level}
                                  </span>
                                ) : null}
                                {item.useful === undefined && !item.evidence_level && <span className="text-xs font-bold text-muted-foreground">—</span>}
                              </div>
                            </td>
                            <td className="px-5 py-3.5 text-xs font-bold text-muted-foreground">
                              {item.page_range || item.page || "—"}
                            </td>
                            <td className="px-3 py-3.5 text-xs font-bold text-muted-foreground">
                              {expanded ? "收起 ▲" : "展开 ▼"}
                            </td>
                          </tr>
                          {expanded && (
                            <tr className="bg-secondary/30">
                              <td colSpan={8} className="px-5 py-5">
                                <EvidenceDetailRow
                                  item={item}
                                  detail={
                                    (payload?.items || []).find(
                                      (it: any) => (it.evidence_name || it.name) === (item.evidence_name || item.name)
                                    ) || {}
                                  }
                                  caseId={activeCase}
                                />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* 7 类标准模板补全 */}
          <div className="rounded-[1.5rem] border border-border bg-card/90 p-6 shadow-sm">
            <div className="mb-1 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-primary" />
              <div className="text-sm font-black text-foreground">证据种类标准模板</div>
            </div>
            <div className="mb-5 text-xs font-bold text-muted-foreground">
              未覆盖的证据类别，可参考以下标准模板补充完善后再入册
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {STANDARD_TEMPLATES.map((t) => (
                <div key={t.key} className="rounded-xl border border-border bg-card px-4 py-3.5 transition-colors hover:border-primary/30 hover:bg-accent/40">
                  <div className="text-xs font-black text-foreground">{t.label}</div>
                  <div className="mt-1.5 text-[11px] font-bold leading-5 text-muted-foreground">{t.desc}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 装订实务规则 */}
          <div className={cn("rounded-[1.5rem] border border-border bg-card/90 p-6 shadow-sm")}>
            <div className="mb-4 flex items-center gap-2">
              <Scale className="h-4 w-4 text-primary" />
              <div className="text-sm font-black text-foreground">装订实务规则</div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {[
                "证据册按序号装订，目录与证据一一对应，页码连续标注",
                "原件与复印件分开存放，复印件首页注明「与原件核对无异」",
                "视听资料附原始载体 + 文字整理稿，截图打印件注明时间来源",
              ].map((rule, idx) => (
                <div key={idx} className="rounded-xl bg-muted/60 px-4 py-3 text-xs font-bold leading-6 text-muted-foreground">
                  <span className="mr-2 text-primary">{idx + 1}.</span>
                  {rule}
                </div>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
