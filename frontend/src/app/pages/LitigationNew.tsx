import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { cn } from "../../lib/utils";
import {
  Upload,
  FolderUp,
  FileText,
  Image as ImageIcon,
  Film,
  Music,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ArrowLeft,
  ArrowRight,
  Sparkles,
  Loader2,
  Scale,
  ShieldCheck,
  ChevronDown,
  Trash2,
  FileCheck2,
  ChevronRight,
  Eye,
  EyeOff,
  Edit3,
} from "lucide-react";
import {
  createLitigationIntake,
  uploadIntakeFiles,
  analyzeIntakeMaterials,
  analyzeIntakeMaterial,
  getIntake,
  confirmIntakeBlock,
  archiveIntakeCase,
  getLitigationCases,
  type IntakeMaterial,
  type ConfirmationBlock,
  type LitigationCaseItem,
} from "../../lib/api/litigation";
import { LitigationConfirmPreview, type EvidenceItem, type Useful } from "./LitigationConfirmPreview";
import { TaskProgress } from "../../app/components/TaskProgress";

const STEPS = [
  { key: "upload", label: "上传材料" },
  { key: "recognition", label: "确认前整理" },
  { key: "confirm", label: "律师确认" },
  { key: "case", label: "归档" },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

interface LocalMaterial {
  file: File;
  id: string;
  preview?: string;
}

function fileIcon(type: string) {
  if (type.startsWith("image")) return <ImageIcon className="h-4 w-4" />;
  if (type.startsWith("video")) return <Film className="h-4 w-4" />;
  if (type.startsWith("audio")) return <Music className="h-4 w-4" />;
  return <FileText className="h-4 w-4" />;
}

type ConfirmKind = "image_object" | "image_text" | "video" | "audio" | "unrecognized";

type ConfirmItem = {
  id: string;
  fileName: string;
  kind: ConfirmKind;
  title: string;
  summary: string;
  fullText?: string;
  timePoints?: string[];
  duplicate?: boolean;
  removed?: boolean;
  reason?: string;
};

function isLandscapeImage(name: string) {
  return /(风景|景色|天空|海景|山景|日落|背景|wallpaper|scenery)/i.test(name);
}

function isLikelyTextImage(name: string) {
  return /(文字|聊天|截图|票据|回执|通知|合同|文书|证书|证明|记录|清单|凭证|单据)/i.test(name);
}

function buildConfirmItems(items: IntakeMaterial[]): ConfirmItem[] {
  const seen = new Set<string>();
  const result: ConfirmItem[] = [];
  items.forEach((item, index) => {
    const fileName = item.file_name || `材料${index + 1}`;
    const normalized = fileName.replace(/\s+/g, "").toLowerCase();
    const type = item.file_type || "document";
    const summary = item.analysis_text || item.summary || "识别结果待补充";
    const isDuplicate = seen.has(normalized);
    if (!isDuplicate) {
      seen.add(normalized);
    }

    if (isDuplicate) {
      result.push({
        id: `${normalized}-dup-${index}`,
        fileName,
        kind: "unrecognized",
        title: `${fileName}（重复）`,
        summary: "重复材料，已自动去除",
        duplicate: true,
        removed: true,
        reason: "重复上传",
      });
      return;
    }

    if (type.startsWith("image")) {
      if (isLandscapeImage(fileName)) {
        result.push({
          id: `${normalized}-landscape-${index}`,
          fileName,
          kind: "unrecognized",
          title: `${fileName}（瑕疵）`,
          summary: "瑕疵图片：仅风景/背景，无人或物主体，已建议去除",
          removed: true,
          reason: "仅风景或背景，无人/物主体",
        });
        return;
      }
      result.push({
        id: `${normalized}-object-${index}`,
        fileName,
        kind: "image_object",
        title: `${fileName} · 物体图片`,
        summary: item.key_facts?.length ? `物体图片摘要：${item.key_facts.slice(0, 2).join("；")}` : `物体图片摘要：${summary}`,
        fullText: item.analysis_text || item.summary || summary,
      });
      if (isLikelyTextImage(fileName) || item.analysis_text) {
        result.push({
          id: `${normalized}-text-${index}`,
          fileName,
          kind: "image_text",
          title: `${fileName} · 文字类`,
          summary: `文字类摘要：${summary}`,
          fullText: item.analysis_text || item.summary || summary,
        });
      }
      return;
    }

    if (type.startsWith("video")) {
      result.push({
        id: `${normalized}-video-${index}`,
        fileName,
        kind: "video",
        title: fileName,
        summary: `视频摘要：${summary}`,
        timePoints: ["00:00-00:10 画面概览", "00:10-00:30 关键情节", "00:30-结束 结果总结"],
        fullText: item.analysis_text || item.summary || summary,
      });
      return;
    }

    if (type.startsWith("audio")) {
      result.push({
        id: `${normalized}-audio-${index}`,
        fileName,
        kind: "audio",
        title: fileName,
        summary: `音频摘要：${summary}`,
        timePoints: ["00:00-00:15 开场", "00:15-00:45 核心内容", "00:45-结束 结论"],
        fullText: item.analysis_text || item.summary || summary,
      });
      return;
    }

    result.push({
      id: `${normalized}-unknown-${index}`,
      fileName,
      kind: "unrecognized",
      title: fileName,
      summary: "该材料暂未识别成功，已放入未识别区",
      reason: "识别失败或类型不明确",
      fullText: item.analysis_text || item.summary || summary,
    });
  });

  return result;
}

function groupConfirmItems(items: ConfirmItem[]) {
  return {
    images: items.filter((item) => item.kind === "image_object" || item.kind === "image_text"),
    videos: items.filter((item) => item.kind === "video"),
    audios: items.filter((item) => item.kind === "audio"),
    unrecognized: items.filter((item) => item.kind === "unrecognized"),
  };
}


export function LitigationNew() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<StepKey>("upload");
  const [intakeId, setIntakeId] = useState<string>("");
  const [localMaterials, setLocalMaterials] = useState<LocalMaterial[]>([]);
  const [uploaded, setUploaded] = useState<IntakeMaterial[]>([]);
  const [blocks, setBlocks] = useState<ConfirmationBlock[]>([]);
  const [editingBlockId, setEditingBlockId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<Record<string, any>>({});
  // 材料整理进度（逐文件）
  const [analyzeTotal, setAnalyzeTotal] = useState(0);
  const [analyzeDone, setAnalyzeDone] = useState(0);
  const [analyzeStartedAt, setAnalyzeStartedAt] = useState(0);

  // 把后端 confirmation_blocks 适配成 EvidenceItem（供 LitigationConfirmPreview 使用）
  const evidenceList = useMemo<EvidenceItem[]>(() => {
    return blocks.map((b) => {
      const ai = (b.ai_result && typeof b.ai_result === "object" ? b.ai_result : null) || (b.data && typeof b.data === "object" ? b.data : null);
      return {
        id: b.block_id,
        type: mapBlockType(b.block_type, ai, b.title),
        name: b.title || b.source_file || "未命名材料",
        summary: ai?.summary || (typeof b.ai_result === "string" ? b.ai_result : "") || "",
        useful: ai?.useful ?? null,
        evidence_level: ai?.evidence_level ?? "C",
        time_range: ai?.time_range || ai?.key_events?.[0]?.time,
        key_events: Array.isArray(ai?.key_events) ? ai.key_events : [],
        detected_objects: ai?.detected_objects,
        transcript: ai?.transcript || ai?.audio_transcript,
        visual_description: ai?.visual_description,
        key_facts: ai?.key_facts,
        file_url: b.material_id ? `/api/litigation/intake/${intakeId}/materials/${b.material_id}/file` : undefined,
        confirmed: b.status === "confirmed",
      };
    });
  }, [blocks]);
  const [archiving, setArchiving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");

  // 案件信息（归档用）
  const [caseInfo, setCaseInfo] = useState({
    case_summary: "",
    dispute_amount: "",
    plaintiff: "",
    defendant: "",
  });

  // 归档去向：新建案件 或 归档到已有案件小库（编号·名称下拉，与证据管理页同一套数据）
  const [archiveMode, setArchiveMode] = useState<"new" | "existing">("new");
  const [caseOptions, setCaseOptions] = useState<LitigationCaseItem[]>([]);
  const [targetCaseId, setTargetCaseId] = useState("");

  // 识别步的逐项进度（前端展示，真实识别结果以后端返回为准）
  const [recognized, setRecognized] = useState<string[]>([]);

  /* ---------------- 上传 ---------------- */
  const pickFolder = () => inputRef.current?.click();

  const onFilesChosen = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const list: LocalMaterial[] = Array.from(files).map((file) => ({
      file,
      id: `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 8)}`,
      preview: file.type.startsWith("image") ? URL.createObjectURL(file) : undefined,
    }));
    setLocalMaterials((prev) => [...prev, ...list]);
  };

  const removeLocal = (id: string) => {
    setLocalMaterials((prev) => prev.filter((m) => m.id !== id));
  };

  const canUpload = localMaterials.length > 0 && !busy;

  const startUpload = async () => {
    if (!canUpload) return;
    setBusy(true);
    setError("");
    try {
      // 1. 创建受理记录
      const intake = await createLitigationIntake({
        source: "folder_upload",
        case_type: "",
        customer_name: caseInfo.plaintiff || undefined,
        opposite_party: caseInfo.defendant || undefined,
      });
      setIntakeId(intake.intake_id);

      // 2. 上传所有文件
      const files = localMaterials.map((m) => m.file);
      const result = await uploadIntakeFiles(intake.intake_id, files);
      setUploaded(result.saved || []);

      // 3. 进入整理步骤（可见独立环节，识别完成后停留在此步，律师可手动跳到「律师确认」）
      setRecognized([]);
      setStep("recognition");

      // 4. 并发材料整理（图片视觉 / 音频转写 / 视频抽帧 / 字段抽取），每完成一个更新进度
      const materials = result.saved || [];
      setAnalyzeTotal(materials.length);
      setAnalyzeDone(0);
      setAnalyzeStartedAt(Date.now());
      const finishedNames = new Set<string>();
      await Promise.allSettled(
        materials.map((m) =>
          analyzeIntakeMaterial(intake.intake_id, m.material_id)
            .catch(() => null)
            .finally(() => {
              finishedNames.add(m.file_name);
              setRecognized(Array.from(finishedNames));
              setAnalyzeDone(finishedNames.size);
            }),
        ),
      );

      // 5. 整理完成，把结果写到 confirmation_blocks 缓存（停留在确认前步骤，律师点"查看识别结果"进入确认）
      const detail = await getIntake(intake.intake_id);
      const list = detail?.confirmation_blocks || [];
      setBlocks(list);
    } catch (e: any) {
      setError(e?.message || "上传失败，请确认后端已启动");
    } finally {
      setBusy(false);
    }
  };

  /* ---------------- 识别 ---------------- */
  const goStep = useCallback(
    async (next: StepKey) => {
      setError("");
      if (next === "recognition") {
        // 模拟逐项识别动画（真实文本识别由后端完成）
        setRecognized([]);
        const names = uploaded.length > 0 ? uploaded.map((m) => m.file_name) : localMaterials.map((m) => m.file.name);
        for (let i = 0; i < names.length; i++) {
          await new Promise((r) => setTimeout(r, 220));
          setRecognized((prev) => [...prev, names[i]]);
        }
        setStep("recognition");
        return;
      }
      if (next === "confirm") {
        // 拉取确认块
        try {
          const detail = await getIntake(intakeId);
          const list = detail?.confirmation_blocks || [];
          setBlocks(list);
          if (list.length === 0) {
            // 后端无确认块时给占位提示，仍可进入
          }
        } catch (e: any) {
          setError(e?.message || "加载识别结果失败");
        }
        setStep("confirm");
        return;
      }
      if (next === "case") {
        // 自动归纳案件要素：用已确认材料的 AI 摘要拼出证据主题，律师可手改
        setCaseInfo((v) => {
          if (v.case_summary.trim()) return v;
          const confirmed = blocks.filter((b) => b.status === "confirmed");
          const lines = confirmed.slice(0, 6).map((b, i) => {
            const ai = b.ai_result && typeof b.ai_result === "object" ? b.ai_result : ({} as Record<string, any>);
            const s = String(ai.summary || ai.proof_purpose || b.title || "").slice(0, 40);
            return `（${i + 1}）${b.title || "材料"}——${s}`;
          });
          if (lines.length === 0) return v;
          const summary = `本案共归档 ${confirmed.length} 项证据材料，主题概览：${lines.join("；")}。`;
          return { ...v, case_summary: summary };
        });
        // 回填当事人（受理时录过的客户/对方）
        if (intakeId) {
          getIntake(intakeId)
            .then((d: any) => {
              const it = d?.intake || {};
              setCaseInfo((v) => ({
                ...v,
                plaintiff: v.plaintiff || it.customer_name || "",
                defendant: v.defendant || it.opposite_party || "",
              }));
            })
            .catch(() => {});
        }
        // 案件小库（编号 · 名称），供「归档到已有案件」选择
        getLitigationCases(50)
          .then((r) => setCaseOptions(r.items || []))
          .catch(() => setCaseOptions([]));
        setStep("case");
        return;
      }
      setStep(next);
    },
    [uploaded, localMaterials, intakeId, blocks],
  );

  const goBack = () => {
    const idx = STEPS.findIndex((s) => s.key === step);
    if (idx > 0) setStep(STEPS[idx - 1].key);
  };

  /* ---------------- 确认 ---------------- */
  const confirmGroup = async (block: ConfirmationBlock, status: "confirmed" | "removed", edited?: Record<string, any>) => {
    if (!intakeId || !block.block_id) return;
    const next = status === "confirmed" ? { ...block, status: "confirmed", confirmed_result: edited ?? block.ai_result ?? block.data ?? null } : { ...block, status: "removed" };
    setBlocks((prev) => prev.map((b) => (b.block_id === block.block_id ? next : b)));
    try {
      await confirmIntakeBlock(intakeId, {
        block_id: block.block_id,
        status,
        confirmed_result: edited ?? block.ai_result ?? block.data ?? null,
      });
    } catch (e: any) {
      console.error("确认失败", e);
    }
  };

  const confirmAllPass = () => {
    setBlocks((prev) =>
      prev.map((b) => (b.status === "pending" ? { ...b, status: "confirmed" } : b)),
    );
  };

  const pendingCount = blocks.filter((b) => b.status === "pending").length;
  const groupedConfirmItems = useMemo(() => groupConfirmItems(buildConfirmItems(uploaded.length > 0 ? uploaded : [])), [uploaded]);

  /* ---------------- 归档 ---------------- */
  useEffect(() => {
    // 归档步骤仅保留手动提交
  }, [step]);

  // demo 联调：?demoIntake=INTAKE-xxx 直接加载已有受理单进确认步（验证图片/视频/音频预览用，不影响正常上传流程）
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const demo = params.get("demoIntake");
    if (!demo) return;
    (async () => {
      try {
        const detail = await getIntake(demo);
        setIntakeId(demo);
        const list = detail?.confirmation_blocks || [];
        setBlocks(list);
        setStep("confirm");
      } catch (e: any) {
        setError(e?.message || "加载 demo 受理单失败");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const archiveCase = async () => {
    if (archiveMode === "existing" && !targetCaseId) {
      setError("请先在「归档去向」中选择要归档到的案件");
      return;
    }
    setArchiving(true);
    setError("");
    try {
      const result = await archiveIntakeCase(intakeId, {
        target_case_id: archiveMode === "existing" ? targetCaseId : undefined,
        case_info: {
          case_title: caseInfo.case_summary ? `${caseInfo.plaintiff || '原告'} 与 ${caseInfo.defendant || '被告'} 纠纷` : undefined,
          case_summary: caseInfo.case_summary,
          plaintiff: caseInfo.plaintiff,
          defendant: caseInfo.defendant,
          claims: [caseInfo.dispute_amount ? `争议金额：${caseInfo.dispute_amount}` : ""] .filter(Boolean),
        },
        assessment: {},
      });
      const nextCaseId = result?.case_id || intakeId;
      navigate(`/litigation/evidence?case_id=${encodeURIComponent(nextCaseId)}`);
    } catch (e: any) {
      setError(e?.message || "归档失败");
    } finally {
      setArchiving(false);
    }
  };

  const isConfirmReady = blocks.length === 0 || pendingCount === 0;

  return (
    <div className="max-w-7xl space-y-8 pb-32 pt-8">
      {/* Hero（紧凑版：保留品牌蓝渐变，压缩高度） */}
      <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-blue-700 via-blue-600 to-blue-500 px-6 py-5 shadow-sm">
        <div className="absolute -right-10 -top-10 h-32 w-32 rounded-full bg-white/10 blur-2xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="inline-flex items-center gap-2 rounded-full bg-white/15 px-2.5 py-0.5 text-[9px] font-black tracking-[0.2em] text-white">
              <Scale className="h-3 w-3" />
              案件受理 · INTAKE
            </div>
            <h1 className="text-2xl font-black tracking-tight text-white">案件受理</h1>
          </div>
          <p className="max-w-xl text-[11px] font-bold leading-5 text-white/85">
            上传案件材料文件夹，系统自动整理图片、视频、音频内容，律师逐项确认后直接归档并进入证据管理。
          </p>
        </div>
      </section>


      {/* Stepper */}
      <div className="flex items-center gap-1 overflow-x-auto rounded-[1.5rem] border border-border bg-card/90 px-5 py-4 shadow-sm">
        {STEPS.map((s, index) => {
          const active = s.key === step;
          const done = STEPS.findIndex((x) => x.key === step) > index;
          return (
            <div key={s.key} className="flex items-center">
              {index > 0 && <div className={cn("mx-3 h-px w-8 sm:w-14", done || active ? "bg-primary/50" : "bg-border")} />}
              <button
                type="button"
                onClick={() => (done ? goStep(s.key) : undefined)}
                className={cn(
                  "flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs font-black tracking-widest transition-colors",
                  active && "bg-primary text-primary-foreground shadow-sm",
                  done && "bg-primary/10 text-primary",
                  !active && !done && "bg-muted text-muted-foreground",
                )}
              >
                {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className="text-[10px]">{index + 1}</span>}
                {s.label}
              </button>
            </div>
          );
        })}
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-xs font-bold text-red-600">
          <AlertTriangle className="h-4 w-4" />
          {error}
        </div>
      )}

      {/* 第一步：上传 */}
      {step === "upload" && (
        <section className="space-y-5">
          <div
            onClick={pickFolder}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              onFilesChosen(e.dataTransfer.files);
            }}
            className="group flex cursor-pointer flex-col items-center justify-center rounded-[2rem] border-2 border-dashed border-primary/30 bg-gradient-to-br from-blue-50 via-white to-sky-50/60 px-8 py-14 text-center transition-all hover:border-primary/60 hover:shadow-md"
          >
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 text-primary transition-transform group-hover:scale-110">
              <FolderUp className="h-8 w-8" />
            </div>
            <div className="mt-5 text-base font-black text-foreground">选择案件材料文件夹</div>
            <div className="mt-2 max-w-md text-xs font-bold leading-6 text-muted-foreground">
              支持选择整个文件夹，系统会自动读取内部的所有图片、视频、音频与文档。
              图片会自动判断是否清晰、是否拍到人、是否重复；音频与视频会提取核心内容。
            </div>
            <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-border bg-white px-5 py-2 text-xs font-black text-foreground shadow-sm transition-colors group-hover:border-primary/40">
              <Upload className="h-3.5 w-3.5" />
              选择文件夹
            </div>
            <input
              ref={inputRef}
              type="file"
              multiple
              webkitdirectory=""
              className="hidden"
              onChange={(e) => onFilesChosen(e.target.files)}
            />
          </div>

          {/* 材料统计 */}
          {localMaterials.length > 0 && (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {[
                { label: "图片", count: localMaterials.filter((m) => m.file.type.startsWith("image")).length, icon: <ImageIcon className="h-4 w-4" /> },
                { label: "视频", count: localMaterials.filter((m) => m.file.type.startsWith("video")).length, icon: <Film className="h-4 w-4" /> },
                { label: "音频", count: localMaterials.filter((m) => m.file.type.startsWith("audio")).length, icon: <Music className="h-4 w-4" /> },
                { label: "文档", count: localMaterials.filter((m) => !m.file.type.startsWith("image") && !m.file.type.startsWith("video") && !m.file.type.startsWith("audio")).length, icon: <FileText className="h-4 w-4" /> },
              ].map((s) => (
                <div key={s.label} className="flex items-center gap-3 rounded-2xl border border-border bg-card/90 px-4 py-4 shadow-sm">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary">{s.icon}</div>
                  <div>
                    <div className="text-xl font-black text-foreground">{s.count}</div>
                    <div className="text-[10px] font-bold tracking-widest text-muted-foreground">{s.label}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 材料列表 */}
          {localMaterials.length > 0 && (
            <div className="rounded-[1.5rem] border border-border bg-card/90 p-5 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <div className="text-sm font-black text-foreground">已选材料（{localMaterials.length}）</div>
                <button type="button" onClick={pickFolder} className="text-xs font-bold text-primary hover:underline">
                  继续添加
                </button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {localMaterials.map((m) => (
                  <div key={m.id} className="group flex items-center gap-3 rounded-xl border border-border bg-card px-3 py-2.5">
                    {m.preview ? (
                      <img src={m.preview} alt="" className="h-9 w-9 rounded-lg object-cover" />
                    ) : (
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                        {fileIcon(m.file.type)}
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-bold text-foreground">{m.file.name}</div>
                      <div className="text-[10px] font-bold text-muted-foreground">
                        {(m.file.size / 1024 / 1024).toFixed(2)} MB
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeLocal(m.id)}
                      className="text-muted-foreground transition-colors hover:text-red-500"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 底部操作 */}
          <div className="flex items-center justify-between rounded-[1.5rem] border border-border bg-card/95 px-6 py-4 shadow-sm">
            <div className="text-xs font-bold text-muted-foreground">
              {canUpload ? `共 ${localMaterials.length} 份材料，上传后进入确认前整理` : "请先选择材料文件夹"}
            </div>
            <button
              type="button"
              disabled={!canUpload}
              onClick={startUpload}
              className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-2.5 text-xs font-black text-primary-foreground shadow-sm transition-all hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
              上传并开始整理
            </button>
          </div>
        </section>
      )}

      {/* 第二步：识别进度 */}
      {step === "recognition" && (
        <section className="rounded-[1.5rem] border border-border bg-card/90 p-6 shadow-sm">
          <div className="mb-5 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <div className="text-sm font-black text-foreground">确认前整理中</div>
            <div className="ml-auto text-xs font-bold text-muted-foreground">
              图片：清晰度 / 人物 / 文字 · 视频：人物、位置、时间 · 音频：核心内容
            </div>
          </div>
          <div className="space-y-2.5">
            {(uploaded.length > 0 ? uploaded.map((m) => m.file_name) : localMaterials.map((m) => m.file.name)).map((name, idx) => {
              const done = recognized.includes(name);
              return (
                <div key={`${name}-${idx}`} className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3">
                  <div className="text-muted-foreground">{fileIcon(name.split(".").pop() || "")}</div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-bold text-foreground">{name}</div>
                    <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn("h-full rounded-full transition-all duration-500", done ? "bg-primary" : "bg-primary/40 animate-pulse")}
                        style={{ width: done ? "100%" : "60%" }}
                      />
                    </div>
                  </div>
                  {done ? (
                    <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-primary" />
                  ) : (
                    <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin text-muted-foreground" />
                  )}
                </div>
              );
            })}
          </div>

          {/* 确认前整理进度条：显示已完成/总数 + 预估剩余时间 */}
          {analyzeTotal > 0 && (
            <TaskProgress
              title="确认前整理中"
              current={analyzeDone}
              total={analyzeTotal}
              startedAt={analyzeStartedAt}
            />
          )}
          {analyzeTotal === 0 && busy && (
            <TaskProgress title="正在准备上传与分析…" startedAt={Date.now()} />
          )}

          <div className="mt-6 flex items-center justify-between">
            <button type="button" onClick={goBack} className="inline-flex items-center gap-2 rounded-full border border-border px-5 py-2.5 text-xs font-bold text-foreground transition-colors hover:bg-accent">
              <ArrowLeft className="h-4 w-4" /> 上一步
            </button>
            <button
              type="button"
              onClick={() => goStep("confirm")}
              disabled={analyzeTotal > 0 && analyzeDone < analyzeTotal}
              className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-2.5 text-xs font-black text-primary-foreground shadow-sm transition-all hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              查看识别结果 <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </section>
      )}

      {/* 第三步：律师确认（复用 LitigationConfirmPreview 组件，三层 tab：文件夹 / 子类 / 有用性） */}
      {step === "confirm" && (
        <>
          <LitigationConfirmPreview
            initialItems={evidenceList}
            showHero={false}
            onConfirmItem={async (id, status) => {
              const block = blocks.find((b) => b.block_id === id);
              if (!block) return;
              try {
                await confirmIntakeBlock(intakeId, { block_id: id, status: status ? "confirmed" : "removed", confirmed_result: block.ai_result || block.data || null });
                setBlocks((prev) => prev.map((b) => (b.block_id === id ? { ...b, status: status ? "confirmed" : "removed" } : b)));
              } catch (e: any) {
                console.error("确认失败", e);
              }
            }}
            onSetUsefulItem={(id, useful) => {
              setBlocks((prev) => prev.map((b) => (b.block_id === id ? { ...b, ai_result: { ...((b.ai_result && typeof b.ai_result === "object") ? b.ai_result : {}), useful } } : b)));
            }}
          />

          {/* 确认完成 → 进入归档 */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1.5rem] border border-border bg-card/90 px-6 py-4 shadow-sm">
            <span className="text-xs font-black text-muted-foreground">
              已确认 {blocks.filter((b) => b.status === "confirmed").length} / 共 {blocks.length} 项
              <span className="ml-2 hidden text-[10px] font-bold text-muted-foreground/70 sm:inline">
                完成确认后即可归档并进入证据管理
              </span>
            </span>
            <button
              onClick={() => goStep("case")}
              className="inline-flex items-center gap-1.5 rounded-full bg-primary px-5 py-2.5 text-xs font-black text-primary-foreground shadow-sm transition-all hover:shadow-md"
            >
              下一步：归档 <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </>
      )}

      {/* 第四步：归档 */}
      {step === "case" && (
        <section className="space-y-5">
          {/* 归档去向：新建案件小库 或 归到已有案件（编号·名称，与证据管理页同一套） */}
          <div className="rounded-[1.5rem] border border-border bg-card/90 p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <FolderUp className="h-4 w-4 text-primary" />
              <div className="text-sm font-black text-foreground">归档去向</div>
              <div className="ml-auto text-[10px] font-bold text-muted-foreground">共 {caseOptions.length} 个已有案件</div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setArchiveMode("new")}
                className={cn(
                  "flex items-start gap-3 rounded-2xl border p-4 text-left transition-colors",
                  archiveMode === "new" ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-accent/30",
                )}
              >
                <CheckCircle2 className={cn("mt-0.5 h-4 w-4 shrink-0", archiveMode === "new" ? "text-primary" : "text-muted-foreground")} />
                <div>
                  <div className="text-xs font-black text-foreground">归档为新案件</div>
                  <div className="mt-1 text-[10px] font-bold leading-5 text-muted-foreground">生成新的 CASE 编号，材料固化进新案件小库</div>
                </div>
              </button>
              <button
                type="button"
                onClick={() => setArchiveMode("existing")}
                className={cn(
                  "flex items-start gap-3 rounded-2xl border p-4 text-left transition-colors",
                  archiveMode === "existing" ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-accent/30",
                )}
              >
                <CheckCircle2 className={cn("mt-0.5 h-4 w-4 shrink-0", archiveMode === "existing" ? "text-primary" : "text-muted-foreground")} />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-black text-foreground">归档到已有案件</div>
                  <div className="mt-1 text-[10px] font-bold leading-5 text-muted-foreground">材料追加进所选案件的证据库，不新建编号</div>
                </div>
              </button>
            </div>
            {archiveMode === "existing" && (
              <div className="mt-4">
                <label className="mb-1.5 block text-[11px] font-black tracking-widest text-muted-foreground">选择目标案件（编号 · 名称）</label>
                <div className="relative">
                  <select
                    value={targetCaseId}
                    onChange={(e) => setTargetCaseId(e.target.value)}
                    className="h-10 w-full appearance-none rounded-xl border border-border bg-background pl-3 pr-8 text-xs font-bold text-foreground outline-none focus:border-primary/50"
                  >
                    <option value="">请选择案件…</option>
                    {caseOptions.map((c) => (
                      <option key={c.case_id} value={c.case_id}>
                        {c.case_id} · {c.case_title}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/60" />
                </div>
              </div>
            )}
          </div>

          <div className="rounded-[1.5rem] border border-border bg-card/90 p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <FileText className="h-4 w-4 text-primary" />
              <div className="text-sm font-black text-foreground">案件要素（用于归档）</div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-[11px] font-black tracking-widest text-muted-foreground">案件描述</label>
                <textarea
                  value={caseInfo.case_summary}
                  onChange={(e) => setCaseInfo((v) => ({ ...v, case_summary: e.target.value }))}
                  rows={3}
                  placeholder="简要描述纠纷经过，如：2026年3月，王某向李某借款20万元，约定年化12%利息，至今未还。"
                  className="w-full rounded-xl border border-border bg-background px-3 py-2 text-xs font-bold text-foreground outline-none focus:border-primary/50"
                />
              </div>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { key: "dispute_amount" as const, label: "争议金额", placeholder: "如 200000 元" },
                  { key: "plaintiff" as const, label: "原告 / 委托方", placeholder: "当事人姓名或单位" },
                  { key: "defendant" as const, label: "被告 / 对方", placeholder: "对方姓名或单位" },
                ].map((f) => (
                  <div key={f.key}>
                    <label className="mb-1.5 block text-[11px] font-black tracking-widest text-muted-foreground">{f.label}</label>
                    <input
                      value={caseInfo[f.key]}
                      onChange={(e) => setCaseInfo((v) => ({ ...v, [f.key]: e.target.value }))}
                      placeholder={f.placeholder}
                      className="w-full rounded-xl border border-border bg-background px-3 py-2 text-xs font-bold text-foreground outline-none focus:border-primary/50"
                    />
                  </div>
                ))}
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between">
              <div className="text-[10px] font-bold text-muted-foreground">也可以留空，直接归档已确认材料</div>
              <button
                type="button"
                onClick={archiveCase}
                disabled={archiving}
                className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2 text-xs font-black text-primary-foreground shadow-sm transition-all hover:bg-primary/90 disabled:opacity-50"
              >
                {archiving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                归档案件，进入证据管理
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between rounded-[1.5rem] border border-border bg-card/95 px-6 py-4 shadow-sm">
            <button type="button" onClick={goBack} className="inline-flex items-center gap-2 rounded-full border border-border px-5 py-2.5 text-xs font-bold text-foreground transition-colors hover:bg-accent">
              <ArrowLeft className="h-4 w-4" /> 上一步
            </button>
            <button
              type="button"
              onClick={archiveCase}
              disabled={archiving}
              className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-2.5 text-xs font-black text-primary-foreground shadow-sm transition-all hover:bg-primary/90 disabled:opacity-50"
            >
              {archiving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              归档案件，进入证据管理
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

function ConfirmSection({
  title,
  icon,
  items,
  emptyHint,
}: {
  title: string;
  icon: React.ReactNode;
  items: ConfirmItem[];
  emptyHint: string;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const visibleItems = items;

  return (
    <div className="rounded-[1.5rem] border border-border bg-card/90 p-6 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        {icon}
        <div className="text-sm font-black text-foreground">{title}</div>
        <div className="ml-auto text-[11px] font-bold text-muted-foreground">{visibleItems.length} 项</div>
      </div>
      {visibleItems.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border px-5 py-10 text-center text-xs font-bold text-muted-foreground">
          {emptyHint}
        </div>
      ) : (
        <div className="space-y-3">
          {visibleItems.map((item) => {
            const isOpen = !!expanded[item.id];
            return (
              <div key={item.id} className={cn("rounded-2xl border p-4", item.removed ? "border-amber-200 bg-amber-50" : "border-border bg-card")}>
                <button
                  type="button"
                  onClick={() => setExpanded((prev) => ({ ...prev, [item.id]: !prev[item.id] }))}
                  className="flex w-full items-start gap-3 text-left"
                >
                  <div className="mt-1 flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    {item.kind === "video" ? <Film className="h-4 w-4" /> : item.kind === "audio" ? <Music className="h-4 w-4" /> : item.kind === "image_text" ? <FileText className="h-4 w-4" /> : item.kind === "image_object" ? <ImageIcon className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <div className="truncate text-xs font-black text-foreground">{item.title}</div>
                      {item.duplicate && <span className="rounded-full bg-muted px-2 py-0.5 text-[9px] font-bold text-muted-foreground">重复去除</span>}
                      {item.removed && !item.duplicate && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[9px] font-bold text-amber-700">已去除</span>}
                    </div>
                    <div className="mt-1 text-[11px] font-bold leading-6 text-muted-foreground">{item.summary}</div>
                    {item.timePoints && item.timePoints.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {item.timePoints.map((point) => (
                          <span key={point} className="rounded-full bg-primary/10 px-2 py-1 text-[10px] font-bold text-primary">{point}</span>
                        ))}
                      </div>
                    )}
                    {item.reason && <div className="mt-2 text-[10px] font-bold text-amber-700">{item.reason}</div>}
                  </div>
                  <div className="mt-1 text-muted-foreground">{isOpen ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</div>
                </button>
                {isOpen && item.fullText && (
                  <div className="mt-4 rounded-xl bg-muted/50 px-4 py-3 text-xs font-medium leading-7 text-foreground/90 whitespace-pre-wrap">
                    {item.fullText}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** ---------------- 后端 block_type → EvidenceItem.kind 映射 ---------------- */
function mapBlockType(blockType, ai, title) {
  const bt = (blockType || '').toLowerCase();
  if (bt === 'video') return 'video';
  if (bt === 'audio') return 'audio';
  if (bt === 'image') {
    // 优先用后端分类结果（QWEN/规则已判断 text/object），比前端正则可靠
    const cat = ai?.classification?.category;
    if (cat === 'text') return 'image_text';
    if (cat === 'object') return 'image_object';
    // fallback：无分类字段时才用关键词正则（避免 summary 里偶含"文字/记录"等词误判）
    const text = ((ai && (ai.proof_purpose || ai.summary)) || '') + ' ' + (title || '');
    const isText = /(聊天记录|截图|票据|回执|合同|文书|证明文件|借条|收据|快递单|聊天截图)/.test(text);
    return isText ? 'image_text' : 'image_object';
  }
  return 'image_object';
}
