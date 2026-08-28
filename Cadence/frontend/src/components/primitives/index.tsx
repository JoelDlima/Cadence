import { forwardRef } from 'react';
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}

/* ------------------------------------------------------------------ button */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

const buttonVariants: Record<ButtonVariant, string> = {
  primary:
    'bg-[var(--color-ink)] text-[var(--color-paper)] hover:bg-[#262b2d] disabled:bg-[var(--color-ink-subtle)]',
  secondary:
    'bg-[var(--color-surface)] text-[var(--color-ink)] border border-[var(--color-line-strong)] hover:border-[var(--color-ink-subtle)] hover:bg-[var(--color-surface-subtle)]',
  ghost: 'bg-transparent text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]',
  danger: 'bg-[var(--color-rejected)] text-white hover:opacity-90',
};

const buttonSizes: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-[12.5px]',
  md: 'h-9 px-4 text-[13.5px]',
  lg: 'h-11 px-5 text-sm',
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', loading, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-md font-medium tracking-tight',
        'transition-[background-color,border-color,opacity,transform] duration-[var(--duration-micro)] ease-[var(--ease-dayflow)]',
        'active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 disabled:active:scale-100 cursor-pointer',
        buttonVariants[variant],
        buttonSizes[size],
        className,
      )}
      {...rest}
    >
      {loading && (
        <span aria-hidden className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
      )}
      {children}
    </button>
  );
});

/* -------------------------------------------------------------------- card */

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={cn(
        'rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface)]',
        'shadow-[var(--shadow-card)]',
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, action, subtitle }: { title: string; action?: ReactNode; subtitle?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--color-line)] px-5 py-3.5">
      <div>
        <h2 className="text-[12px] font-semibold uppercase tracking-wider text-[var(--color-ink-muted)]">
          {title}
        </h2>
        {subtitle && <p className="text-[11px] text-[var(--color-ink-subtle)] mt-0.5">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

/* ------------------------------------------------------------------- badge */

export type BadgeTone = 'approved' | 'pending' | 'rejected' | 'info' | 'neutral';

const badgeTones: Record<BadgeTone, string> = {
  approved: 'bg-[var(--color-approved-wash)] text-[var(--color-approved)] border border-[var(--color-approved)]/20',
  pending: 'bg-[var(--color-pending-wash)] text-[var(--color-pending)] border border-[var(--color-pending)]/20',
  rejected: 'bg-[var(--color-rejected-wash)] text-[var(--color-rejected)] border border-[var(--color-rejected)]/20',
  info: 'bg-[var(--color-info-wash)] text-[var(--color-info)] border border-[var(--color-info)]/20',
  neutral: 'bg-[var(--color-surface-subtle)] text-[var(--color-ink-muted)] border border-[var(--color-line)]',
};

export function Badge({ tone = 'neutral', children, className }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium tracking-tight',
        badgeTones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ header */

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-[var(--color-line)] mb-6">
      <div>
        <h1 className="display text-3xl sm:text-4xl text-[var(--color-ink)] font-normal">
          {title}
        </h1>
        {description && (
          <p className="mt-1 text-[13.5px] text-[var(--color-ink-muted)] leading-relaxed">
            {description}
          </p>
        )}
      </div>
      {action && <div className="shrink-0 flex items-center gap-3">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------- inputs */

const controlBase =
  'w-full rounded-md border bg-[var(--color-surface)] px-3 text-sm text-[var(--color-ink)] ' +
  'placeholder:text-[var(--color-ink-subtle)] transition-colors duration-[var(--duration-micro)] ' +
  'focus:border-[var(--color-ink)] focus:outline-none disabled:opacity-60';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ className, invalid, ...rest }, ref) {
    return (
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          controlBase,
          'h-9',
          invalid ? 'border-[var(--color-rejected)]' : 'border-[var(--color-line)]',
          className,
        )}
        {...rest}
      />
    );
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <select
        ref={ref}
        className={cn(controlBase, 'h-9 border-[var(--color-line)]', className)}
        {...rest}
      >
        {children}
      </select>
    );
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  function Textarea({ className, invalid, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          controlBase,
          'min-h-24 resize-y py-2 leading-relaxed',
          invalid ? 'border-[var(--color-rejected)]' : 'border-[var(--color-line)]',
          className,
        )}
        {...rest}
      />
    );
  },
);

/* -------------------------------------------------------------- feedback */

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn('animate-pulse rounded bg-[var(--color-line)]', className)}
    />
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <p className="text-[14px] font-medium text-[var(--color-ink)]">{title}</p>
      <p className="max-w-sm text-[13px] text-[var(--color-ink-muted)]">{description}</p>
      {action && <div className="pt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <p className="text-sm text-[var(--color-rejected)]">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
