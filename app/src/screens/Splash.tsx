import { RefreshCw, PlugZap } from "lucide-react";
import { useSession } from "../lib/session";
import { Button } from "../components/ui";

export function Splash() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 bg-ink" aria-busy="true">
      <img src="/agnostos-icon.png" alt="" className="h-16 w-16 animate-pulse rounded-2xl" />
      <div className="font-serif text-2xl tracking-tight text-cream">Agnostos</div>
      <div className="h-1 w-40 overflow-hidden rounded-full bg-surface-2">
        <div className="skeleton h-full w-full" />
      </div>
      <p className="text-xs text-slate">Starting the engine…</p>
    </div>
  );
}

export function EngineDown() {
  const { error, restart, status } = useSession();
  return (
    <div className="flex h-full items-center justify-center bg-ink p-6">
      <div className="card w-full max-w-md p-8 text-center animate-fade-in">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl border border-rust/30 bg-rust-soft text-[#e98a72]">
          <PlugZap className="h-5 w-5" />
        </div>
        <h1 className="font-serif text-2xl text-cream">The engine isn't responding</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate">
          Agnostos runs a small background engine that does the actual work. It didn't start or stopped unexpectedly. Your data is safe.
        </p>
        {error && (
          <pre className="mt-4 max-h-32 overflow-auto rounded-lg border border-line bg-ink px-3 py-2 text-left font-mono text-[11px] text-slate">
            {error.code}: {error.message}
          </pre>
        )}
        <Button variant="primary" className="mt-6" onClick={() => void restart()} loading={status === "loading"} icon={<RefreshCw className="h-4 w-4" />}>
          Restart engine
        </Button>
      </div>
    </div>
  );
}
