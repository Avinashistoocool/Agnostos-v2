import { MessagesSquare, RefreshCw } from "lucide-react";
import { useSession } from "../lib/session";
import { fmtDate, useAsync } from "../lib/util";
import { Button, Card, EmptyState, PageHeader, Skeleton } from "../components/ui";

export function Conversations() {
  const { engine } = useSession();
  const { data, loading, error, reload } = useAsync(() => engine.call("conversations.get"), [engine]);
  return (
    <>
      <PageHeader
        title="Conversations"
        subtitle={data?.modified ? `Updated ${fmtDate(data.modified)}` : "Every thread, in one place"}
        actions={
          <Button variant="ghost" onClick={() => void reload()} loading={loading && !!data} icon={<RefreshCw className="h-4 w-4" />}>
            Refresh
          </Button>
        }
      />
      <Card className="overflow-hidden">
        {loading && !data ? (
          <div className="space-y-3 p-6">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : error ? (
          <div className="p-6 text-sm text-slate">Couldn't load conversations: {error.message}</div>
        ) : !data?.html ? (
          <EmptyState icon={<MessagesSquare className="h-5 w-5" />} title="No conversations yet">
            Once professors reply, full threads show up here.
          </EmptyState>
        ) : (
          <iframe
            title="Conversations"
            sandbox=""
            referrerPolicy="no-referrer"
            srcDoc={data.html}
            className="block h-[calc(100vh-13rem)] w-full bg-ink"
          />
        )}
      </Card>
    </>
  );
}
