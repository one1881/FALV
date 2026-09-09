import { Link } from "react-router";
import { FileArchive } from "lucide-react";

/**
 * 空态：还没有案件时给用户一个引导入口
 * （原 LitigationStageBar 组件已随阶段条下线移除，本文件只保留 EmptyCaseHint）
 */
export function EmptyCaseHint() {
  return (
    <div className="flex flex-col items-center justify-center rounded-[1.5rem] border border-dashed border-border bg-card/60 px-8 py-16 text-center">
      <FileArchive className="h-10 w-10 text-muted-foreground/50" />
      <div className="mt-4 text-sm font-black text-foreground">还没有可查看的案件</div>
      <div className="mt-2 max-w-sm text-xs font-bold leading-6 text-muted-foreground">
        请先在「案件受理」中创建受理、上传材料并完成归档，归档后的案件会出现在这里。
      </div>
      <Link
        to="/litigation/new"
        className="mt-6 rounded-full bg-primary px-5 py-2 text-xs font-black text-primary-foreground transition-opacity hover:opacity-90"
      >
        去案件受理
      </Link>
    </div>
  );
}
