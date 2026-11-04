import { useCallback, useEffect, useRef, useState } from "react";
import { toEngineError, type EngineError } from "./engine";

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

/** Minimal async-resource hook (keeps us off a query library). */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<EngineError | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    const my = ++seq.current;
    setLoading(true);
    try {
      const v = await fnRef.current();
      if (my === seq.current) {
        setData(v);
        setError(null);
      }
      return v;
    } catch (e) {
      if (my === seq.current) setError(toEngineError(e));
      return undefined;
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, setData, error, loading, reload };
}

export function initials(name: string) {
  const parts = name.replace(/^(prof\.?|dr\.?)\s+/gi, "").trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

export function fmtDate(s?: string | null) {
  if (!s) return "";
  const d = new Date(s.replace(" ", "T"));
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function parseWindow(v: string | undefined): [number, number] | null {
  const m = /^(\d{1,2})\s*-\s*(\d{1,2})$/.exec((v ?? "").trim());
  return m ? [Number(m[1]), Number(m[2])] : null;
}
