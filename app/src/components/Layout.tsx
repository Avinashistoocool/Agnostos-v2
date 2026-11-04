import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronDown,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Reply,
  Settings,
  Terminal,
  Workflow,
} from "lucide-react";
import { useSession } from "../lib/session";
import { isActive, useJobs } from "../lib/jobs";
import { cn, initials } from "../lib/util";
import { Badge, Tooltip } from "./ui";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/professors", label: "Professors", icon: GraduationCap },
  { to: "/replies", label: "Replies", icon: Reply },
  { to: "/conversations", label: "Conversations", icon: MessagesSquare },
  { to: "/pipeline", label: "Pipeline", icon: Workflow },
  { to: "/jobs", label: "Jobs", icon: Terminal },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Avatar({ name, url, size = 28 }: { name: string; url?: string | null; size?: number }) {
  if (url) return <img src={url} alt="" className="rounded-full object-cover" style={{ width: size, height: size }} />;
  return (
    <span
      className="inline-flex items-center justify-center rounded-full bg-gradient-to-br from-rust to-[#7a2b1c] font-medium text-cream"
      style={{ width: size, height: size, fontSize: size * 0.38 }}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}

export function Layout() {
  const { user, signOut, engine } = useSession();
  const { jobs } = useJobs();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("ag.sidebar") === "1");
  const [menu, setMenu] = useState(false);
  const nav = useNavigate();
  const loc = useLocation();
  const running = jobs.filter(isActive);
  const waiting = jobs.some((j) => j.status === "waiting_input");

  useEffect(() => localStorage.setItem("ag.sidebar", collapsed ? "1" : "0"), [collapsed]);
  useEffect(() => setMenu(false), [loc.pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setCollapsed((c) => !c);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const title = NAV.find((n) => loc.pathname.startsWith(n.to))?.label ?? "";

  return (
    <div className="flex h-full bg-ink">
      <aside
        className={cn(
          "flex shrink-0 flex-col border-r border-line bg-[#131418] transition-[width] duration-200",
          collapsed ? "w-[60px]" : "w-[220px]",
        )}
        aria-label="Main navigation"
      >
        <div className={cn("flex h-14 items-center gap-2.5 border-b border-line", collapsed ? "justify-center px-0" : "px-4")}>
          <img src="/agnostos-icon.png" alt="" className="h-7 w-7 rounded-lg" />
          {!collapsed && <span className="font-serif text-[19px] tracking-tight text-cream">Agnostos</span>}
        </div>
        <nav className="flex-1 space-y-0.5 p-2">
          {NAV.map(({ to, label, icon: Icon }) => {
            const link = (
              <NavLink
                key={to}
                to={to}
                className={({ isActive: a }) =>
                  cn(
                    "focus-ring group relative flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors",
                    a ? "bg-surface-2 text-cream" : "text-slate hover:bg-surface hover:text-cream",
                    collapsed && "justify-center px-0",
                  )
                }
              >
                {({ isActive: a }) => (
                  <>
                    {a && <span className="absolute left-0 top-1.5 h-5 w-[3px] rounded-r bg-rust" aria-hidden />}
                    <Icon className="h-[18px] w-[18px] shrink-0" />
                    {!collapsed && <span className="flex-1">{label}</span>}
                    {to === "/jobs" && running.length > 0 && (
                      <span
                        className={cn(
                          "h-2 w-2 rounded-full",
                          waiting ? "bg-amber" : "bg-sage",
                          "animate-pulse",
                          collapsed && "absolute right-2 top-2",
                        )}
                        aria-label={waiting ? "A job needs your answer" : "Job running"}
                      />
                    )}
                  </>
                )}
              </NavLink>
            );
            return collapsed ? (
              <Tooltip key={to} content={label}>
                <div className="w-full">{link}</div>
              </Tooltip>
            ) : (
              link
            );
          })}
        </nav>
        <div className="border-t border-line p-2">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className={cn(
              "focus-ring flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-xs text-slate hover:bg-surface hover:text-cream",
              collapsed && "justify-center px-0",
            )}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
            {!collapsed && (
              <>
                <span className="flex-1 text-left">Collapse</span>
                <span className="kbd">Ctrl B</span>
              </>
            )}
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-ink/80 px-6 backdrop-blur">
          <div className="text-sm text-slate">{title}</div>
          {engine.isMock && (
            <Badge tone="amber" className="ml-1">
              Demo data
            </Badge>
          )}
          <div className="flex-1" />
          {running.length > 0 && (
            <button onClick={() => nav(`/jobs/${running[0].id}`)} className="focus-ring flex items-center gap-2 rounded-lg px-2 py-1 text-xs text-slate hover:text-cream">
              <span className={cn("h-2 w-2 animate-pulse rounded-full", waiting ? "bg-amber" : "bg-sage")} />
              {waiting ? "Waiting for your answer" : `${running[0].command} running`}
            </button>
          )}
          <button
            onClick={() => nav("/pipeline")}
            className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-lg bg-rust px-3 text-xs font-medium text-cream transition-colors hover:bg-rust-hover"
          >
            <Play className="h-3.5 w-3.5" /> Run pipeline
          </button>
          <div className="relative">
            <button
              onClick={() => setMenu(!menu)}
              aria-haspopup="menu"
              aria-expanded={menu}
              className="focus-ring flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 hover:bg-surface"
              data-testid="user-menu"
            >
              <Avatar name={user?.name ?? "?"} url={user?.avatar_url} />
              <span className="max-w-[140px] truncate text-sm text-cream">{user?.name}</span>
              <ChevronDown className="h-3.5 w-3.5 text-slate" />
            </button>
            {menu && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setMenu(false)} aria-hidden />
                <div role="menu" className="absolute right-0 z-50 mt-1.5 w-60 rounded-xl border border-line bg-surface-2 p-1.5 shadow-pop animate-fade-in">
                  <div className="px-3 py-2">
                    <div className="text-sm text-cream">{user?.name}</div>
                    <div className="truncate text-xs text-slate">{user?.email ?? (user?.provider === "guest" ? "Guest account" : "")}</div>
                  </div>
                  <div className="my-1 h-px bg-line" />
                  <button role="menuitem" onClick={() => nav("/settings")} className="focus-ring flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-cream-dim hover:bg-surface-3">
                    <Settings className="h-4 w-4" /> Settings
                  </button>
                  <button role="menuitem" onClick={() => void signOut()} className="focus-ring flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-cream-dim hover:bg-surface-3">
                    <LogOut className="h-4 w-4" /> Sign out
                  </button>
                </div>
              </>
            )}
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div key={loc.pathname.split("/")[1]} className="mx-auto max-w-[1200px] px-8 py-8 animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
