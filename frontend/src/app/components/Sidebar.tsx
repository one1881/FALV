import { Link, useLocation, useNavigate } from "react-router";
import { cn } from "../../lib/utils";
import {
  Scale,
  Fingerprint,
  FileText,
  GitPullRequest,
  ShieldCheck,
  
  
  
} from "lucide-react";
import { motion } from "motion/react";

import { getCurrentUser, signOut } from "../auth";

const NAV_GROUPS = [
  {
    title: "起草",
    items: [
      { icon: FileText, label: "合同文书起草", path: "/drafting" },
      { icon: FileText, label: "合同管理", path: "/drafting/contracts" },
    ],
  },
  {
    title: "审核",
    items: [
      { icon: GitPullRequest, label: "合同审核", path: "/approvals" },
    ],
  },
  {
    title: "证据处理",
    items: [
      { icon: Scale, label: "案件受理", path: "/litigation/new" },
      { icon: ShieldCheck, label: "证据管理", path: "/litigation/evidence" },
    ],
  },
];

export function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentUser = getCurrentUser();
  const isReviewer = currentUser?.role === "reviewer";
  // 按角色显示"审核"分组入口：律师→合同审核（提交方），审核员→审核工作台（审批方）
  const navGroups = NAV_GROUPS.map((g) => {
    if (g.title === "审核") {
      return {
        ...g,
        items: isReviewer
          ? [{ icon: ShieldCheck, label: "审核工作台", path: "/review-management" }]
          : [{ icon: GitPullRequest, label: "合同审核", path: "/approvals" }],
      };
    }
    return g;
  });

  const handleSignOut = () => {
    signOut();
    navigate("/login", { replace: true });
  };

  return (
    <div className="w-full h-full flex flex-col py-10 px-8 overflow-y-auto overflow-x-hidden relative bg-gradient-to-b from-background via-card to-muted/40 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:'none'] [scrollbar-width:'none']">
      <motion.div
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.8, delay: 0.1 }}
        className="mb-10 flex flex-col gap-2 relative z-10 border-b border-border pb-8"
      >
        <div className="flex items-center gap-4">
          <motion.div
            whileHover={{ rotate: 90 }}
            transition={{ type: "spring", stiffness: 200, damping: 10 }}
            className="w-12 h-12 flex-shrink-0 rounded-2xl border border-primary/20 flex flex-col justify-center items-center bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors duration-300"
          >
            <Scale className="w-5 h-5" />
          </motion.div>
          <div>
            <h1 className="text-xl font-black text-foreground tracking-[0.2em] leading-none uppercase">{"一律通"}</h1>
            <p className="text-[9px] tracking-[0.3em] font-bold text-muted-foreground uppercase mt-2">YI LV TONG · LEGAL INTELLIGENCE</p>
          </div>
        </div>
      </motion.div>

      <nav className="flex-1 flex flex-col gap-8 relative z-10">
        {(() => {
          const activePath =
            navGroups
              .flatMap((g) => g.items)
              .filter(
                (i) =>
                  location.pathname === i.path ||
                  (i.path !== "/" && location.pathname.startsWith(i.path + "/"))
              )
              .sort((a, b) => b.path.length - a.path.length)[0]?.path ?? null;
          return navGroups.map((group, groupIndex) => (
            <div key={group.title} className="flex flex-col gap-2">
              <motion.div
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 + groupIndex * 0.1 }}
                className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em] px-2 mb-2 flex items-center gap-4"
              >
                {group.title}
                <div className="flex-1 h-px bg-border" />
              </motion.div>

              {group.items.map((item, index) => {
                const isActive = activePath === item.path;
                return (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.5, delay: 0.2 + groupIndex * 0.1 + index * 0.05 }}
                >
                  <Link
                    to={item.path}
                    className={cn(
                      "group flex items-center gap-4 px-4 py-3 rounded-2xl transition-all duration-300 relative overflow-hidden border",
                      isActive
                        ? "bg-primary text-primary-foreground border-primary shadow-sm"
                        : "bg-card/70 text-muted-foreground border-border hover:bg-accent hover:text-accent-foreground hover:border-primary/20"
                    )}
                  >
                    {isActive && <motion.div layoutId="activeNav" className="absolute left-0 top-2 bottom-2 w-1 rounded-full bg-white/90" />}
                    <item.icon
                      strokeWidth={isActive ? 2 : 1.5}
                      className={cn(
                        "w-4 h-4 relative z-10 transition-transform duration-300 group-hover:scale-110",
                        isActive ? "text-primary-foreground" : "text-muted-foreground group-hover:text-accent-foreground"
                      )}
                    />
                    <span className={cn("relative z-10 font-bold tracking-widest text-xs transition-colors", isActive ? "text-primary-foreground" : "group-hover:text-accent-foreground")}>{item.label}</span>
                  </Link>
                </motion.div>
              );
            })}
          </div>
        ));
      })()}
      </nav>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.5 }}
        className="mt-8 pt-6 border-t border-border relative z-10"
      >
        <button
          type="button"
          onClick={handleSignOut}
          className="flex w-full items-center gap-4 rounded-2xl border border-border p-3 text-left transition-colors duration-300 hover:border-primary/20 hover:bg-accent group bg-card/80"
        >
          <div className="w-10 h-10 rounded-xl border border-primary/20 bg-accent/60 flex-shrink-0 flex items-center justify-center group-hover:bg-primary group-hover:border-primary transition-colors duration-300">
            <Fingerprint className="w-5 h-5 text-primary group-hover:text-primary-foreground transition-colors duration-300" />
          </div>
          <div>
            <div className="text-sm font-black text-foreground tracking-widest group-hover:text-accent-foreground transition-colors duration-300">{currentUser?.full_name || "业务用户"}</div>
            <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-muted-foreground mt-1 group-hover:text-accent-foreground/70 transition-colors duration-300">
              {currentUser?.role === "reviewer" ? "审核员 · 在线 · 退出" : "起草用户 · 在线 · 退出"}
            </div>
          </div>
        </button>
      </motion.div>
    </div>
  );
}
