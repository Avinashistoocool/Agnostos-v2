import type { EngineEvent, MethodName, ParamsOf, ResultOf, ErrorCode } from "./types";
import { MockEngine } from "./mock";

export class EngineError extends Error {
  code: ErrorCode | string;
  constructor(code: ErrorCode | string, message: string) {
    super(message);
    this.name = "EngineError";
    this.code = code;
  }
}

export function toEngineError(e: unknown): EngineError {
  if (e instanceof EngineError) return e;
  if (e && typeof e === "object") {
    const o = e as { code?: unknown; message?: unknown };
    if (typeof o.code === "string") return new EngineError(o.code, String(o.message ?? o.code));
    if (typeof o.message === "string") return new EngineError("internal", o.message);
  }
  if (typeof e === "string") {
    try {
      return toEngineError(JSON.parse(e));
    } catch {
      return new EngineError("internal", e);
    }
  }
  return new EngineError("internal", "Unexpected error");
}

export type EventHandler = (ev: EngineEvent) => void;
export type FileDropEvent = { type: "enter" | "over" | "leave" | "drop"; paths?: string[] };

export interface Transport {
  readonly kind: "tauri" | "mock";
  call(method: string, params: unknown): Promise<unknown>;
  listen(handler: EventHandler): () => void;
  restart(): Promise<void>;
  pickResume(): Promise<string | null>;
  openUrl(url: string): Promise<void>;
  /** Native OS file drag-drop (Tauri). No-op in the browser, where HTML drop events work. */
  onFileDrop(handler: (e: FileDropEvent) => void): () => void;
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

class TauriTransport implements Transport {
  readonly kind = "tauri" as const;

  async call(method: string, params: unknown): Promise<unknown> {
    const { invoke } = await import("@tauri-apps/api/core");
    try {
      return await invoke("engine_call", { method, params: params ?? {} });
    } catch (e) {
      throw toEngineError(e);
    }
  }

  listen(handler: EventHandler): () => void {
    let un: (() => void) | null = null;
    let cancelled = false;
    void import("@tauri-apps/api/event").then(({ listen }) =>
      listen<EngineEvent>("engine://event", (e) => handler(e.payload)).then((u) => {
        if (cancelled) u();
        else un = u;
      }),
    );
    return () => {
      cancelled = true;
      un?.();
    };
  }

  async restart(): Promise<void> {
    const { invoke } = await import("@tauri-apps/api/core");
    try {
      await invoke("engine_restart");
    } catch (e) {
      throw toEngineError(e);
    }
  }

  async pickResume(): Promise<string | null> {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const res = await open({ multiple: false, directory: false, filters: [{ name: "Resume", extensions: ["pdf", "docx"] }] });
    return typeof res === "string" ? res : null;
  }

  async openUrl(url: string): Promise<void> {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
  }

  onFileDrop(handler: (e: FileDropEvent) => void): () => void {
    let un: (() => void) | null = null;
    let cancelled = false;
    void import("@tauri-apps/api/webview").then(({ getCurrentWebview }) =>
      getCurrentWebview()
        .onDragDropEvent((e) => handler({ type: e.payload.type, paths: "paths" in e.payload ? e.payload.paths : undefined }))
        .then((u) => {
          if (cancelled) u();
          else un = u;
        }),
    );
    return () => {
      cancelled = true;
      un?.();
    };
  }
}

class MockTransport implements Transport {
  readonly kind = "mock" as const;
  constructor(readonly mock: MockEngine) {}
  async call(method: string, params: unknown) {
    try {
      return await this.mock.handle(method, params);
    } catch (e) {
      throw toEngineError(e);
    }
  }
  listen(handler: EventHandler) {
    return this.mock.subscribe(handler);
  }
  async restart() {
    this.mock.restart();
  }
  async pickResume() {
    return "C:\\Users\\student\\Documents\\resume.pdf";
  }
  async openUrl(url: string) {
    window.open(url, "_blank", "noopener");
  }
  onFileDrop() {
    return () => {};
  }
}

/** Typed engine client. All UI â†” engine traffic goes through here. */
export class EngineClient {
  constructor(readonly transport: Transport) {}

  get isMock() {
    return this.transport.kind === "mock";
  }

  call<M extends MethodName>(method: M, ...args: undefined extends ParamsOf<M> ? [ParamsOf<M>?] : [ParamsOf<M>]): Promise<ResultOf<M>> {
    return this.transport.call(method, args[0] ?? {}) as Promise<ResultOf<M>>;
  }

  on(handler: EventHandler): () => void {
    return this.transport.listen(handler);
  }

  restart() {
    return this.transport.restart();
  }

  pickResume() {
    return this.transport.pickResume();
  }

  openUrl(url: string) {
    return this.transport.openUrl(url);
  }

  onFileDrop(handler: (e: FileDropEvent) => void) {
    return this.transport.onFileDrop(handler);
  }
}

export function createEngine(): EngineClient {
  if (isTauri()) return new EngineClient(new TauriTransport());
  const latency = typeof window !== "undefined" && /[?&]fast\b/.test(window.location.search) ? 0 : 250;
  return new EngineClient(new MockTransport(new MockEngine({ latency })));
}

export function createMockEngine(opts?: ConstructorParameters<typeof MockEngine>[0]) {
  const mock = new MockEngine(opts);
  return { engine: new EngineClient(new MockTransport(mock)), mock };
}

export const engine = createEngine();
