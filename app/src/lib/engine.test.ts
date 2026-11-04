import { describe, expect, it, vi } from "vitest";
import { createMockEngine, EngineError, toEngineError } from "./engine";
import type { EngineEvent, Job } from "./types";

const waitFor = async (pred: () => boolean, ms = 3000) => {
  const t0 = Date.now();
  while (!pred()) {
    if (Date.now() - t0 > ms) throw new Error("timeout");
    await new Promise((r) => setTimeout(r, 10));
  }
};

describe("toEngineError", () => {
  it("normalises engine error objects, strings and JSON strings", () => {
    expect(toEngineError({ code: "conflict", message: "stale" })).toMatchObject({ code: "conflict", message: "stale" });
    expect(toEngineError('{"code":"unavailable","message":"down"}').code).toBe("unavailable");
    expect(toEngineError("boom")).toMatchObject({ code: "internal", message: "boom" });
    expect(toEngineError(new EngineError("auth_failed", "x"))).toBeInstanceOf(EngineError);
  });
});

describe("mock engine", () => {
  it("requires sign in and supports guest + onboarding", async () => {
    const { engine } = createMockEngine({ latency: 0 });
    const info = await engine.call("app.info");
    expect(info.user).toBeNull();
    await expect(engine.call("stats.get")).rejects.toMatchObject({ code: "not_signed_in" });
    const { user } = await engine.call("auth.guest", {});
    expect(user.provider).toBe("guest");
    let ob = await engine.call("onboarding.complete", { step: "resume" });
    expect(ob.completed).toEqual(["resume"]);
    expect(ob.done).toBe(false);
    for (const s of ["profile", "interests", "targets", "email", "llm", "funding", "limits"] as const)
      ob = await engine.call("onboarding.complete", { step: s });
    expect(ob.done).toBe(true);
  });

  it("registers and logs in local accounts", async () => {
    const { engine } = createMockEngine({ latency: 0 });
    await engine.call("auth.register", { name: "A", email: "a@x.io", password: "longenough" });
    await engine.call("auth.logout");
    await expect(engine.call("auth.login", { email: "a@x.io", password: "nope" })).rejects.toMatchObject({ code: "auth_failed" });
    const r = await engine.call("auth.login", { email: "a@x.io", password: "longenough" });
    expect(r.user.email).toBe("a@x.io");
  });

  it("reports unavailable providers", async () => {
    const { engine } = createMockEngine({ latency: 0, unavailable: ["google", "github"] });
    await expect(engine.call("auth.google", { connect_gmail: true })).rejects.toMatchObject({ code: "unavailable" });
    await expect(engine.call("auth.github.start")).rejects.toMatchObject({ code: "unavailable" });
  });

  it("masks secrets and ignores masked values on update", async () => {
    const { engine } = createMockEngine({ latency: 0, signedIn: true });
    await engine.call("settings.update", { values: { GROQ_API_KEY: "gsk_secret1234" } });
    const { settings, secrets } = await engine.call("settings.get");
    expect(secrets).toContain("GROQ_API_KEY");
    expect(settings.GROQ_API_KEY).toBe("••••1234");
    await engine.call("settings.update", { values: { GROQ_API_KEY: settings.GROQ_API_KEY } });
    expect((await engine.call("llm.test")).ok).toBe(true);
  });

  it("enforces optimistic locking on drafts and refuses sent rows", async () => {
    const { engine } = createMockEngine({ latency: 0, signedIn: true });
    const { items } = await engine.call("professors.list", { status: "unsent" });
    const p = items[0];
    const r = await engine.call("drafts.update", { sheet: p.sheet, row: p.row, version: p.version, draft: "hello" });
    expect(r.professor.draft).toBe("hello");
    expect(r.professor.version).not.toBe(p.version);
    await expect(engine.call("drafts.update", { sheet: p.sheet, row: p.row, version: p.version, draft: "again" })).rejects.toMatchObject({
      code: "conflict",
    });
    const sent = (await engine.call("professors.list", { status: "sent" })).items[0];
    await expect(engine.call("drafts.update", { sheet: sent.sheet, row: sent.row, version: sent.version, draft: "x" })).rejects.toMatchObject({
      code: "conflict",
    });
  });

  it("filters professors by query", async () => {
    const { engine } = createMockEngine({ latency: 0, signedIn: true });
    const r = await engine.call("professors.list", { query: "cern" });
    expect(r.total).toBe(1);
    expect(r.items[0].institution).toBe("CERN");
  });

  it("versions the reply queue", async () => {
    const { engine } = createMockEngine({ latency: 0, signedIn: true });
    const { items, version } = await engine.call("replies.list");
    const r = await engine.call("replies.update", { index: items[0].index, version, body: "ok", approved: true });
    expect(r.version).not.toBe(version);
    await expect(engine.call("replies.update", { index: 0, version, body: "x", approved: false })).rejects.toMatchObject({ code: "conflict" });
  });

  it("requires exact confirmation for live jobs", async () => {
    const { engine } = createMockEngine({ latency: 0, signedIn: true, logInterval: 1 });
    await expect(engine.call("jobs.start", { command: "send", options: { live: true } })).rejects.toMatchObject({ code: "confirmation_required" });
    await expect(engine.call("jobs.start", { command: "send", options: { live: true }, confirmation: "send live" })).rejects.toMatchObject({
      code: "confirmation_required",
    });
    const { job } = await engine.call("jobs.start", { command: "send", options: { live: true }, confirmation: "SEND LIVE" });
    expect(job.live).toBe(true);
  });

  it("streams logs, prompts [Y/N], and finishes after answer", async () => {
    const { engine } = createMockEngine({ latency: 0, signedIn: true, logInterval: 1 });
    const events: EngineEvent[] = [];
    const off = engine.on((e) => events.push(e));
    const { job } = await engine.call("jobs.start", { command: "send", options: { limit: 2 } });
    expect(job.status).toBe("running");
    await waitFor(() => events.some((e) => e.event === "job.prompt"));
    const st = (await engine.call("jobs.list")).jobs.find((j) => j.id === job.id) as Job;
    expect(st.status).toBe("waiting_input");
    expect(st.prompt).toMatch(/\[Y\/N\]/);
    await engine.call("jobs.answer", { job_id: job.id, answer: "y" });
    await waitFor(() => events.some((e) => e.event === "job.status" && e.data.job.id === job.id && e.data.job.status === "done"));
    const log = await engine.call("jobs.log", { job_id: job.id });
    expect(log.lines.some((l) => l.includes("dry-run"))).toBe(true);
    expect(log.offset).toBe(log.lines.length);
    const tail = await engine.call("jobs.log", { job_id: job.id, offset: log.offset - 1 });
    expect(tail.lines).toHaveLength(1);
    off();
  });

  it("cancels a waiting job and answering 'n' aborts", async () => {
    const { engine } = createMockEngine({ latency: 0, signedIn: true, logInterval: 1 });
    const spy = vi.fn();
    engine.on(spy);
    const { job } = await engine.call("jobs.start", { command: "run", options: {} });
    await waitFor(() => spy.mock.calls.some(([e]) => e.event === "job.prompt"));
    await engine.call("jobs.answer", { job_id: job.id, answer: "n" });
    const j = (await engine.call("jobs.list")).jobs.find((x) => x.id === job.id)!;
    expect(j.status).toBe("cancelled");
  });
});
