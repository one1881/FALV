import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

type Props = {
  children: ReactNode;
};

type State = {
  error: Error | null;
};

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("页面渲染失败:", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
        <section className="max-w-lg rounded-[2rem] border border-rose-200 bg-rose-50 p-8 text-center shadow-sm">
          <AlertTriangle className="mx-auto h-10 w-10 text-rose-600" />
          <h1 className="mt-5 text-xl font-black tracking-widest text-rose-950">页面加载失败</h1>
          <p className="mt-3 text-sm font-bold leading-7 text-rose-700">
            当前页面组件发生异常，已拦截白屏。请刷新重试，或返回其他模块继续操作。
          </p>
          <p className="mt-3 rounded-2xl border border-rose-200 bg-white/70 px-4 py-3 text-left text-xs font-bold leading-6 text-rose-800">
            {this.state.error.message || "未知前端错误"}
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-6 inline-flex items-center gap-2 rounded-2xl bg-rose-600 px-5 py-3 text-xs font-black tracking-widest text-white transition-colors hover:bg-rose-700"
          >
            <RefreshCw className="h-4 w-4" />
            刷新页面
          </button>
        </section>
      </main>
    );
  }
}
