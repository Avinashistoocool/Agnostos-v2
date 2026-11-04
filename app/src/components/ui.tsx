import { forwardRef, useEffect, useId, useRef, useState } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import { LoaderCircle, X } from "lucide-react";
import { cn } from "../lib/util";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-rust text-cream hover:bg-rust-hover shadow-[0_1px_0_rgba(255,255,255,0.12)_inset] disabled:hover:bg-rust",
  secondary: "bg-surface-2 text-cream border border-line hover:border-line-strong hover:bg-surface-3",
  ghost: "text-slate hover:text-cream hover:bg-surface-2",
  subtle: "bg-transparent text-cream border border-line hover:bg-surface-2",
  danger: "bg-[#8f2d1d] text-cream hover:bg-[#a53723] border border-[#c9583f]/40",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-11 px-5 text-sm gap-2",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "focus-ring inline-flex select-none items-center justify-center whitespace-nowrap rounded-lg font-medium transition-all duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100",
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("card", className)} {...rest}>
      {children}
    </div>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
  className,
  required,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
  className?: string;
  required?: boolean;
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="label">
        {label}
        {required && (
          <span className="ml-0.5 text-[#e07a62]" aria-hidden="true">
            *
          </span>
        )}
      </label>
      {children}
      {error ? <p className="mt-1.5 text-xs text-[#e07a62]">{error}</p> : hint ? <p className="mt-1.5 text-xs text-slate">{hint}</p> : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn("input", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={cn("input min-h-[120px] resize-y leading-relaxed", className)} {...rest} />;
});

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn("input appearance-none bg-[length:12px] pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  id,
  disabled,
  tone = "rust",
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: ReactNode;
  description?: ReactNode;
  id?: string;
  disabled?: boolean;
  tone?: "rust" | "sage";
}) {
  const auto = useId();
  const tid = id ?? auto;
  return (
    <div className="flex items-start gap-3">
      <button
        id={tid}
        role="switch"
        type="button"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "focus-ring relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
          checked ? (tone === "sage" ? "border-sage bg-sage" : "border-rust bg-rust") : "border-line-strong bg-surface-3",
        )}
      >
        <span
          className={cn(
            "inline-block h-3.5 w-3.5 rounded-full bg-cream shadow transition-transform duration-200",
            checked ? "translate-x-[18px]" : "translate-x-[2px]",
          )}
        />
      </button>
      {(label || description) && (
        <label htmlFor={tid} className="cursor-pointer select-none">
          {label && <div className="text-sm text-cream">{label}</div>}
          {description && <div className="mt-0.5 text-xs text-slate">{description}</div>}
        </label>
      )}
    </div>
  );
}

export function Checkbox({ checked, onChange, children, id }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; id?: string }) {
  const auto = useId();
  const cid = id ?? auto;
  return (
    <label htmlFor={cid} className="flex cursor-pointer select-none items-center gap-2.5 text-sm text-cream-dim">
      <input
        id={cid}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="focus-ring h-4 w-4 rounded border-line-strong bg-surface-2 accent-[#b5452e]"
      />
      {children}
    </label>
  );
}

export function Chip({
  children,
  onRemove,
  active,
  onClick,
  className,
}: {
  children: ReactNode;
  onRemove?: () => void;
  active?: boolean;
  onClick?: () => void;
  className?: string;
}) {
  const base = cn(
    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
    active ? "border-rust/60 bg-rust-soft text-cream" : "border-line bg-surface-2 text-cream-dim",
    onClick && "focus-ring cursor-pointer hover:border-line-strong hover:text-cream",
    className,
  );
  const inner = (
    <>
      {children}
      {onRemove && (
        <span
          role="button"
          tabIndex={0}
          aria-label={`Remove ${typeof children === "string" ? children : "item"}`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onRemove();
            }
          }}
          className="focus-ring -mr-1 rounded-full p-0.5 text-slate hover:bg-surface-3 hover:text-cream"
        >
          <X className="h-3 w-3" />
        </span>
      )}
    </>
  );
  return onClick ? (
    <button type="button" onClick={onClick} className={base} aria-pressed={active}>
      {inner}
    </button>
  ) : (
    <span className={base}>{inner}</span>
  );
}

/** Free-text chip input: Enter or comma adds, Backspace removes last. */
export function ChipInput({
  value,
  onChange,
  placeholder,
  suggestions = [],
  label,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
  label?: string;
}) {
  const [text, setText] = useState("");
  const add = (raw: string) => {
    const v = raw.trim().replace(/,$/, "").trim();
    if (!v) return;
    if (!value.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...value, v]);
    setText("");
  };
  const remaining = suggestions.filter((s) => !value.some((x) => x.toLowerCase() === s.toLowerCase()));
  return (
    <div>
      <div className="input flex min-h-[44px] flex-wrap items-center gap-1.5 py-1.5">
        {value.map((v) => (
          <Chip key={v} active onRemove={() => onChange(value.filter((x) => x !== v))}>
            {v}
          </Chip>
        ))}
        <input
          aria-label={label ?? placeholder}
          value={text}
          onChange={(e) => {
            const t = e.target.value;
            if (t.endsWith(",")) add(t);
            else setText(t);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(text);
            } else if (e.key === "Backspace" && !text && value.length) {
              onChange(value.slice(0, -1));
            }
          }}
          onBlur={() => add(text)}
          placeholder={value.length ? "" : placeholder}
          className="min-w-[120px] flex-1 bg-transparent py-1 text-sm text-cream outline-none placeholder:text-slate-dim"
        />
      </div>
      {remaining.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {remaining.map((s) => (
            <Chip key={s} onClick={() => onChange([...value, s])}>
              + {s}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4", className)} aria-hidden />;
}

export function EmptyState({ icon, title, children, action }: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center animate-fade-in">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-line bg-surface-2 text-slate">{icon}</div>
      <h3 className="font-serif text-lg text-cream">{title}</h3>
      {children && <p className="mt-1.5 max-w-sm text-sm text-slate">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Badge({ tone = "slate", children, className }: { tone?: "slate" | "rust" | "sage" | "amber"; children: ReactNode; className?: string }) {
  const tones = {
    slate: "bg-surface-3 text-slate border-line",
    rust: "bg-rust-soft text-[#e98a72] border-rust/30",
    sage: "bg-sage-soft text-sage border-sage/30",
    amber: "bg-amber-soft text-amber border-amber/30",
  };
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-medium", tones[tone], className)}>
      {children}
    </span>
  );
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-max max-w-[260px] -translate-x-1/2 rounded-lg border border-line bg-surface-3 px-2.5 py-1.5 text-xs leading-snug text-cream-dim opacity-0 shadow-pop transition-opacity duration-150 group-focus-within:opacity-100 group-hover:opacity-100"
      >
        {content}
      </span>
    </span>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = "md",
  labelledBy,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  labelledBy?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const tid = useId();
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const t = setTimeout(() => {
      const el = ref.current?.querySelector<HTMLElement>("[data-autofocus], input, textarea, button:not([data-close])");
      el?.focus();
    }, 20);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && ref.current) {
        const f = ref.current.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
        if (!f.length) return;
        const first = f[0];
        const last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  const w = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" }[size];
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-[2px] animate-fade-in" onClick={onClose} aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy ?? (title ? tid : undefined)}
        className={cn("relative w-full rounded-2xl border border-line bg-surface shadow-pop animate-fade-in", w)}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-line px-6 py-4">
            <h2 id={tid} className="font-serif text-lg text-cream">
              {title}
            </h2>
            <button data-close onClick={onClose} aria-label="Close" className="focus-ring rounded-md p-1 text-slate hover:bg-surface-2 hover:text-cream">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
        <div className="px-6 py-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = "Confirm",
  tone = "primary",
  onConfirm,
  onCancel,
  busy,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  tone?: "primary" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant={tone === "danger" ? "danger" : "primary"} onClick={onConfirm} loading={busy} data-autofocus>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-sm leading-relaxed text-cream-dim">{children}</div>
    </Modal>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-serif text-[28px] leading-tight tracking-tight text-cream">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={cn("h-4 w-4 animate-spin text-slate", className)} aria-label="Loading" />;
}
