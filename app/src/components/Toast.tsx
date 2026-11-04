import { createContext, useCallback, useContext, useRef, useState } from "react";
import type { ReactNode } from "react";
import { CircleCheck, CircleX, Info, TriangleAlert, X } from "lucide-react";
import { cn } from "../lib/util";

type Tone = "success" | "error" | "info" | "warning";
type Toast = { id: number; tone: Tone; title: string; detail?: string };

type Ctx = { push: (tone: Tone, title: string, detail?: string) => void };
const ToastCtx = createContext<Ctx>({ push: () => {} });

export function useToast() {
  const { push } = useContext(ToastCtx);
  return {
    success: (t: string, d?: string) => push("success", t, d),
    error: (t: string, d?: string) => push("error", t, d),
    info: (t: string, d?: string) => push("info", t, d),
    warning: (t: string, d?: string) => push("warning", t, d),
  };
}

const icons = {
  success: <CircleCheck className="h-4 w-4 text-sage" />,
  error: <CircleX className="h-4 w-4 text-[#e07a62]" />,
  info: <Info className="h-4 w-4 text-slate" />,
  warning: <TriangleAlert className="h-4 w-4 text-amber" />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (tone: Tone, title: string, detail?: string) => {
      const id = ++seq.current;
      setToasts((t) => [...t.slice(-3), { id, tone, title, detail }]);
      setTimeout(() => dismiss(id), tone === "error" ? 7000 : 4000);
    },
    [dismiss],
  );
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[60] flex w-[360px] flex-col gap-2" aria-live="polite" role="status">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "pointer-events-auto flex items-start gap-3 rounded-xl border border-line bg-surface-2/95 px-4 py-3 shadow-pop backdrop-blur animate-slide-in",
            )}
          >
            <div className="mt-0.5">{icons[t.tone]}</div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-cream">{t.title}</div>
              {t.detail && <div className="mt-0.5 break-words text-xs text-slate">{t.detail}</div>}
            </div>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="focus-ring rounded p-0.5 text-slate hover:text-cream">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
