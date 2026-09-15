import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

/**
 * 通用任务进度条：用于所有"转圈/等待"场景，显示阶段、已完成/总数、预估剩余时间。
 *
 * 两种模式：
 *  - 多文件模式（current/total）：逐文件处理，显示 已完成 i/N + 剩余预估
 *  - 阶段模式（phases/phaseIndex）：单任务多阶段，显示 当前阶段名 + 总阶段进度
 */
export function TaskProgress({
  title,
  current,
  total,
  phases,
  phaseIndex,
  startedAt,
  estimatedTotalSeconds,
  className,
}: {
  title?: string;
  current?: number;
  total?: number;
  phases?: string[];
  phaseIndex?: number;
  /** 任务开始时间（Date.now()），用于计算已用时长与剩余预估 */
  startedAt?: number;
  /**
   * 阶段模式的预估总时长（秒），缺省按每阶段 60 秒推算。
   *
   * 2026-09-11 修复：此前阶段模式写死「每阶段 60 秒」，4 阶段 = 240 秒封顶。
   * 审核实测 205~410 秒，导致进度条在 240 秒就走满 100%，ETA 被 Math.max 钳在
   * 「10 秒」后继续挂两三分钟——看起来像卡死。现改为对外可传真实预估，
   * 且进度封顶 95%（任务未结束就不显示 100%），超预估时如实改文案。
   */
  estimatedTotalSeconds?: number;
  className?: string;
}) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const start = startedAt ?? now;
  const elapsed = Math.max(0, Math.floor((now - start) / 1000));

  // 多文件模式
  const isMulti = typeof current === "number" && typeof total === "number" && total > 0;

  const hasPhases = !!(phases && phases.length > 0);
  // 阶段模式预估总时长：调用方可传，缺省每阶段 60 秒
  const estimatedTotal =
    estimatedTotalSeconds && estimatedTotalSeconds > 0
      ? estimatedTotalSeconds
      : hasPhases
        ? phases!.length * 60
        : 90;
  const secondsPerPhase = hasPhases ? Math.max(15, Math.round(estimatedTotal / phases!.length)) : 60;

  // 阶段模式：外部传入 phaseIndex 则用之；否则按已用时长自动推进
  const autoPhaseIndex =
    hasPhases && typeof phaseIndex !== "number"
      ? Math.min(phases!.length - 1, Math.floor(elapsed / secondsPerPhase))
      : undefined;
  const activePhaseIndex = typeof phaseIndex === "number" ? phaseIndex : (autoPhaseIndex ?? 0);
  const percent = isMulti
    ? Math.min(100, Math.round((current! / total!) * 100))
    : hasPhases
      ? // 封顶 95%：任务还在跑就不能显示「已完成」
        Math.min(95, Math.round(((activePhaseIndex + 1) / phases!.length) * 100))
      : 0;

  // 剩余预估
  let etaText = "";
  const overdue = elapsed > estimatedTotal;
  if (isMulti && current! > 0) {
    const perItem = elapsed / current!;
    etaText = `预计剩余 ${formatSec(Math.ceil(perItem * (total! - current!)))}`;
  } else if (hasPhases) {
    etaText = overdue
      ? `仍在处理（已用 ${formatSec(elapsed)}）`
      : `预计剩余 ${formatSec(Math.max(5, estimatedTotal - elapsed))}`;
  } else {
    etaText = `预计剩余 ${formatSec(Math.max(30, 90 - elapsed))}`;
  }

  const phaseLabel = hasPhases ? phases![activePhaseIndex] : "";

  return (
    <div className={cn("rounded-2xl border border-border bg-card/90 px-5 py-4 shadow-sm", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-black text-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          <span>{title || (isMulti ? "正在处理文件…" : "AI 处理中…")}</span>
          {phaseLabel && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-black text-primary">{phaseLabel}</span>}
        </div>
        <div className="flex items-center gap-2 text-[11px] font-black text-muted-foreground">
          {isMulti && <span>已完成 {current} / {total}</span>}
          <span className="rounded-full bg-secondary px-2.5 py-0.5">{etaText || "正在计算…"}</span>
        </div>
      </div>

      {/* 进度条 */}
      <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-500 to-primary transition-all duration-700"
          style={{ width: `${Math.max(4, percent)}%` }}
        />
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] font-bold text-muted-foreground">
        <span>进度 {percent}%</span>
        <span>已用时 {formatSec(elapsed)}</span>
      </div>
    </div>
  );
}

function formatSec(sec: number) {
  if (sec < 60) return `${sec} 秒`;
  return `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`;
}
