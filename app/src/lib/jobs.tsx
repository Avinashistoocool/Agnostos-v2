import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useSession } from "./session";
import type { Job } from "./types";

type JobsState = {
  jobs: Job[];
  logs: Record<string, string[]>;
  reload: () => Promise<void>;
  loadLog: (id: string) => Promise<void>;
  upsert: (j: Job) => void;
  loading: boolean;
};

const JobsCtx = createContext<JobsState | null>(null);

export function useJobs() {
  const c = useContext(JobsCtx);
  if (!c) throw new Error("useJobs outside provider");
  return c;
}

export const isActive = (j: Job) => j.status === "running" || j.status === "waiting_input";

/** Keeps the job list and live logs in sync with engine events. */
export function JobsProvider({ children }: { children: ReactNode }) {
  const { engine } = useSession();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const offsets = useRef<Record<string, number>>({});

  const upsert = useCallback((j: Job) => {
    setJobs((prev) => {
      const i = prev.findIndex((x) => x.id === j.id);
      if (i === -1) return [j, ...prev];
      const next = prev.slice();
      next[i] = { ...prev[i], ...j };
      return next;
    });
  }, []);

  const reload = useCallback(async () => {
    try {
      const r = await engine.call("jobs.list");
      setJobs(r.jobs);
    } finally {
      setLoading(false);
    }
  }, [engine]);

  const loadLog = useCallback(
    async (id: string) => {
      const r = await engine.call("jobs.log", { job_id: id, offset: 0 });
      offsets.current[id] = r.offset;
      // Live events may have raced ahead of the snapshot; keep whichever is longer.
      setLogs((l) => ({ ...l, [id]: (l[id]?.length ?? 0) > r.lines.length ? l[id] : r.lines }));
    },
    [engine],
  );

  useEffect(() => {
    void reload();
    return engine.on((ev) => {
      if (ev.event === "job.log") {
        const { job_id, line } = ev.data;
        offsets.current[job_id] = (offsets.current[job_id] ?? 0) + 1;
        setLogs((l) => ({ ...l, [job_id]: [...(l[job_id] ?? []), line] }));
      } else if (ev.event === "job.status") {
        upsert(ev.data.job);
      } else if (ev.event === "job.prompt") {
        setJobs((prev) => prev.map((j) => (j.id === ev.data.job_id ? { ...j, status: "waiting_input", prompt: ev.data.text } : j)));
      }
    });
  }, [engine, reload, upsert]);

  return <JobsCtx.Provider value={{ jobs, logs, reload, loadLog, upsert, loading }}>{children}</JobsCtx.Provider>;
}
