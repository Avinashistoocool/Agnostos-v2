import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Play, ShieldAlert, Workflow } from "lucide-react";
import { useSession } from "../lib/session";
import { toEngineError } from "../lib/engine";
import { isActive, useJobs } from "../lib/jobs";
import type { CommandField, CommandSpec } from "../lib/types";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, PageHeader, Select, Skeleton, Toggle } from "../components/ui";
import { useToast } from "../components/Toast";
import { cn, useAsync } from "../lib/util";

export function defaultsFor(spec: CommandSpec): Record<string, unknown> {
  const o: Record<string, unknown> = {};
  for (const f of spec.fields) o[f.name] = f.default ?? (f.type === "bool" ? false : f.type === "choice" ? f.choices?.[0] ?? "" : f.type === "str" ? "" : undefined);
  return o;
}

export function Pipeline() {
  const { engine } = useSession();
  const { data, loading, error } = useAsync(() => engine.call("commands.list"), [engine]);
  const [params] = useSearchParams();
  const [open, setOpen] = useState<CommandSpec | null>(null);

  const groups = useMemo(() => {
    const m = new Map<string, CommandSpec[]>();
    for (const c of data?.commands ?? []) m.set(c.group, [...(m.get(c.group) ?? []), c]);
    return [...m.entries()];
  }, [data]);

  useEffect(() => {
    const want = params.get("cmd");
    if (want && data) setOpen(data.commands.find((c) => c.name === want) ?? null);
  }, [params, data]);

  return (
    <>
      <PageHeader title="Pipeline" subtitle="Each step is a job you can watch. Sending is always a dry run unless you explicitly go live." />
      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Card key={i} className="p-5">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="mt-3 h-10" />
            </Card>
          ))}
        </div>
      ) : error ? (
        <Card className="p-6 text-sm text-slate">Couldn't load commands: {error.message}</Card>
      ) : !groups.length ? (
        <Card>
          <EmptyState icon={<Workflow className="h-5 w-5" />} title="No commands available" />
        </Card>
      ) : (
        <div className="space-y-8">
          {groups.map(([g, cmds], gi) => (
            <section key={g}>
              <h2 className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-slate">
                <span className="flex h-5 w-5 items-center justify-center rounded-full border border-line text-[10px] text-cream-dim">{gi + 1}</span>
                {g}
              </h2>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {cmds.map((c) => (
                  <button
                    key={c.name}
                    onClick={() => setOpen(c)}
                    data-testid={`cmd-${c.name}`}
                    className="card focus-ring group flex flex-col p-5 text-left transition-all hover:-translate-y-0.5 hover:border-line-strong"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-cream">{c.title}</span>
                      {c.live_field && (
                        <Badge tone="rust" className="ml-auto">
                          can send mail
                        </Badge>
                      )}
                    </div>
                    <p className="mt-2 flex-1 text-xs leading-relaxed text-slate">{c.description}</p>
                    <div className="mt-4 flex items-center gap-1.5 text-xs text-slate-dim transition-colors group-hover:text-rust-hover">
                      <Play className="h-3.5 w-3.5" /> Configure &amp; run
                    </div>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
      {open && <RunDialog spec={open} onClose={() => setOpen(null)} />}
    </>
  );
}

export function RunDialog({ spec, onClose }: { spec: CommandSpec; onClose: () => void }) {
  const { engine } = useSession();
  const { jobs, upsert } = useJobs();
  const toast = useToast();
  const nav = useNavigate();
  const [opts, setOpts] = useState<Record<string, unknown>>(() => defaultsFor(spec));
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const live = !!(spec.live_field && opts[spec.live_field]);
  const confirmText = spec.confirmation ?? "SEND";
  const confirmed = !live || typed === confirmText;
  const blocking = jobs.find(isActive);

  const visibleFields = spec.fields.filter((f) => f.name !== spec.live_field);
  const basicFields = visibleFields.filter((f) => !ADVANCED.has(f.name));
  const advancedFields = visibleFields.filter((f) => ADVANCED.has(f.name));
  const liveField = spec.fields.find((f) => f.name === spec.live_field);

  const start = async () => {
    setBusy(true);
    try {
      const clean: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(opts)) if (v !== undefined && v !== "") clean[k] = v;
      const r = await engine.call("jobs.start", { command: spec.name, options: clean, ...(live ? { confirmation: typed } : {}) });
      upsert(r.job);
      toast.success(`${spec.title} started`, live ? "Live: real emails will be sent." : undefined);
      onClose();
      nav(`/jobs/${r.job.id}`);
    } catch (e) {
      const err = toEngineError(e);
      toast.error(err.code === "confirmation_required" ? "Confirmation didn't match" : "Couldn't start job", err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={spec.title}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={live ? "danger" : "primary"}
            onClick={() => void start()}
            loading={busy}
            disabled={!confirmed || !!blocking}
            data-testid="start-job"
            icon={live ? <ShieldAlert className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          >
            {live ? "Start live run" : spec.live_field ? "Start dry run" : "Start"}
          </Button>
        </>
      }
    >
      <p className="mb-5 text-sm leading-relaxed text-slate">{spec.description}</p>
      {blocking && (
        <div className="mb-4 rounded-lg border border-amber/30 bg-amber-soft px-3 py-2 text-xs text-amber">
          "{blocking.command}" is still running. Wait for it to finish or cancel it on the Jobs page.
        </div>
      )}
      <div className="space-y-4">
        {basicFields.map((f) => (
          <FieldInput key={f.name} f={f} value={opts[f.name]} onChange={(v) => setOpts((o) => ({ ...o, [f.name]: v }))} />
        ))}
        {visibleFields.length === 0 && !liveField && <p className="text-xs text-slate-dim">No options. Just run it.</p>}
        {basicFields.length > 0 && <p className="text-[11px] text-slate-dim"><span className="text-[#e07a62]">*</span> required. Everything else is optional.</p>}
        {advancedFields.length > 0 && (
          <details className="group rounded-lg border border-line bg-ink/30 px-4 py-3">
            <summary className="cursor-pointer select-none text-xs text-slate hover:text-cream">Advanced options (files, sheets, model)</summary>
            <div className="mt-4 space-y-4">
              {advancedFields.map((f) => (
                <FieldInput key={f.name} f={f} value={opts[f.name]} onChange={(v) => setOpts((o) => ({ ...o, [f.name]: v }))} />
              ))}
            </div>
          </details>
        )}
      </div>
      {liveField && (
        <div
          className={cn(
            "mt-6 rounded-xl border p-4 transition-colors",
            live ? "border-rust/60 bg-[rgba(181,69,46,0.10)]" : "border-line bg-ink/40",
          )}
          data-testid="danger-zone"
        >
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#e98a72]">
            <ShieldAlert className="h-3.5 w-3.5" /> Danger zone
          </div>
          <Toggle
            checked={live}
            onChange={(v) => {
              setOpts((o) => ({ ...o, [liveField.name]: v }));
              setTyped("");
            }}
            label={liveField.label}
            description={liveField.help ?? "Real emails to real people. This can't be undone."}
            id="live-toggle"
          />
          {live && (
            <div className="mt-4 animate-fade-in">
              <label htmlFor="confirm-text" className="text-xs text-cream-dim">
                Type <code className="rounded bg-ink px-1.5 py-0.5 font-mono text-[#f0a08b]">{confirmText}</code> to confirm
              </label>
              <Input
                id="confirm-text"
                autoComplete="off"
                spellCheck={false}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                className={cn("mt-2 font-mono", typed && !confirmed && "border-rust")}
                placeholder={confirmText}
              />
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

const ADVANCED = new Set(["xlsx", "sheet", "sources", "output", "export_dir", "resume", "model", "provider", "no_enrich", "no_profile_hop", "at", "preview", "workers", "min_score", "prestige_weight", "top_universities", "max_pages", "since", "min_works", "min_h_index", "also_universities", "list_universities", "fresh"]);

function FieldInput({ f, value, onChange }: { f: CommandField; value: unknown; onChange: (v: unknown) => void }) {
  const id = `f-${f.name}`;
  const req = !!f.required;
  if (f.type === "bool") return <Toggle id={id} checked={!!value} onChange={onChange} label={f.label} description={f.help} />;
  if (f.type === "choice")
    return (
      <Field label={f.label} hint={f.help} htmlFor={id} required={req}>
        <Select id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {(f.choices ?? []).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
      </Field>
    );
  if (f.type === "int" || f.type === "float") {
    const n = value === undefined || value === null || value === "" ? "" : String(value);
    const bad = n !== "" && ((f.min !== undefined && Number(n) < f.min) || (f.max !== undefined && Number(n) > f.max));
    return (
      <Field label={f.label} required={req} hint={f.help ?? (f.min !== undefined && f.max !== undefined ? `${f.min}–${f.max}` : undefined)} error={bad ? `Must be between ${f.min} and ${f.max}` : undefined} htmlFor={id}>
        <Input
          id={id}
          type="number"
          inputMode={f.type === "int" ? "numeric" : "decimal"}
          step={f.type === "int" ? 1 : "any"}
          min={f.min}
          max={f.max}
          value={n}
          onChange={(e) => onChange(e.target.value === "" ? undefined : f.type === "int" ? parseInt(e.target.value, 10) : parseFloat(e.target.value))}
        />
      </Field>
    );
  }
  return (
    <Field label={f.label} hint={f.help} htmlFor={id} required={req}>
      <Input id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}
