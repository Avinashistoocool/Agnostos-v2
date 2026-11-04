import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CircleHelp, Square, Terminal } from "lucide-react";
import { useSession } from "../lib/session";
import { toEngineError } from "../lib/engine";
import { isActive, useJobs } from "../lib/jobs";
import type { Job } from "../lib/types";
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton, Spinner } from "../components/ui";
import { useToast } from "../components/Toast";
import { cn, fmtDate } from "../lib/util";

export function JobStatusBadge({ job }: { job: Job }) {
  switch (job.status) {
    case "running":
      return (
        <Badge tone="sage">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sage" /> Running
        </Badge>
      );
    case "waiting_input":
      return <Badge tone="amber">Needs answer</Badge>;
    case "done":
      return <Badge tone="slate">Done</Badge>;
    case "failed":
      return <Badge tone="rust">Failed</Badge>;
    case "cancelled":
      return <Badge tone="slate">Cancelled</Badge>;
    case "interrupted":
      return <Badge tone="amber">Interrupted</Badge>;
  }
}

export function Jobs() {
  const { jobs, loading } = useJobs();
  const { id } = useParams();
  const nav = useNavigate();
  const selected = jobs.find((j) => j.id === id) ?? (id ? undefined : jobs[0]);

  return (
    <>
      <PageHeader title="Jobs" subtitle="Everything Agnostos has run, with full logs." />
      {loading && !jobs.length ? (
        <Card className="p-6">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="mt-4 h-60" />
        </Card>
      ) : !jobs.length ? (
        <Card>
          <EmptyState icon={<Terminal className="h-5 w-5" />} title="No jobs yet" action={<Button variant="primary" onClick={() => nav("/pipeline")}>Open pipeline</Button>}>
            Start a step from the Pipeline and watch it here in real time.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <Card className="h-fit p-1.5">
            <ul aria-label="Jobs">
              {jobs.map((j) => (
                <li key={j.id}>
                  <button
                    onClick={() => nav(`/jobs/${j.id}`)}
                    aria-current={selected?.id === j.id ? "true" : undefined}
                    className={cn(
                      "focus-ring flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
                      selected?.id === j.id ? "bg-surface-3" : "hover:bg-surface-2",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 truncate text-sm text-cream">
                        {j.command}
                        {j.live && <span className="rounded bg-rust px-1 text-[9px] font-semibold uppercase text-cream">live</span>}
                      </div>
                      <div className="text-[11px] text-slate">{fmtDate(j.started)}</div>
                    </div>
                    <JobStatusBadge job={j} />
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {selected ? <JobDetail key={selected.id} job={selected} /> : <Card className="p-6 text-sm text-slate">Job not found.</Card>}
        </div>
      )}
    </>
  );
}

function JobDetail({ job }: { job: Job }) {
  const { engine } = useSession();
  const { logs, loadLog } = useJobs();
  const toast = useToast();
  const lines = logs[job.id];
  const box = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(true);
  const [answering, setAnswering] = useState<"y" | "n" | null>(null);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    void loadLog(job.id).catch(() => {});
  }, [job.id, loadLog]);

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines?.length, follow]);

  const answer = async (a: "y" | "n") => {
    setAnswering(a);
    try {
      await engine.call("jobs.answer", { job_id: job.id, answer: a });
    } catch (e) {
      toast.error("Couldn't send answer", toEngineError(e).message);
    } finally {
      setAnswering(null);
    }
  };

  const cancel = async () => {
    setCancelling(true);
    try {
      await engine.call("jobs.cancel", { job_id: job.id });
    } catch (e) {
      toast.error("Couldn't cancel", toEngineError(e).message);
    } finally {
      setCancelling(false);
    }
  };

  const opts = Object.entries(job.options);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-serif text-xl text-cream">{job.command}</h2>
          <JobStatusBadge job={job} />
          {job.live ? <Badge tone="rust">Live</Badge> : <Badge>Safe</Badge>}
          <div className="flex-1" />
          {isActive(job) && (
            <Button size="sm" variant="secondary" onClick={() => void cancel()} loading={cancelling} icon={<Square className="h-3.5 w-3.5" />}>
              Cancel
            </Button>
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate">
          <span>Started {fmtDate(job.started)}</span>
          {job.finished && <span>Finished {fmtDate(job.finished)}</span>}
          {job.exit_code !== undefined && job.exit_code !== null && <span>Exit code {job.exit_code}</span>}
        </div>
        {opts.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {opts.map(([k, v]) => (
              <span key={k} className="rounded-md border border-line bg-ink/60 px-2 py-0.5 font-mono text-[11px] text-slate">
                {k}=<span className="text-cream-dim">{String(v)}</span>
              </span>
            ))}
          </div>
        )}
      </Card>

      {job.status === "waiting_input" && (
        <div role="alert" data-testid="prompt-banner" className="flex flex-wrap items-center gap-4 rounded-xl border border-amber/40 bg-amber-soft px-5 py-4 animate-fade-in">
          <CircleHelp className="h-5 w-5 shrink-0 text-amber" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-cream">This job is asking you a question</div>
            <div className="mt-0.5 font-mono text-xs text-cream-dim">{job.prompt ?? "Continue? [Y/N]"}</div>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => void answer("n")} loading={answering === "n"} disabled={!!answering}>
              No
            </Button>
            <Button variant={job.live ? "danger" : "primary"} onClick={() => void answer("y")} loading={answering === "y"} disabled={!!answering}>
              Yes, continue
            </Button>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-line bg-[#0f1013] shadow-card">
        <div className="flex items-center gap-2 border-b border-line px-4 py-2 text-xs text-slate">
          <Terminal className="h-3.5 w-3.5" /> Log
          {isActive(job) && <Spinner className="h-3 w-3" />}
          <div className="flex-1" />
          <label className="flex cursor-pointer items-center gap-1.5">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-[#b5452e]" /> Follow
          </label>
        </div>
        <div
          ref={box}
          data-testid="job-log"
          role="log"
          aria-live="polite"
          className="h-[min(56vh,520px)] overflow-y-auto px-4 py-3 font-mono text-[12.5px] leading-[1.65]"
        >
          {!lines ? (
            <div className="space-y-2">
              <Skeleton className="h-3 w-2/3" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ) : lines.length === 0 ? (
            <div className="text-slate-dim">Waiting for output…</div>
          ) : (
            lines.map((l, i) => (
              <div key={i} className={cn("whitespace-pre-wrap break-words", lineTone(l))}>
                {l || "\u00a0"}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function lineTone(l: string) {
  if (/\[Y\/N\]/i.test(l)) return "text-amber";
  if (/\b(error|failed|traceback|exception)\b/i.test(l)) return "text-[#e98a72]";
  if (/\bLIVE\b/.test(l)) return "text-[#f0a08b] font-semibold";
  if (/^\s*>/.test(l)) return "text-cream";
  if (/\b(sent|done|ok|finished|wrote)\b/i.test(l)) return "text-sage";
  return "text-cream-dim/80";
}
