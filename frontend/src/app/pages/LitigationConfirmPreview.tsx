import { useState, useEffect } from "react";
import { motion } from "motion/react";
import { cn } from "../../lib/utils";
import { PageHeader } from "../components/PageHeader";
import {
  Image as ImageIcon,
  Film,
  Music,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  ScanText,
  Box,
  Sparkles,
  Clock3,
  ThumbsUp,
  ThumbsDown,
  CheckCheck,
  FileText,
  ListFilter,
  X,
} from "lucide-react";

/** 清理 AI 摘要里的 markdown 标题/粗体/换行，截取前 maxLen 字 */
function cleanSummary(text: string | undefined, maxLen = 200) {
  if (!text) return "";
  const cleaned = text
    .replace(/^#+\s*/gm, "")
    .replace(/\*\*/g, "")
    .replace(/\n+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.length > maxLen ? cleaned.slice(0, maxLen) + "..." : cleaned;
}

/** 带鉴权媒体加载器：img/video/audio 标签无法带 Authorization 头，先 fetch blob 再渲染 */
export function MediaPlayer({ url, variant, className, onClick }: {
  url: string;
  variant: "thumb" | "image" | "video" | "audio";
  className?: string;
  onClick?: () => void;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    const token = localStorage.getItem("access_token");
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((blob) => { if (alive) setSrc(URL.createObjectURL(blob)); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [url]);
  if (failed) return null;
  if (!src) {
    if (variant === "video") return <div className="mt-2 flex h-32 w-full items-center justify-center rounded-xl border border-border bg-secondary/30 text-[11px] font-bold text-muted-foreground">视频加载中…</div>;
    if (variant === "audio") return <div className="mt-2 h-9 w-full animate-pulse rounded-lg bg-secondary/30" />;
    return <div className="h-16 w-16 animate-pulse rounded-xl bg-secondary/30" />;
  }
  if (variant === "thumb") {
    return (
      <button type="button" onClick={onClick} title="点击查看大图" className="shrink-0 cursor-zoom-in overflow-hidden rounded-xl border border-border">
        <img src={src} alt="证据缩略图" className="h-16 w-16 object-cover transition-transform hover:scale-110" />
      </button>
    );
  }
  if (variant === "image") {
    return <img src={src} alt="证据大图" className="max-h-[85vh] max-w-[90vw] rounded-2xl object-contain shadow-2xl" onClick={(e) => e.stopPropagation()} />;
  }
  if (variant === "video") {
    return <video key={src} src={src} controls preload="metadata" className={className || "mt-2 max-h-64 w-full rounded-xl border border-border bg-black/5"} />;
  }
  return <audio key={src} src={src} controls preload="metadata" className={className || "mt-2 w-full"} />;
}

/* ---------------- Mock 数据（基于真实 AI 识别结果 + 补足） ---------------- */
type Kind = "image_object" | "image_text" | "video" | "audio";
export type Useful = true | false | null;

export interface EvidenceItem {
  id: string;
  type: Kind;
  name: string;
  summary: string;
  useful: Useful;
  evidence_level: "A" | "B" | "C";
  time_range?: string; // 视频/音频
  key_events?: Array<{ time?: string; event?: string; evidence_value?: string; frame_path?: string }>;
  detected_objects?: string[]; // 视频
  transcript?: string; // 音频
  confirmed?: boolean | null; // null=未确认
  // 图片附加
  key_facts?: string[];
  /** 原始文件访问 URL（图片缩略图/大图、视频/音频播放用） */
  file_url?: string;
  /** 详细描述（图片/视频多模态长描述，区别于一句话 summary） */
  visual_description?: string;
}

const MOCK: EvidenceItem[] = [
  // —— 图片：物体图片 ——
  {
    id: "e1", type: "image_object", name: "现场车辆碰撞照片.jpg",
    summary: "画面中一辆白色轿车与黑色 SUV 正面相撞，引擎盖变形隆起，前保险杠脱落散落在地。事故现场为城市十字路口，可见路面刹车痕。",
    useful: true, evidence_level: "A",
    key_facts: ["车辆正面碰撞", "引擎盖变形", "刹车痕可见"],
  },
  {
    id: "e2", type: "image_object", name: "伤情照片_手腕.png",
    summary: "左手腕可见长约 5cm 横向伤口，周围皮肤红肿，已用纱布包扎。",
    useful: true, evidence_level: "B",
    key_facts: ["伤口长约 5cm", "横向伤口"],
  },
  // —— 图片：文字类 ——
  {
    id: "e3", type: "image_text", name: "借条.png",
    summary: "借款人李××向出借人周××借款人民币 10 万元，年利率 12%，期限 2025-06-01 至 2026-05-31。文末载明'逾期承担诉讼费、律师费'。",
    useful: false, evidence_level: "A",
    key_facts: ["金额 10 万", "年利率 12%", "逾期违约条款"],
  },
  {
    id: "e4", type: "image_text", name: "微信聊天记录.png",
    summary: "聊天记录显示被告于 2026-03-15 承诺 4 月底还款，并多次以'手头紧'拖延。",
    useful: true, evidence_level: "B",
    key_facts: ["被告承诺还款", "多次拖延"],
  },
  {
    id: "e5", type: "image_object", name: "事故认定书扫描件.png",
    summary: "对方车辆负事故的次要责任，本方车辆负主要责任（不利于我方）。",
    useful: false, evidence_level: "B",
    key_facts: ["对方次要责任", "本方主要责任"],
  },
  // —— 视频 ——
  {
    id: "v1", type: "video", name: "交通事故现场.mp4",
    summary: "现场监控：白色轿车闯红灯撞上正常行驶的黑色 SUV，撞击后两车滑行约 5 米。画面中可见车牌号。",
    useful: true, evidence_level: "A",
    time_range: "00:00:08 - 00:00:23",
    detected_objects: ["vehicle", "license_plate", "traffic_light"],
  },
  {
    id: "v2", type: "video", name: "家暴手机录屏.mp4",
    summary: "手机录屏显示争吵过程，男方多次推搡女方，女方哭泣。",
    useful: true, evidence_level: "B",
    time_range: "00:01:12 - 00:02:48",
    detected_objects: ["person", "phone"],
  },
  // —— 音频 ——
  {
    id: "a1", type: "audio", name: "威胁通话录音.mp3",
    summary: "通话中男方以'让你好看'威胁女方，并制止女方过问财务。",
    useful: true, evidence_level: "B",
    time_range: "00:00:00 - 00:03:42",
    transcript: "（片段）…你再翻我手机试试？我让你好看！…这个月房贷我说了算，你别问…",
  },
  {
    id: "a2", type: "audio", name: "催款电话.mp3",
    summary: "出借人三次电话催款，借款人承认借款但以各种理由推脱。",
    useful: true, evidence_level: "A",
    time_range: "00:00:00 - 00:08:15",
    transcript: "（片段）…周总，10 万的事这个月底一定给您…现在确实手头紧…",
  },
];

const TABS: { key: Kind | "all"; label: string; icon: any }[] = []; // 不再使用（旧按类别 tab 改为按有利不利主分组 + 类别小节）

const USEFUL_FILTERS = [
  { key: "all", label: "全部", icon: FileText },
  { key: "true", label: "有利", icon: ThumbsUp },
  { key: "false", label: "不利", icon: ThumbsDown },
] as const;

/* ---------------- 组件 ---------------- */
export function LitigationConfirmPreview({
  initialItems,
  onConfirmItem,
  onSetUsefulItem,
  onConfirmAll,
  showHero = true,
  readOnly = false,
}: {
  /** 不传则用内置 mock；传则使用真实数据（如从后端 confirmation_blocks 适配而来） */
  initialItems?: EvidenceItem[];
  /** 单条确认回调（不传则组件内部仅本地切换） */
  onConfirmItem?: (id: string, status: boolean) => void | Promise<void>;
  /** 切换有利/不利回调（不传则组件内部仅本地切换） */
  onSetUsefulItem?: (id: string, useful: Useful) => void;
  /** 一键确认当前视图回调；不传则用本地 setItems */
  onConfirmAll?: (ids: string[]) => void | Promise<void>;
  /** 是否显示 Hero 标题块（独立预览页显示，业务页可隐藏避免重复） */
  showHero?: boolean;
  /** 只读模式（true 时隐藏所有确认/编辑按钮，仅展示证据，适合证据管理页等"查看"场景） */
  readOnly?: boolean;
} = {}) {
  const [folder, setFolder] = useState<"image" | "video" | "audio">("image");
  // 图片有两层：sub（物体图片/文字类） × useful（有利/不利）。视频/音频只有 useful 一层。
  const [sub, setSub] = useState<"object" | "text">("object");
  const [useful, setUseful] = useState<"all" | "true" | "false">("all");
  const [items, setItems] = useState<EvidenceItem[]>(initialItems || MOCK);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [previewImage, setPreviewImage] = useState<string | null>(null);

  // 当外部传入新数据（如拉取到真实确认块）时同步本地 items
  useEffect(() => {
    if (initialItems) setItems(initialItems);
  }, [initialItems]);

  // 当前文件夹无数据但其他类型有数据时，自动切到第一个有数据的类型（避免"空状态"误导）
  useEffect(() => {
    const img = items.some((i) => i.type === "image_object" || i.type === "image_text");
    const vid = items.some((i) => i.type === "video");
    const aud = items.some((i) => i.type === "audio");
    const has = { image: img, video: vid, audio: aud };
    if (!has[folder] && items.length > 0) {
      const next = (["image", "video", "audio"] as const).find((k) => has[k]);
      if (next && next !== folder) setFolder(next);
    }
  }, [items, folder]);

  const imageItems = items.filter((i) => i.type === "image_object" || i.type === "image_text");
  const videoItems = items.filter((i) => i.type === "video");
  const audioItems = items.filter((i) => i.type === "audio");

  // 当前文件夹 → 当前视图（图片经过子分类 + 有用性两道过滤；视频/音频只过滤有用性）
  const current = (() => {
    const pool = folder === "image" ? imageItems : folder === "video" ? videoItems : audioItems;
    const filtered = useful === "all" ? pool : pool.filter((i) => String(i.useful) === useful);
    if (folder === "image") {
      return filtered.filter((i) => (sub === "object" ? i.type === "image_object" : i.type === "image_text"));
    }
    return filtered;
  })();
  // 当前文件夹"另一有用性"的备用数量（用于 tab 标签计数）
  const oppositeUsefulCount = (() => {
    if (useful === "all") return 0;
    const pool = folder === "image" ? imageItems : folder === "video" ? videoItems : audioItems;
    const subFiltered = folder === "image" ? pool.filter((i) => (sub === "object" ? i.type === "image_object" : i.type === "image_text")) : pool;
    const targetUseful = useful === "true" ? false : true;
    return subFiltered.filter((i) => Boolean(i.useful) === targetUseful).length;
  })();
  const sameUsefulCount = current.length;
  const allUsefulCount = (() => {
    const pool = folder === "image" ? imageItems : folder === "video" ? videoItems : audioItems;
    return folder === "image" ? pool.filter((i) => (sub === "object" ? i.type === "image_object" : i.type === "image_text")).length : pool.length;
  })();

  const counts = {
    image: imageItems.length,
    video: videoItems.length,
    audio: audioItems.length,
    image_object: imageItems.filter((i) => i.type === "image_object").length,
    image_text: imageItems.filter((i) => i.type === "image_text").length,
    confirmed: items.filter((i) => i.confirmed === true).length,
  };

  // 确认单条：优先调外部，否则本地
  const confirm = (id: string, status: boolean) => {
    if (onConfirmItem) {
      void onConfirmItem(id, status);
    } else {
      setItems((prev) => prev.map((it) => (it.id === id ? { ...it, confirmed: status } : it)));
    }
  };
  // 切换有用性：优先调外部，否则本地
  const setUsefulFor = (id: string, usefulVal: Useful) => {
    if (onSetUsefulItem) {
      onSetUsefulItem(id, usefulVal);
    }
    // 始终本地更新（保证 tab 计数实时变化）
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, useful: usefulVal } : it)));
  };
  // 一键确认当前视图：优先调外部，否则本地
  const confirmAll = () => {
    const ids = current.map((i) => i.id);
    if (onConfirmAll) {
      void onConfirmAll(ids);
    }
    setItems((prev) => prev.map((it) => (ids.includes(it.id) ? { ...it, confirmed: true } : it)));
  };

  // 渲染：根据 folder 决定子结构
  const renderList = () => {
    if (current.length === 0) return null;
    if (folder === "image") {
      // 图片：单列表（因为 sub 已经过滤了物体/文字）
      return (
        <div className="overflow-hidden rounded-[1.5rem] border border-border bg-card/90 shadow-sm">
          <div className="flex items-center gap-3 border-b border-border px-6 py-4">
            {sub === "object" ? <Box className="h-4 w-4 text-primary" /> : <ScanText className="h-4 w-4 text-primary" />}
            <div className="flex-1">
              <div className="text-sm font-black text-foreground">
                图片 · {sub === "object" ? "物体图片" : "文字类"} · {useful === "true" ? "有利" : "不利"}证据
              </div>
              <div className="text-[11px] font-bold text-muted-foreground">
                {sub === "object" ? "现场照片、损伤照片等以画面主体为主的证据" : "聊天记录、票据、合同截图等以文字为主的证据"}
              </div>
            </div>
            <span className="rounded-full bg-secondary px-2.5 py-1 text-[10px] font-black text-muted-foreground">{current.length}</span>
          </div>
          <div className="divide-y divide-border">
            {current.map((it) => (
              <ImageRow key={it.id} item={it} expandedId={expandedId} setExpandedId={setExpandedId} onConfirm={confirm} onSetUseful={setUsefulFor} onPreview={setPreviewImage} />
            ))}
          </div>
        </div>
      );
    }
    return (
      <MediaSection
        title={folder === "video" ? "视频" : "音频"}
        subtitle={folder === "video" ? `关键时段、检测到的物体 · ${useful === "all" ? "全部" : useful === "true" ? "有利" : "不利"}` : `关键时段、转写片段 · ${useful === "all" ? "全部" : useful === "true" ? "有利" : "不利"}`}
        icon={folder === "video" ? Film : Music}
        items={current}
        onConfirm={confirm}
        onSetUseful={setUsefulFor}
      />
    );
  };

  return (
    <div className="max-w-7xl space-y-6 pb-32 pt-8">
      {/* Hero（仅预览页显示，业务页隐藏避免重复） */}
      {showHero && (
        <PageHeader
          title="律师逐项确认"
          description="三个文件夹：图片 / 视频 / 音频。图片文件夹先选【物体图片 / 文字类】再选【有利 / 不利】；视频 / 音频直接选【有利 / 不利】。单条确认或一键确认当前视图。"
        />
      )}

      {/* 操作条 */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1.5rem] border border-border bg-card/90 px-6 py-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-2 text-xs font-black">
          <span className="rounded-full border border-border bg-secondary px-3 py-1 text-muted-foreground">当前视图 {current.length} 项</span>
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-emerald-700">已确认 {counts.confirmed}</span>
        </div>
        {!readOnly && (
          <button
            onClick={confirmAll}
            className="inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-[11px] font-black text-primary-foreground shadow-sm transition-opacity hover:opacity-90"
          >
            <CheckCheck className="h-3.5 w-3.5" /> 一键确认当前视图
          </button>
        )}
      </div>

      {/* 三层步骤式切换（明确层级关系） */}
      <div className="space-y-3">
        {/* 顶层操作条（当前视图数量 + 一键确认） */}
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-secondary/30 px-3 py-2">
          <span className="text-[10px] font-black tracking-widest text-muted-foreground">
            当前视图 {counts.byUseful} 项
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-card px-2.5 py-0.5 text-[10px] font-black text-muted-foreground">
              已确认 {counts.confirmed}
            </span>
          </div>
        </div>

        {/* 三层切换：每层独立、有序号、有层级标识 */}
        <div className="space-y-2 rounded-2xl border border-border bg-card/90 p-4 shadow-sm">
          <FilterLayer
            num="1"
            label="文件夹"
            hint="先选证据类型"
            value={folder}
            options={([["image", "图片", ImageIcon, counts.image], ["video", "视频", Film, counts.video], ["audio", "音频", Music, counts.audio]] as const)}
            onChange={setFolder}
          />
          {folder === "image" && (
            <FilterLayer
              num="2"
              label="子类"
              hint="图片下分物体/文字"
              value={sub}
              options={([["object", "物体图片", Box, counts.image_object], ["text", "文字类", ScanText, counts.image_text]] as const)}
              onChange={setSub}
            />
          )}
          <FilterLayer
            num="3"
            label="有用性"
            hint="按对己方影响筛选"
            value={useful}
            tone="useful"
            options={([["all", "全部", ListFilter, allUsefulCount], ["true", "有利", ThumbsUp, sameUsefulCount], ["false", "不利", ThumbsDown, oppositeUsefulCount]] as const)}
            onChange={setUseful}
          />
        </div>
      </div>

      {/* 当前视图证据列表 */}
      {renderList()}

      {/* 空状态 */}
      {current.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-[1.5rem] border border-dashed border-border bg-card/60 px-8 py-16 text-center">
          <FileText className="h-8 w-8 text-muted-foreground/30" />
          <div className="mt-3 text-sm font-black text-foreground">当前筛选下没有证据</div>
          <div className="mt-1 text-xs font-bold text-muted-foreground">切换文件夹 / 子类 / 有用性 试试其他组合</div>
        </div>
      )}

      {/* 图片放大预览 */}
      {previewImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-6 backdrop-blur-sm"
          onClick={() => setPreviewImage(null)}
        >
          <button
            type="button"
            onClick={() => setPreviewImage(null)}
            className="absolute right-5 top-5 inline-flex h-9 w-9 items-center justify-center rounded-full bg-white/90 text-slate-700 shadow transition-colors hover:bg-white"
          >
            <X className="h-4 w-4" />
          </button>
          <MediaPlayer url={previewImage} variant="image" />
        </div>
      )}
    </div>
  );
}

/* ---------------- 图片分小节组件 ---------------- */
function ImageSection({
  title, subtitle, icon: Icon, items, expandedId, setExpandedId, onConfirm, onSetUseful, readOnly = false,
}: {
  title: string; subtitle: string; icon: any; items: EvidenceItem[];
  expandedId: string | null; setExpandedId: (v: string | null) => void;
  onConfirm: (id: string, status: boolean) => void;
  onSetUseful: (id: string, u: Useful) => void;
  readOnly?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(false);
  if (items.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-[1.5rem] border border-border bg-card/90 shadow-sm">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex w-full items-center gap-3 border-b border-border px-6 py-4 text-left transition-colors hover:bg-accent/40"
      >
        {collapsed ? <ChevronRight className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        <Icon className="h-4 w-4 text-primary" />
        <div className="flex-1">
          <div className="text-sm font-black text-foreground">{title}</div>
          <div className="text-[11px] font-bold text-muted-foreground">{subtitle}</div>
        </div>
        <span className="rounded-full bg-secondary px-2.5 py-1 text-[10px] font-black text-muted-foreground">{items.length}</span>
      </button>
      {!collapsed && (
        <div className="divide-y divide-border">
          {items.map((it) => (
            <ImageRow key={it.id} item={it} expandedId={expandedId} setExpandedId={setExpandedId} onConfirm={onConfirm} onSetUseful={onSetUseful} readOnly={readOnly} />
          ))}
        </div>
      )}
    </div>
  );
}

function ImageRow({
  item, expandedId, setExpandedId, onConfirm, onSetUseful, readOnly = false, onPreview,
}: {
  item: EvidenceItem; expandedId: string | null; setExpandedId: (v: string | null) => void;
  onConfirm: (id: string, status: boolean) => void;
  onSetUseful: (id: string, u: Useful) => void;
  readOnly?: boolean;
  onPreview?: (url: string) => void;
}) {
  const expanded = expandedId === item.id;
  return (
    <div className={cn("p-5", expanded && "bg-accent/30")}>
      <div className="flex flex-wrap items-center gap-4">
        {item.file_url ? (
          <MediaPlayer url={item.file_url} variant="thumb" onClick={() => onPreview?.(item.file_url!)} />
        ) : (
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl border border-border bg-gradient-to-br from-slate-100 to-slate-200 text-muted-foreground">
            <ImageIcon className="h-7 w-7" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-black text-foreground">{item.name}</span>
            <EvidenceLevelBadge level={item.evidence_level} />
            <UsefulBadge useful={item.useful} />
            {item.confirmed === true && (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[9px] font-black text-emerald-700">
                <CheckCircle2 className="h-3 w-3" /> 已确认
              </span>
            )}
            {item.confirmed === false && (
              <span className="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[9px] font-black text-rose-700">
                <XCircle className="h-3 w-3" /> 已排除
              </span>
            )}
          </div>
          <p className="mt-1.5 line-clamp-2 text-xs font-medium leading-6 text-foreground/80">{cleanSummary(item.summary, 110)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* 有利/不利切换（只读模式只展示当前状态，不可切换） */}
          {readOnly ? (
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-[11px] font-black",
                item.useful === true
                  ? "bg-emerald-500 text-white"
                  : item.useful === false
                  ? "bg-rose-500 text-white"
                  : "bg-secondary text-muted-foreground",
              )}
            >
              {item.useful === true ? <ThumbsUp className="h-3 w-3" /> : <ThumbsDown className="h-3 w-3" />}
            </span>
          ) : (
            <div className="flex overflow-hidden rounded-full border border-border">
              <button
                onClick={() => onSetUseful(item.id, true)}
                className={cn(
                  "px-3 py-1.5 text-[11px] font-black transition-colors",
                  item.useful === true ? "bg-emerald-500 text-white" : "bg-card text-muted-foreground hover:bg-accent",
                )}
              >
                <ThumbsUp className="h-3 w-3" />
              </button>
              <button
                onClick={() => onSetUseful(item.id, false)}
                className={cn(
                  "px-3 py-1.5 text-[11px] font-black transition-colors",
                  item.useful === false ? "bg-rose-500 text-white" : "bg-card text-muted-foreground hover:bg-accent",
                )}
              >
                <ThumbsDown className="h-3 w-3" />
              </button>
            </div>
          )}
          {!readOnly && (
            <button
              onClick={() => onConfirm(item.id, true)}
              className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300 bg-emerald-50 px-4 py-1.5 text-[11px] font-black text-emerald-700 transition-colors hover:bg-emerald-100"
            >
              <CheckCircle2 className="h-3.5 w-3.5" /> 单独确认
            </button>
          )}
          <button
            onClick={() => setExpandedId(expanded ? null : item.id)}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-[11px] font-black text-muted-foreground transition-colors hover:bg-accent"
          >
            {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            展开
          </button>
        </div>
      </div>
      {expanded && (
        <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} className="mt-4 grid gap-3 rounded-2xl border border-border bg-card p-4 sm:grid-cols-3">
          <div className="sm:col-span-3 space-y-2">
            <DetailRow label="重点摘要" text={cleanSummary(item.summary)} />
            {item.key_facts && item.key_facts.length > 0 && (
              <DetailRow label="关键事实" items={item.key_facts} />
            )}
            <details className="rounded-lg border border-border bg-secondary/20 px-3 py-2">
              <summary className="cursor-pointer text-[10px] font-black uppercase tracking-widest text-muted-foreground">查看完整摘要（{((item.visual_description && cleanSummary(item.visual_description, 9999)) || (typeof item.key_facts === 'object' && item.key_facts?.length) || 0) + (item.summary?.length || 0)} 字）</summary>
              <div className="mt-2 space-y-2 text-xs font-medium leading-6 text-foreground/80">
                {item.visual_description && (
                  <p className="whitespace-pre-wrap">{cleanSummary(item.visual_description, 9999)}</p>
                )}
                {item.key_facts && Array.isArray(item.key_facts) && item.key_facts.length > 0 && (
                  <ul className="ml-4 list-disc space-y-0.5">
                    {item.key_facts.map((f, i) => <li key={i}>{typeof f === 'string' ? f : JSON.stringify(f)}</li>)}
                  </ul>
                )}
                {item.key_info && typeof item.key_info === 'object' && !item.key_facts?.length && (
                  <div className="space-y-1">
                    {Object.entries(item.key_info).map(([k, v]) => (
                      typeof v === 'string' && v ? <p key={k}><span className="font-black text-muted-foreground">{k}：</span>{cleanSummary(v, 9999)}</p> : null
                    ))}
                  </div>
                )}
                {item.proof_purpose && <p><span className="font-black text-muted-foreground">证明目的：</span>{item.proof_purpose}</p>}
              </div>
            </details>
            <div className="grid grid-cols-2 gap-2">
              <DetailRow label="证明力等级" text={levelLabel(item.evidence_level)} />
              <DetailRow label="对己方" text={item.useful === true ? "有利" : item.useful === false ? "不利" : "待定"} />
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
}

/* ---------------- 视频/音频分小节组件 ---------------- */
function MediaSection({
  title, subtitle, icon: Icon, items, onConfirm, onSetUseful, readOnly = false,
}: {
  title: string; subtitle: string; icon: any; items: EvidenceItem[];
  onConfirm: (id: string, status: boolean) => void;
  onSetUseful: (id: string, u: Useful) => void;
  readOnly?: boolean;
}) {
  if (items.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-[1.5rem] border border-border bg-card/90 shadow-sm">
      <div className="flex items-center gap-3 border-b border-border px-6 py-4">
        <Icon className="h-4 w-4 text-primary" />
        <div className="flex-1">
          <div className="text-sm font-black text-foreground">{title}</div>
          <div className="text-[11px] font-bold text-muted-foreground">{subtitle}</div>
        </div>
        <span className="rounded-full bg-secondary px-2.5 py-1 text-[10px] font-black text-muted-foreground">{items.length}</span>
      </div>
      <div className="divide-y divide-border">
        {items.map((it) => (
          <MediaRow key={it.id} item={it} onConfirm={onConfirm} onSetUseful={onSetUseful} readOnly={readOnly} />
        ))}
      </div>
    </div>
  );
}

function MediaRow({
  item, onConfirm, onSetUseful, readOnly = false,
}: {
  item: EvidenceItem; onConfirm: (id: string, status: boolean) => void;
  onSetUseful: (id: string, u: Useful) => void;
  readOnly?: boolean;
}) {
  const isVideo = item.type === "video";
  return (
    <div className="p-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className={cn(
          "flex h-16 w-20 shrink-0 items-center justify-center rounded-xl border text-muted-foreground",
          isVideo ? "border-violet-200 bg-violet-50" : "border-emerald-200 bg-emerald-50",
        )}>
          {isVideo ? <Film className="h-7 w-7 text-violet-600" /> : <Music className="h-7 w-7 text-emerald-600" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-black text-foreground">{item.name}</span>
            <EvidenceLevelBadge level={item.evidence_level} />
            <UsefulBadge useful={item.useful} />
            {item.confirmed === true && (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[9px] font-black text-emerald-700">
                <CheckCircle2 className="h-3 w-3" /> 已确认
              </span>
            )}
          </div>
          {item.file_url && (
            isVideo ? (
              <MediaPlayer url={item.file_url} variant="video" />
            ) : (
              <MediaPlayer url={item.file_url} variant="audio" />
            )
          )}
          <p className="mt-1.5 text-xs font-medium leading-6 text-foreground/80">{item.summary}</p>
          {item.transcript && (
            <details className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50/30 px-3 py-2">
              <summary className="cursor-pointer text-[11px] font-black text-emerald-700">查看转写全文（{item.transcript.length} 字）</summary>
              <p className="mt-2 whitespace-pre-wrap text-xs font-medium leading-6 text-foreground/80">{item.transcript}</p>
            </details>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] font-bold text-muted-foreground">
            {item.time_range && (
              <span className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary px-2.5 py-1">
                <Clock3 className="h-3 w-3" /> {item.time_range}
              </span>
            )}
            {item.key_events && item.key_events.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <Sparkles className="h-3 w-3 text-primary" />
                {item.key_events.map((event, index) => (
                  <span key={`${event.time || 'event'}-${index}`} className="rounded-full border border-primary/20 bg-primary/5 px-2 py-0.5 text-primary">
                    {event.time ? `${event.time} ` : ''}{event.event || '关键事件'}
                  </span>
                ))}
              </div>
            )}
            {isVideo && item.detected_objects && item.detected_objects.length > 0 && (
              <div className="flex items-center gap-1">
                <Sparkles className="h-3 w-3 text-primary" />
                {item.detected_objects.map((o) => (
                  <span key={o} className="rounded-full border border-primary/20 bg-primary/5 px-2 py-0.5 text-primary">
                    {o}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {readOnly ? (
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-[11px] font-black",
                item.useful === true
                  ? "bg-emerald-500 text-white"
                  : item.useful === false
                  ? "bg-rose-500 text-white"
                  : "bg-secondary text-muted-foreground",
              )}
            >
              {item.useful === true ? <ThumbsUp className="h-3 w-3" /> : <ThumbsDown className="h-3 w-3" />}
            </span>
          ) : (
            <>
              <div className="flex overflow-hidden rounded-full border border-border">
                <button
                  onClick={() => onSetUseful(item.id, true)}
                  className={cn(
                    "px-3 py-1.5 text-[11px] font-black transition-colors",
                    item.useful === true ? "bg-emerald-500 text-white" : "bg-card text-muted-foreground hover:bg-accent",
                  )}
                >
                  <ThumbsUp className="h-3 w-3" />
                </button>
                <button
                  onClick={() => onSetUseful(item.id, false)}
                  className={cn(
                    "px-3 py-1.5 text-[11px] font-black transition-colors",
                    item.useful === false ? "bg-rose-500 text-white" : "bg-card text-muted-foreground hover:bg-accent",
                  )}
                >
                  <ThumbsDown className="h-3 w-3" />
                </button>
              </div>
              <button
                onClick={() => onConfirm(item.id, true)}
                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300 bg-emerald-50 px-4 py-1.5 text-[11px] font-black text-emerald-700 transition-colors hover:bg-emerald-100"
              >
                <CheckCircle2 className="h-3.5 w-3.5" /> 单独确认
              </button>
            </>
          )}
        </div>
      </div>
      {item.transcript && (
        <div className="mt-3 rounded-2xl border border-border bg-secondary/30 px-4 py-3">
          <div className="mb-1.5 text-[10px] font-black tracking-widest text-muted-foreground">转写片段</div>
          <p className="text-xs font-medium leading-6 text-foreground/80">{item.transcript}</p>
        </div>
      )}
    </div>
  );
}

/* ---------------- 公共小组件 ---------------- */
function EvidenceLevelBadge({ level }: { level: "A" | "B" | "C" }) {
  const cls = level === "A" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : level === "B" ? "border-amber-200 bg-amber-50 text-amber-700" : "border-slate-200 bg-slate-100 text-slate-600";
  return <span className={cn("rounded-full border px-2 py-0.5 text-[9px] font-black", cls)}>证明力 {level}</span>;
}
function UsefulBadge({ useful }: { useful: Useful }) {
  if (useful === null || useful === undefined) return null;
  return useful ? (
    <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[9px] font-black text-emerald-700">有利</span>
  ) : (
    <span className="rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[9px] font-black text-rose-700">不利</span>
  );
}
function levelLabel(l: "A" | "B" | "C") { return l === "A" ? "A · 强" : l === "B" ? "B · 中" : "C · 弱"; }
function DetailRow({ label, text, items }: { label: string; text?: string; items?: string[] }) {
  return (
    <div>
      <div className="text-[10px] font-black tracking-widest text-muted-foreground">{label}</div>
      {text && <div className="mt-1 text-xs font-medium leading-6 text-foreground/80">{text}</div>}
      {items && items.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {items.map((i, idx) => (
            <span key={idx} className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-bold text-foreground">{i}</span>
          ))}
        </div>
      )}
    </div>
  );
}

/** 当前路径面包屑的分隔符 + 三种步骤 token（视觉层级分明） */
function Sep() {
  return <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />;
}
function FolderStep({ icon: Icon, active, label, count, onClick }: { icon: any; active: boolean; label: string; count: number; onClick: () => void }) {
  return (
    <button onClick={onClick} className={cn(
      "inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-black transition-all", active ? "text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-secondary/50 rounded-full",
    )}>
      <Icon className="h-4 w-4 text-primary" />
      <span>{label}</span>
      <span className="rounded-full bg-primary/15 px-1.5 py-0.5 text-[9px] font-black text-primary">{count}</span>
    </button>
  );
}
function SubStep({ icon: Icon, active, label, count, onClick }: { icon: any; active: boolean; label: string; count: number; onClick: () => void }) {
  return (
    <button onClick={onClick} className={cn(
      "inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-black transition-all", active ? "text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-secondary/50 rounded-full",
    )}>
      <Icon className="h-3.5 w-3.5 text-violet-600" />
      <span>{label}</span>
      <span className="rounded-full bg-violet-100 px-1.5 py-0.5 text-[9px] font-black text-violet-700">{count}</span>
    </button>
  );
}
function UsefulStep({ tone, label, count, onClick }: { tone: "good" | "bad"; active?: boolean; label: string; count: number; onClick: () => void }) {
  const cls = tone === "good" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-rose-200 bg-rose-50 text-rose-700";
  const Icon =
 tone === "good" ? ThumbsUp : ThumbsDown;
  return (
    <button onClick={onClick} className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-xs font-black transition-colors hover:opacity-80", cls)}> 
      <Icon className="h-3.5 w-3.5" />
      <span>{label}</span>
      <span className="rounded-full bg-white/40 px-1.5 py-0.5 text-[9px] font-black">{count}</span>
    </button>
  );
}

/** 三层切换：每层独立行，序号 + 标签 + 提示 + 选项按钮组（颜色与面包屑呼应） */
function FilterLayer<T extends string>({ num, label, hint, value, options, onChange, tone }: {
  num: string;
  label: string;
  hint?: string;
  value: T;
  options: ReadonlyArray<readonly [T, string, any, number]>;
  onChange: (v: T) => void;
  tone?: "useful" | undefined;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border/60 bg-background/40 px-3 py-2">
      <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-primary text-[10px] font-black text-primary-foreground">{num}</span>
      <span className="text-xs font-black text-foreground">{label}</span>
      {hint && <span className="text-[10px] font-bold text-muted-foreground">· {hint}</span>}
      <div className="ml-auto flex flex-wrap gap-1.5">
        {options.map(([k, optLabel, Icon, cnt]) => {
          const active = value === k;
          const isUseful = tone === "useful";
          return (
            <button
              key={k}
              onClick={() => onChange(k)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-black transition-all", active
                  ? isUseful && k === "true"
                    ? "border-emerald-200 bg-emerald-500 text-white shadow-sm"
                    : isUseful && k === "false"
                    ? "border-rose-200 bg-rose-500 text-white shadow-sm"
                    : "border-primary bg-primary text-primary-foreground shadow-sm"
                  : "border-border bg-card text-muted-foreground hover:bg-accent",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              <span>{optLabel}</span>
              <span className={cn("rounded-full px-1.5 py-0.5 text-[9px]", active ? "bg-white/25" : "bg-muted text-muted-foreground")}>{cnt}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
