import { useNavigate } from "react-router-dom";
import { ArrowRight, Inbox, MailCheck, Reply, Send, Terminal, TriangleAlert, Users } from "lucide-react";
import { useSession } from "../lib/session";
import { useJobs } from "../lib/jobs";
import { fmtDate, useAsync } from "../lib/util";
import type { Stats } from "../lib/types";
import { Button, Card, EmptyState, PageHeader, Skeleton } from "../components/ui";
import { JobStatusBadge } from "./Jobs";

function Kpi({ label, value, sub, icon, tone }: { label: string; value: number | string; sub?: string; icon: React.ReactNode; tone?: string }) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between text-slate">
        <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
        <span className={tone ?? "text-slate-dim"}>{icon}</span>
      </div>
      <div className="mt-3 font-serif text-[34px] leading-none tracking-tight text-cream">{value}</div>
      {sub && <div className="mt-2 text-xs text-slate">{sub}</div>}
    </Card>
  );
}

export function BarChart({ data }: { data: Stats["sent_per_day"] }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const H = 140;
  return (
    <div className="w-full" role="img" aria-label={`Emails sent per day, last ${data.length} days`}>
      <div className="flex h-[160px] items-end gap-1.5">
        {data.map((d) => {
          const h = Math.max(d.count ? 4 : 2, (d.count / max) * H);
          return (
            <div key={d.date} className="group relative flex flex-1 flex-col items-center justify-end">
              <div className="pointer-events-none absolute -top-1 -translate-y-full whitespace-nowrap rounded-md border border-line bg-surface-3 px-2 py-1 text-[11px] text-cream opacity-0 transition-opacity group-hover:opacity-100">
                {d.count} on {new Date(d.date).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
              </div>
              <div
                className={d.count ? "w-full rounded-t-md bg-rust/80 transition-colors group-hover:bg-rust-hover" : "w-full rounded-t-sm bg-surface-3"}
                style={{ height: h }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between text-[10px] text-slate-dim">
        <span>{data[0] && new Date(data[0].date).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>
        <span>today</span>
      </div>
    </div>
  );
}

export function Dashboard() {
  const { engine, user } = useSession();
  const { jobs } = useJobs();
  const nav = useNavigate();
  const { data: stats, loading, error, reload } = useAsync(() => engine.call("stats.get"), [engine]);
  const hour = new Date().getHours();
  const greet = hour < 5 ? "Working late" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const first = user?.provider === "guest" ? "" : `, ${user?.name.split(" ")[0]}`;
  const replyRate = stats && stats.sent ? Math.round((stats.replied / stats.sent) * 100) : 0;

  return (
    <>
      <PageHeader
        title={`${greet}${first}`}
        subtitle="Here's how your outreach is going."
        actions={
          <Button variant="secondary" onClick={() => nav("/replies")} icon={<Reply className="h-4 w-4" />}>
            Review replies
          </Button>
        }
      />
      {error ? (
        <Card className="p-6 text-sm text-slate">
          Couldn't load stats: {error.message}{" "}
          <button className="text-rust-hover underline" onClick={() => void reload()}>
            Retry
          </button>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" data-testid="kpis">
            {loading || !stats ? (
              Array.from({ length: 4 }, (_, i) => (
                <Card key={i} className="p-5">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="mt-4 h-8 w-16" />
                  <Skeleton className="mt-3 h-3 w-24" />
                </Card>
              ))
            ) : (
              <>
                <Kpi label="Professors" value={stats.total} sub={`${stats.with_email} with a verified email`} icon={<Users className="h-4 w-4" />} />
                <Kpi label="Drafted" value={stats.drafted} sub="ready for your review" icon={<Inbox className="h-4 w-4" />} />
                <Kpi label="Sent" value={stats.sent} sub={stats.resends ? `${stats.resends} resent` : "paced & capped"} icon={<Send className="h-4 w-4" />} tone="text-rust-hover" />
                <Kpi label="Replies" value={stats.replied} sub={`${replyRate}% reply rate`} icon={<MailCheck className="h-4 w-4" />} tone="text-sage" />
              </>
            )}
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card className="p-5 lg:col-span-2">
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-medium text-cream">Sent per day</h2>
                  <p className="text-xs text-slate">Last two weeks</p>
                </div>
                {stats && stats.bounced > 0 && (
                  <span className="flex items-center gap-1.5 text-xs text-amber">
                    <TriangleAlert className="h-3.5 w-3.5" /> {stats.bounced} bounced
                  </span>
                )}
              </div>
              {stats ? (
                stats.sent_per_day.some((d) => d.count) ? (
                  <BarChart data={stats.sent_per_day} />
                ) : (
                  <EmptyState icon={<Send className="h-5 w-5" />} title="Nothing sent yet">
                    When you send your first batch, you'll see it here.
                  </EmptyState>
                )
              ) : (
                <Skeleton className="h-[160px]" />
              )}
            </Card>

            <Card className="flex flex-col p-5">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-medium text-cream">Recent jobs</h2>
                <button onClick={() => nav("/jobs")} className="focus-ring rounded text-xs text-slate hover:text-cream">
                  View all
                </button>
              </div>
              {jobs.length === 0 ? (
                <EmptyState icon={<Terminal className="h-5 w-5" />} title="No jobs yet">
                  Run something from the Pipeline.
                </EmptyState>
              ) : (
                <ul className="-mx-2 space-y-0.5">
                  {jobs.slice(0, 6).map((j) => (
                    <li key={j.id}>
                      <button
                        onClick={() => nav(`/jobs/${j.id}`)}
                        className="focus-ring group flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-surface-2"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm text-cream">{j.command}</div>
                          <div className="text-[11px] text-slate">{fmtDate(j.started)}</div>
                        </div>
                        <JobStatusBadge job={j} />
                        <ArrowRight className="h-3.5 w-3.5 text-slate-dim opacity-0 transition-opacity group-hover:opacity-100" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
