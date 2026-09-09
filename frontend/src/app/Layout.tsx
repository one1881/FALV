import { Outlet, useLocation } from "react-router";
import { Sidebar } from "./components/Sidebar";
import { motion } from "motion/react";
import { useState } from "react";
import { Menu } from "lucide-react";

const ROUTES_COLORS: Record<string, string> = {
  "/": "rgba(248, 250, 252, 0.94)",
  "/drafting/contracts": "rgba(241, 245, 249, 0.96)",
  "/approvals": "rgba(239, 246, 255, 0.9)",
  "/approvals/my": "rgba(239, 246, 255, 0.9)",
};

export default function Layout() {
  const location = useLocation();
  const activeColorOverlay = ROUTES_COLORS[location.pathname] || "rgba(255,255,255,0.82)";
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen w-full font-['PingFang_SC','-apple-system','BlinkMacSystemFont','Microsoft_YaHei',sans-serif] text-foreground overflow-hidden bg-background selection:bg-primary selection:text-primary-foreground relative">
      <motion.div
        className="absolute inset-0 z-0 pointer-events-none transition-colors duration-1000 ease-in-out"
        style={{ backgroundColor: activeColorOverlay }}
      />

      <aside className="relative z-30 hidden md:flex md:w-[320px] md:flex-shrink-0 md:border-r md:border-border md:bg-card/95 md:backdrop-blur-2xl md:shadow-[18px_0_40px_rgba(15,23,42,0.08)]">
        <Sidebar />
      </aside>

      <div
        className={`fixed inset-y-0 left-0 z-50 w-[320px] transform ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'} transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] bg-card/95 backdrop-blur-2xl border-r border-border shadow-[18px_0_40px_rgba(15,23,42,0.08)] flex md:hidden`}
      >
        <Sidebar />
      </div>

      {isSidebarOpen && (
        <button
          type="button"
          aria-label="关闭菜单"
          onClick={() => setIsSidebarOpen(false)}
          className="fixed inset-0 z-40 bg-slate-950/20 backdrop-blur-[1px] md:hidden"
        />
      )}

      <main className="relative z-10 flex-1 h-full overflow-y-auto overflow-x-hidden pt-16 sm:pt-24 pb-24 tracking-wide">
        <button
          onClick={() => setIsSidebarOpen(true)}
          className="absolute top-8 left-8 flex items-center gap-3 opacity-70 hover:opacity-100 transition-opacity z-30 group cursor-pointer md:hidden"
        >
          <Menu className="w-4 h-4 text-foreground group-hover:scale-110 transition-transform" />
          <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground border-b border-transparent group-hover:border-primary/50 transition-colors">
            调用矩阵菜单
          </div>
        </button>

        <div className="max-w-7xl mx-auto px-8 sm:px-16 min-h-full mt-8">
          {/* 仅做「进入淡入」，不保留退场动画，避免 mode="wait" + opacity 退场
              被中断时新页面卡在 opacity:0 而整页不可见。 */}
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
          >
            <Outlet />
          </motion.div>
        </div>
      </main>

      <div className="fixed left-4 top-1/2 -translate-y-1/2 z-0 opacity-20 flex flex-col gap-3 pointer-events-none text-primary mix-blend-normal md:hidden">
        <motion.div
          animate={{ height: ["20px", "40px", "20px"] }}
          transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
          className="w-[1.5px] bg-current mx-auto"
        />
        <motion.div
          animate={{ scale: [1, 1.5, 1], opacity: [0.35, 0.8, 0.35] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
          className="w-1.5 h-1.5 rounded-full bg-current mx-auto"
        />
        <motion.div
          animate={{ height: ["20px", "40px", "20px"] }}
          transition={{ duration: 3, repeat: Infinity, ease: "easeInOut", delay: 0.5 }}
          className="w-[1.5px] bg-current mx-auto"
        />
      </div>
    </div>
  );
}
