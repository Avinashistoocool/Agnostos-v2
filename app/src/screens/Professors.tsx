import { useEffect, useMemo, useState } from "react";
import { GraduationCap, Lock, RefreshCw, Search, X } from "lucide-react";
import { useSession } from "../lib/session";
import { toEngineError } from "../lib/engine";
import type { Professor } from "../lib/types";
import { Badge, Button, EmptyState, Field, Input, PageHeader, Skeleton, Textarea } from "../components/ui";
import { useToast } from "../components/Toast";
import { cn, useAsync } from "../lib/util";

const FILTERS = [
  ["", "All"],
  ["unsent", "Not sent"],
  ["sent", "Sent"],
  ["replied", "Replied"],
  ["failed", "Problems"],
] as const;

export function sendBadge(p: Professor) {
  const s = p.send_status.toLowerCase();
  if (p.reply_status === "bounced") return <Badge tone="rust">Bounced</Badge>;
  if (s === "sent" || s === "review-sent") return <Badge tone="sage">Sent</Badge>;
  if (s.startsWith("failed")) return <Badge tone="rust">Failed</Badge>;
  if (s === "dry-run") return <Badge tone="slate">Dry run</Badge>;
  if (s.startsWith("skipped")) return <Badge tone="slate">Skipped</Badge>;
  if (p.draft) return <Badge tone="amber">Draft</Badge>;
  return <Badge tone="slate">No draft</Badge>;
}

const isSent = (p: Professor) => ["sent", "review-sent"].includes(p.send_status.toLowerCase());

export function Professors() {
  const { engine } = useSession();
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [sel, setSel] = useState<Professor | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setQ(query), 200);
    return () => clearTimeout(t);
  }, [query]);

  const { data, loading, error, reload, setData } = useAsync(() => engine.call("professors.list", { query: q, status, offset: 0, limit: 500 }), [engine, q, status]);

  const replace = (p: Professor) => {
    setData((d) => (d ? { ...d, items: d.items.map((x) => (x.sheet === p.sheet && x.row === p.row ? p : x)) } : d));
    setSel(p);
  };

  return (
    <div className="flex gap-6">
      <div className="min-w-0 flex-1">
        <PageHeader
          title="Professors"
          subtitle={data ? `${data.total} ${data.total === 1 ? "match" : "matches"}` : "Everyone you're reaching out to"}
          actions={<Button variant="ghost" onClick={() => void reload()} icon={<RefreshCw className="h-4 w-4" />} aria-label="Refresh" />}
        />
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-dim" />
            <Input aria-label="Search professors" placeholder="Search name, university, country…" value={query} onChange={(e) => setQuery(e.target.value)} className="pl-9" />
          </div>
          <div className="flex rounded-lg border border-line bg-surface p-0.5" role="tablist" aria-label="Filter by status">
            {FILTERS.map(([k, l]) => (
              <button
                key={k}
                role="tab"
                aria-selected={status === k}
                onClick={() => setStatus(k)}
                className={cn("focus-ring rounded-md px-3 py-1.5 text-xs transition-colors", status === k ? "bg-surface-3 text-cream" : "text-slate hover:text-cream")}
              >
                {l}
              </button>
            ))}
          </div>
        </div>

        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-slate">
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="hidden px-4 py-3 font-medium md:table-cell">Institution</th>
                <th className="hidden px-4 py-3 font-medium lg:table-cell">Country</th>
                <th className="px-4 py-3 font-medium">Match</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {loading && !data
                ? Array.from({ length: 6 }, (_, i) => (
                    <tr key={i} className="border-b border-line/60">
                      <td className="px-4 py-3.5" colSpan={5}>
                        <Skeleton className="h-4" />
                      </td>
                    </tr>
                  ))
                : data?.items.map((p) => (
                    <tr
                      key={`${p.sheet}:${p.row}`}
                      tabIndex={0}
                      onClick={() => setSel(p)}
                      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSel(p))}
                      aria-selected={sel?.row === p.row && sel?.sheet === p.sheet}
                      className={cn(
                        "cursor-pointer border-b border-line/60 transition-colors last:border-0 hover:bg-surface-2 focus:bg-surface-2 focus:outline-none",
                        sel?.row === p.row && sel?.sheet === p.sheet && "bg-surface-2",
                      )}
                    >
                      <td className="px-4 py-3">
                        <div className="font-medium text-cream">{p.name}</div>
                        <div className="text-xs text-slate">{p.email}</div>
                      </td>
                      <td className="hidden px-4 py-3 text-cream-dim md:table-cell">{p.institution}</td>
                      <td className="hidden px-4 py-3 text-slate lg:table-cell">{p.country}</td>
                      <td className="px-4 py-3">
                        <MatchBar v={p.probability} />
                      </td>
                      <td className="px-4 py-3">{sendBadge(p)}</td>
                    </tr>
                  ))}
            </tbody>
          </table>
          {error && <div className="p-6 text-sm text-slate">Couldn't load professors: {error.message}</div>}
          {data && data.items.length === 0 && (
            <EmptyState icon={<GraduationCap className="h-5 w-5" />} title={q || status ? "No matches" : "No professors yet"}>
              {q || status ? "Try a different search or filter." : "Run Discover from the Pipeline to find researchers that fit your interests."}
            </EmptyState>
          )}
        </div>
      </div>
      {sel && <DraftPanel key={`${sel.sheet}:${sel.row}:${sel.version}`} prof={sel} onClose={() => setSel(null)} onSaved={replace} onConflict={() => void reload().then((d) => {
        const fresh = d?.items.find((x) => x.sheet === sel.sheet && x.row === sel.row);
        if (fresh) setSel(fresh);
      })} />}
    </div>
  );
}

function MatchBar({ v }: { v: number }) {
  const pct = Math.round(v * 100);
  return (
    <div className="flex items-center gap-2" title={`${pct}% match`}>
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-3">
        <div className={cn("h-full rounded-full", pct >= 65 ? "bg-sage" : pct >= 45 ? "bg-amber" : "bg-slate-dim")} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-[11px] text-slate">{pct}</span>
    </div>
  );
}

function DraftPanel({ prof, onClose, onSaved, onConflict }: { prof: Professor; onClose: () => void; onSaved: (p: Professor) => void; onConflict: () => void }) {
  const { engine } = useSession();
  const toast = useToast();
  const [subject, setSubject] = useState(prof.subject);
  const [draft, setDraft] = useState(prof.draft);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);
  const locked = isSent(prof);
  const dirty = subject !== prof.subject || draft !== prof.draft;
  const words = useMemo(() => draft.trim().split(/\s+/).filter(Boolean).length, [draft]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !dirty) onClose();
      if ((e.ctrlKey || e.metaKey) && e.key === "s" && dirty && !locked) {
        e.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const save = async () => {
    setSaving(true);
    setConflict(null);
    try {
      const r = await engine.call("drafts.update", { sheet: prof.sheet, row: prof.row, version: prof.version, subject, draft });
      toast.success("Draft saved");
      onSaved(r.professor);
    } catch (e) {
      const err = toEngineError(e);
      if (err.code === "conflict") setConflict(err.message);
      else toast.error("Couldn't save draft", err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside className="sticky top-0 h-[calc(100vh-8rem)] w-[460px] shrink-0 animate-slide-in" aria-label={`Draft for ${prof.name}`}>
      <div className="card flex h-full flex-col">
        <div className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="truncate font-serif text-lg text-cream">{prof.name}</div>
            <div className="truncate text-xs text-slate">
              {prof.institution} · {prof.country}
            </div>
          </div>
          {sendBadge(prof)}
          <button onClick={onClose} aria-label="Close panel" className="focus-ring rounded-md p-1 text-slate hover:bg-surface-2 hover:text-cream">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {locked && (
            <div className="flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-slate">
              <Lock className="h-3.5 w-3.5" /> Already sent, so this is read-only.
            </div>
          )}
          {conflict && (
            <div role="alert" className="rounded-lg border border-amber/30 bg-amber-soft px-3 py-2.5 text-xs text-amber">
              <div className="font-medium">Someone else changed this row</div>
              <div className="mt-0.5 text-amber/80">{conflict}. Your text is still here; reload to get the latest version, then re-apply your edits.</div>
              <div className="mt-2 flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    void navigator.clipboard?.writeText(draft).catch(() => {});
                    onConflict();
                  }}
                >
                  Copy my text &amp; reload
                </Button>
              </div>
            </div>
          )}
          {!prof.draft && !locked ? (
            <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-xs text-slate">No draft yet. Run "Match &amp; draft" to write one, or type your own below.</p>
          ) : null}
          <Field label="Subject" htmlFor="d-subject">
            <Input id="d-subject" value={subject} onChange={(e) => setSubject(e.target.value)} readOnly={locked} />
          </Field>
          <Field label="Email" htmlFor="d-body" hint={`${words} words${words > 220 ? " · shorter emails get more replies" : ""}`}>
            <Textarea id="d-body" value={draft} onChange={(e) => setDraft(e.target.value)} readOnly={locked} className="min-h-[340px] font-[450]" />
          </Field>
        </div>
        {!locked && (
          <div className="flex items-center justify-between border-t border-line px-5 py-3">
            <span className="text-[11px] text-slate-dim">
              <span className="kbd">Ctrl S</span> to save
            </span>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                disabled={!dirty || saving}
                onClick={() => {
                  setSubject(prof.subject);
                  setDraft(prof.draft);
                }}
              >
                Discard
              </Button>
              <Button variant="primary" onClick={() => void save()} loading={saving} disabled={!dirty}>
                Save draft
              </Button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
