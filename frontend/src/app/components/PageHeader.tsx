import { cn } from "../../lib/utils";

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
}

/**
 * 紧凑版页面标题：仅显示标题 + 一句话描述，不占用大块空间。
 * 替代之前带徽章 + 大标题 + 大描述的圆角卡片 Hero。
 */
export function PageHeader({ title, description, actions, className }: PageHeaderProps) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4", className)}>
      <div className="space-y-1">
        <h1 className="text-2xl font-black tracking-tight text-foreground">{title}</h1>
        {description && (
          <p className="max-w-2xl text-xs font-bold leading-5 text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
