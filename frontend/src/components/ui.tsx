import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'

import { ApiError } from '../api/client'
import type { OrderStatus, TicketPriority, TicketStatus } from '../api/types'
import { label } from '../lib/format'

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

// ---------- status badges ----------

type Tone = 'amber' | 'blue' | 'violet' | 'green' | 'red' | 'slate'

const TONES: Record<Tone, string> = {
  amber: 'bg-st-amber-wash text-st-amber',
  blue: 'bg-st-blue-wash text-st-blue',
  violet: 'bg-st-violet-wash text-st-violet',
  green: 'bg-st-green-wash text-st-green',
  red: 'bg-st-red-wash text-st-red',
  slate: 'bg-st-slate-wash text-st-slate',
}

export const ORDER_TONE: Record<OrderStatus, Tone> = {
  pending: 'amber',
  paid: 'blue',
  shipped: 'violet',
  delivered: 'green',
  cancelled: 'slate',
  refunded: 'red',
}

const TICKET_TONE: Record<TicketStatus, Tone> = {
  open: 'blue',
  pending: 'amber',
  resolved: 'green',
  closed: 'slate',
}

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={cx('inline-flex items-center rounded px-1.5 py-0.5 text-[12px] font-medium leading-4', TONES[tone])}>
      {children}
    </span>
  )
}

export const OrderBadge = ({ status }: { status: OrderStatus }) => (
  <Badge tone={ORDER_TONE[status]}>{label(status)}</Badge>
)

export const TicketBadge = ({ status }: { status: TicketStatus }) => (
  <Badge tone={TICKET_TONE[status]}>{label(status)}</Badge>
)

/** Priority as a small signal-strength glyph: easier to scan in a queue than a word. */
export function Priority({ value }: { value: TicketPriority }) {
  const level = { low: 1, medium: 2, high: 3, urgent: 4 }[value]
  const color = value === 'urgent' ? 'bg-danger' : value === 'high' ? 'bg-st-amber' : 'bg-faint'
  return (
    <span className="inline-flex items-center gap-2 text-[13px] text-muted">
      <span className="flex h-3 items-end gap-[2px]" aria-hidden>
        {[1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className={cx('w-[3px] rounded-[1px]', i <= level ? color : 'bg-line')}
            style={{ height: `${i * 3}px` }}
          />
        ))}
      </span>
      {label(value)}
    </span>
  )
}

// ---------- controls ----------

type BtnVariant = 'primary' | 'secondary' | 'danger' | 'ghost'

const BTN: Record<BtnVariant, string> = {
  primary: 'bg-cobalt text-cobalt-ink hover:brightness-110',
  secondary: 'bg-surface text-ink border border-line hover:bg-sunken',
  danger: 'bg-surface text-danger border border-line hover:bg-danger-wash',
  ghost: 'text-muted hover:text-ink hover:bg-sunken',
}

export function Button({
  variant = 'secondary',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant }) {
  return (
    <button
      className={cx(
        'inline-flex h-8 items-center justify-center gap-1.5 rounded-md px-3 text-[13px] font-medium',
        'cursor-pointer transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        BTN[variant],
        className,
      )}
      {...props}
    />
  )
}

const field =
  'h-8 rounded-md border border-line bg-surface px-2.5 text-[13px] text-ink placeholder:text-faint focus:border-cobalt focus:outline-none'

export const Input = ({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) => (
  <input className={cx(field, className)} {...props} />
)

export function Select<T extends string>({
  value,
  onChange,
  options,
  placeholder,
  className,
  ...props
}: Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange' | 'value'> & {
  value: T | ''
  onChange: (v: T | '') => void
  options: readonly T[]
  placeholder?: string
}) {
  return (
    <select
      className={cx(field, selectChrome, className)}
      value={value}
      onChange={(e) => onChange(e.target.value as T | '')}
      {...props}
    >
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o} value={o}>
          {label(o)}
        </option>
      ))}
    </select>
  )
}

export function Field({ label: text, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[13px] font-medium text-muted">{text}</span>
      {children}
      {error && <span className="text-[12px] text-danger">{error}</span>}
    </label>
  )
}

/** Native select with a consistent chevron (keeps keyboard + mobile behaviour). */
export const selectChrome = 'select-chrome'

// ---------- layout ----------

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.01em]">{title}</h1>
        {subtitle && <div className="mt-1 text-[14px] text-muted">{subtitle}</div>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Panel({
  title,
  actions,
  children,
  className,
  flush,
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  flush?: boolean
}) {
  return (
    <section className={cx('min-w-0 rounded-lg border border-line bg-surface', className)}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[14px] font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      <div className={flush ? '' : 'p-4'}>{children}</div>
    </section>
  )
}

export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="mb-3 flex flex-wrap items-center gap-2">{children}</div>
}

// ---------- tables ----------

export function Table({
  head,
  children,
  alignRight = [],
}: {
  head: ReactNode[]
  children: ReactNode
  /** Column indexes whose header should be right-aligned (to sit over numbers). */
  alignRight?: number[]
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-[13.5px]">
        <thead>
          <tr className="border-b border-line">
            {head.map((h, i) => (
              <th
                key={i}
                className={cx(
                  'whitespace-nowrap px-4 py-2 text-[12.5px] font-medium text-muted',
                  alignRight.includes(i) && 'text-right',
                )}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&>tr:not(:last-child)]:border-b [&>tr]:border-line">{children}</tbody>
      </table>
    </div>
  )
}

export const Td = ({ children, className }: { children: ReactNode; className?: string }) => (
  <td className={cx('px-4 py-2.5 align-middle', className)}>{children}</td>
)

export function Pagination({
  page,
  pages,
  total,
  onPage,
}: {
  page: number
  pages: number
  total: number
  onPage: (p: number) => void
}) {
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-[13px] text-muted">
      <span className="num">
        {total.toLocaleString()} {total === 1 ? 'result' : 'results'}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </Button>
        <span className="num">
          {page} of {pages}
        </span>
        <Button variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  )
}

// ---------- states ----------

export function Loading({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-5 animate-pulse rounded bg-sunken" style={{ width: `${90 - (i % 3) * 15}%` }} />
      ))}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.message : 'Something went wrong loading this.'
  return (
    <div className="flex flex-col items-start gap-3 p-6">
      <p className="text-[14px] text-danger">{message}</p>
      {onRetry && <Button onClick={onRetry}>Try again</Button>}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-10 text-center text-[14px] text-muted">{children}</div>
}

export function MutationError({ error }: { error: unknown }) {
  if (!error) return null
  const message = error instanceof ApiError ? error.message : 'That didn’t work. Try again.'
  return <p className="text-[13px] text-danger">{message}</p>
}

export { cx }
