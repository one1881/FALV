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
  className,
}: {
  title?: string;
  current?: number;
  total?: number;
  phases?: string[];
  phaseIndex?: number;
  /** 任务开始时间（Date.now()），用于计算已用时长与剩余预估 */
  startedAt?: number;
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

  // 阶段模式：外部传入 phaseIndex 则用之；否则按已用时长自动推进（每阶段约 60 秒）
  const autoPhaseIndex = phases && phases.length > 0 && typeof phaseIndex !== "number" ? Math.min(phases.length - 1, Math.floor(elapsed / 60)) : undefined;
  const activePhaseIndex = typeof phaseIndex === "number" ? phaseIndex : (autoPhaseIndex ?? 0);
  const percent = isMulti
    ? Math.min(100, Math.round((current! / total!) * 100))
    : phases && phases.length > 0
      ? Math.min(100, Math.round(((activePhaseIndex + 1) / phases.length) * 100))
      : 0;

  // 剩余预估：多文件按平均耗时外推；阶段模式按总时长推算
  let eta = "";
  if (isMulti && current! > 0) {
    const perItem = elapsed / current!;
    const remain = Math.ceil(perItem * (total! - current!));
    eta = formatSec(remain);
  } else if (phases && phases.length > 0) {
    const totalEst = phases.length * 60; // 每阶段约 1 分钟
    const remain = Math.max(10, totalEst - elapsed);
    eta = formatSec(remain);
  } else {
    eta = formatSec(Math.max(30, 90 - elapsed));
  }

  const phaseLabel = phases && phases.length > 0 ? phases[activePhaseIndex] : "";

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
          <span className="rounded-full bg-secondary px-2.5 py-0.5">
            {eta ? `预计剩余 ${eta}` : "正在计算…"}
          </span>
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
