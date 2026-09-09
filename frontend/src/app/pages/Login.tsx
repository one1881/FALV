import { useEffect, useRef, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowRight,
  Eye,
  EyeOff,
  Fingerprint,
  KeyRound,
  LockKeyhole,
  Scale,
  ShieldCheck,
} from "lucide-react";
import { isAuthenticated, signIn } from "../auth";

type FieldErrors = {
  account?: string;
  password?: string;
};

const BRAND = "律一通";
const SYSTEM_NAME = "一律通";

function getDestination(from: unknown) {
  if (typeof from === "string" && from.startsWith("/") && from !== "/login") {
    return from;
  }
  return "/";
}

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const reduceMotion = useReducedMotion();
  const accountRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    document.title = `${SYSTEM_NAME} · \u5b89\u5168\u767b\u5f55`;
    return () => {
      document.title = SYSTEM_NAME;
    };
  }, []);

  if (isAuthenticated()) {
    return <Navigate to="/" replace />;
  }

  const clearError = (field: keyof FieldErrors) => {
    if (errors[field]) {
      setErrors((current) => ({ ...current, [field]: undefined }));
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextErrors: FieldErrors = {};
    if (!account.trim()) nextErrors.account = "\u8bf7\u8f93\u5165\u8d26\u53f7";
    if (!password.trim()) nextErrors.password = "\u8bf7\u8f93\u5165\u5bc6\u7801";
    setErrors(nextErrors);

    if (Object.keys(nextErrors).length > 0) {
      if (nextErrors.account) accountRef.current?.focus();
      else passwordRef.current?.focus();
      return;
    }

    setIsLoading(true);
    try {
      await signIn(account.trim(), password);
      const from = (location.state as { from?: unknown } | null)?.from;
      navigate(getDestination(from), { replace: true });
    } catch (error: any) {
      setErrors({
        account: "\u767b\u5f55\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8d26\u53f7\u548c\u5bc6\u7801",
        password: error?.message || "\u767b\u5f55\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5",
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-background text-foreground selection:bg-primary selection:text-primary-foreground">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(37,99,235,0.14),_transparent_40%),linear-gradient(135deg,_rgba(255,255,255,0.96),_rgba(241,245,249,0.98))]" />
        <div className="absolute inset-0 opacity-[0.04] mix-blend-overlay" />
      </div>

      <div className="relative z-10 mx-auto flex min-h-screen w-full max-w-7xl items-center justify-center px-5 py-10 sm:px-10">
        <motion.section
          initial={reduceMotion ? false : { opacity: 0, y: 28, filter: "blur(8px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          className="grid w-full max-w-5xl overflow-hidden rounded-[2rem] border border-border bg-card shadow-[14px_14px_40px_rgba(15,23,42,0.08)] lg:grid-cols-[0.9fr_1.1fr]"
        >
          <section className="relative hidden min-h-[620px] overflow-hidden bg-[#dfe9f5] lg:flex lg:items-center lg:justify-center">
            <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.68),rgba(214,228,244,0.92))]" />
            <div className="absolute inset-0 opacity-70 bg-[linear-gradient(120deg,transparent_0%,transparent_28%,rgba(59,130,246,0.12)_28.5%,transparent_29%),linear-gradient(120deg,transparent_0%,transparent_52%,rgba(59,130,246,0.10)_52.5%,transparent_53%),linear-gradient(120deg,transparent_0%,transparent_76%,rgba(59,130,246,0.08)_76.5%,transparent_77%)]" />
            <div className="absolute left-10 top-10 z-10 flex items-center gap-3 text-[#2f80ed]">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#2f80ed] text-white shadow-[0_12px_32px_rgba(47,128,237,0.24)]">
                <Scale className="h-5 w-5" />
              </div>
              <div>
                <div className="text-2xl font-black tracking-[0.18em]">{BRAND}</div>
                <div className="mt-1 whitespace-nowrap text-[10px] font-bold uppercase tracking-[0.2em] text-[#2f80ed]/70">
                  YI LV TONG
                </div>
              </div>
            </div>

            <div className="relative z-10 flex h-full w-full items-center justify-center px-10 py-14">
              <div className="relative flex h-[560px] w-[360px] flex-col items-center justify-center">
                <div className="relative mt-16 flex select-none flex-col items-center">
                  <div className="absolute bottom-2 left-1/2 top-2 w-px -translate-x-1/2 bg-gradient-to-b from-transparent via-[#2f80ed]/30 to-transparent" />
                  {["律", "一", "通"].map((label) => (
                    <div
                      key={label}
                      className="relative text-[150px] font-black leading-none tracking-[0.04em]"
                      style={{
                        background: "linear-gradient(135deg,#2f80ed 0%,#1e3a8a 55%,#5b9bf0 100%)",
                        WebkitBackgroundClip: "text",
                        WebkitTextFillColor: "transparent",
                        backgroundClip: "text",
                        filter: "drop-shadow(8px 12px 16px rgba(47,128,237,0.28))",
                      }}
                    >
                      {label}
                    </div>
                  ))}
                </div>
                <div className="mt-10 text-center">
                  <div className="text-[13px] font-black uppercase tracking-[0.42em] text-[#1e3a8a]/80">
                    YI LV TONG
                  </div>
                  <div className="mt-2 h-px w-40 bg-gradient-to-r from-transparent via-[#2f80ed] to-transparent" />
                  <div className="mt-3 text-[10px] font-bold uppercase tracking-[0.3em] text-[#2f80ed]/60">
                    Legal Intelligence Platform
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="flex min-h-[620px] flex-col justify-center bg-card/90 p-7 sm:p-12 lg:p-16">
            <div className="mb-10 flex items-start justify-between">
              <div>
                <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-primary/10 bg-primary/8 px-3 py-1 text-[9px] font-black uppercase tracking-[0.25em] text-primary">
                  <Fingerprint className="h-3 w-3" />
                  {"\u8eab\u4efd\u6821\u9a8c"}
                </div>
                <h2 className="text-3xl font-black tracking-[0.12em] text-foreground sm:text-4xl">
                  {"\u6b22\u8fce\u56de\u6765"}
                </h2>
                <p className="mt-3 text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground">
                  {"\u9a8c\u8bc1\u51ed\u8bc1\u4ee5\u7ee7\u7eed\u5de5\u4f5c"}
                </p>
              </div>
              <ShieldCheck className="mt-1 h-6 w-6 text-primary/30" />
            </div>

            <form onSubmit={handleSubmit} noValidate className="space-y-6">
              <div>
                <label htmlFor="account" className="mb-2 flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em]">
                  <KeyRound className="h-3.5 w-3.5 text-primary" />
                  {"\u64cd\u4f5c\u5458\u8d26\u53f7"}
                </label>
                <input
                  ref={accountRef}
                  id="account"
                  value={account}
                  onChange={(event) => {
                    setAccount(event.target.value);
                    clearError("account");
                  }}
                  aria-invalid={Boolean(errors.account)}
                  aria-describedby={errors.account ? "account-error" : undefined}
                  autoComplete="username"
                  placeholder="Enter account / OPERATOR ID"
                  className={`h-14 w-full rounded-2xl border bg-secondary/40 px-4 text-sm font-bold tracking-widest outline-none transition-colors placeholder:text-muted-foreground focus:bg-card focus:ring-0 ${
                    errors.account ? "border-red-500 bg-card" : "border-border focus:border-primary/40"
                  }`}
                />
                <AnimatePresence initial={false}>
                  {errors.account && (
                    <motion.p initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} id="account-error" role="alert" className="mt-2 text-[10px] font-bold tracking-widest text-red-600">
                      {errors.account}
                    </motion.p>
                  )}
                </AnimatePresence>
              </div>

              <div>
                <label htmlFor="password" className="mb-2 flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em]">
                  <LockKeyhole className="h-3.5 w-3.5 text-primary" />
                  {"\u8bbf\u95ee\u5bc6\u7801"}
                </label>
                <div className="relative">
                  <input
                    ref={passwordRef}
                    id="password"
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(event) => {
                      setPassword(event.target.value);
                      clearError("password");
                    }}
                    aria-invalid={Boolean(errors.password)}
                    aria-describedby={errors.password ? "password-error" : undefined}
                    autoComplete="current-password"
                    placeholder="Enter password / ACCESS KEY"
                    className={`h-14 w-full rounded-2xl border bg-secondary/40 px-4 pr-14 text-sm font-bold tracking-widest outline-none transition-colors placeholder:text-muted-foreground focus:bg-card focus:ring-0 ${
                      errors.password ? "border-red-500 bg-card" : "border-border focus:border-primary/40"
                    }`}
                  />
                  <button type="button" onClick={() => setShowPassword((visible) => !visible)} aria-label={showPassword ? "Hide password" : "Show password"} className="absolute right-0 top-0 flex h-14 w-14 items-center justify-center rounded-r-2xl border-l border-border text-muted-foreground transition-colors hover:bg-primary hover:text-primary-foreground">
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <AnimatePresence initial={false}>
                  {errors.password && (
                    <motion.p initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} id="password-error" role="alert" className="mt-2 text-[10px] font-bold tracking-widest text-red-600">
                      {errors.password}
                    </motion.p>
                  )}
                </AnimatePresence>
              </div>

              <button type="submit" disabled={isLoading} className="group flex h-14 w-full items-center justify-between rounded-2xl border border-primary/20 bg-primary px-5 text-left text-xs font-black uppercase tracking-[0.24em] text-primary-foreground transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-[7px_7px_0_rgba(37,99,235,0.18)] disabled:cursor-not-allowed disabled:opacity-50">
                <span>{isLoading ? "Authorizing..." : "Access core matrix / AUTHORIZE"}</span>
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </button>
            </form>

            <p className="mt-8 border-t border-border pt-5 text-[9px] font-bold uppercase leading-5 tracking-[0.16em] text-muted-foreground">
              ACCESS POLICY · 登录账号：admin / password123 · reviewer / password123
            </p>
          </section>
        </motion.section>
      </div>
    </main>
  );
}
