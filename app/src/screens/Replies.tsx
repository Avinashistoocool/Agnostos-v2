import { useState } from "react";
import { CircleCheck, Inbox, RefreshCw, Send } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../lib/session";
import { toEngineError } from "../lib/engine";
import type { ReplyDraft } from "../lib/types";
import { Badge, Button, Card, ConfirmDialog, EmptyState, PageHeader, Skeleton, Textarea, Toggle } from "../components/ui";
import { useToast } from "../components/Toast";
import { fmtDate, useAsync } from "../lib/util";
import { Avatar } from "../components/Layout";

export function Replies() {
  const { engine } = useSession();
  const nav = useNavigate();
  const { data, loading, error, reload, setData } = useAsync(() => engine.call("replies.list"), [engine]);
  const approved = data?.items.filter((r) => r.approved && !r.sent_at).length ?? 0;

  const onVersion = (index: number, patch: Partial<ReplyDraft>, version: string) =>
    setData((d) => (d ? { version, items: d.items.map((r) => (r.index === index ? { ...r, ...patch } : r)) } : d));

  return (
    <>
      <PageHeader
        title="Replies"
        subtitle="Read what professors said and approve the responses you want sent."
        actions={
          <>
            <Button variant="ghost" onClick={() => void reload()} icon={<RefreshCw className="h-4 w-4" />} aria-label="Refresh" />
            <Button variant="secondary" disabled={!approved} onClick={() => nav("/pipeline?cmd=replies")} icon={<Send className="h-4 w-4" />}>
              Send {approved || ""} approved
            </Button>
          </>
        }
      />
      {loading && !data ? (
        <div className="space-y-4">
          {[0, 1].map((i) => (
            <Card key={i} className="p-6">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="mt-4 h-20" />
            </Card>
          ))}
        </div>
      ) : error ? (
        <Card className="p-6 text-sm text-slate">Couldn't load replies: {error.message}</Card>
      ) : !data?.items.length ? (
        <Card>
          <EmptyState icon={<Inbox className="h-5 w-5" />} title="No replies yet" action={<Button onClick={() => nav("/pipeline")}>Check for replies</Button>}>
            Professors usually take a few days to a couple of weeks. Agnostos drafts a response for each reply it finds.
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-4">
          {data.items.map((r) => (
            <ReplyCard key={r.index} r={r} version={data.version} onSaved={onVersion} onConflict={() => void reload()} />
          ))}
        </div>
      )}
    </>
  );
}

function ReplyCard({
  r,
  version,
  onSaved,
  onConflict,
}: {
  r: ReplyDraft;
  version: string;
  onSaved: (i: number, p: Partial<ReplyDraft>, v: string) => void;
  onConflict: () => void;
}) {
  const { engine } = useSession();
  const toast = useToast();
  const [body, setBody] = useState(r.body);
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const sent = !!r.sent_at;
  const dirty = body !== r.body;

  const save = async (approved: boolean) => {
    setSaving(true);
    try {
      const res = await engine.call("replies.update", { index: r.index, version, body, approved });
      onSaved(r.index, { body, approved }, res.version);
      toast.success(approved ? "Reply approved" : approved !== r.approved ? "Approval removed" : "Reply saved");
      setConfirm(false);
    } catch (e) {
      const err = toEngineError(e);
      if (err.code === "conflict") {
        toast.warning("The reply queue changed", "Reloaded the latest version. Your edit wasn't saved.");
        onConflict();
      } else toast.error("Couldn't save reply", err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="overflow-hidden" data-testid={`reply-${r.index}`}>
      <div className="flex items-center gap-3 border-b border-line px-5 py-4">
        <Avatar name={r.name} size={34} />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-cream">{r.name}</div>
          <div className="truncate text-xs text-slate">{r.subject}</div>
        </div>
        {sent ? (
          <Badge tone="sage">
            <CircleCheck className="h-3 w-3" /> Sent {fmtDate(r.sent_at)}
          </Badge>
        ) : r.approved ? (
          <Badge tone="sage">Approved</Badge>
        ) : (
          <Badge tone="amber">Needs review</Badge>
        )}
      </div>
      <div className="grid gap-0 lg:grid-cols-2">
        <div className="border-b border-line p-5 lg:border-b-0 lg:border-r">
          <div className="label">Their message</div>
          <div className="mb-4 rounded-lg border-l-2 border-sage/60 bg-ink/40 px-4 py-3 text-sm leading-relaxed text-cream-dim whitespace-pre-wrap">{r.their_message}</div>
          <div className="label">Summary</div>
          <p className="text-sm text-cream">{r.summary}</p>
          {r.action && <p className="mt-2 text-xs text-slate">Suggested: {r.action}</p>}
        </div>
        <div className="flex flex-col p-5">
          <label className="label" htmlFor={`reply-body-${r.index}`}>
            Your reply
          </label>
          <Textarea id={`reply-body-${r.index}`} value={body} onChange={(e) => setBody(e.target.value)} readOnly={sent} className="min-h-[180px] flex-1" />
          {!sent && (
            <div className="mt-4 flex items-center justify-between gap-3">
              <Toggle
                tone="sage"
                checked={r.approved}
                onChange={(v) => (v ? setConfirm(true) : void save(false))}
                label="Approved to send"
                id={`approve-${r.index}`}
              />
              <Button size="sm" variant="secondary" disabled={!dirty} loading={saving && !confirm} onClick={() => void save(r.approved)}>
                Save edits
              </Button>
            </div>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={confirm}
        title="Approve this reply?"
        confirmLabel="Approve"
        busy={saving}
        onCancel={() => setConfirm(false)}
        onConfirm={() => void save(true)}
      >
        Approved replies may be sent the next time <b className="text-cream">Send approved replies</b> runs live, to{" "}
        <span className="text-cream">{r.email}</span>. Read it once more: it goes out exactly as written.
      </ConfirmDialog>
    </Card>
  );
}
