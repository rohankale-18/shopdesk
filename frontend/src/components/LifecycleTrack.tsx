import type { Order } from '../api/types'
import { date, dateTime } from '../lib/format'
import { cx } from './ui'

type Step = { key: string; label: string; at: string | null; done: boolean }

/**
 * Parcel-tracking style view of where an order is in its life:
 * Placed -> Paid -> Shipped -> Delivered, with an end cap for cancelled/refunded.
 */
export function LifecycleTrack({ order, compact = false }: { order: Order; compact?: boolean }) {
  const s = order.status
  const steps: Step[] = [
    { key: 'placed', label: 'Placed', at: order.placed_at, done: true },
    { key: 'paid', label: 'Paid', at: null, done: ['paid', 'shipped', 'delivered', 'refunded'].includes(s) },
    { key: 'shipped', label: 'Shipped', at: order.shipped_at, done: !!order.shipped_at },
    { key: 'delivered', label: 'Delivered', at: order.delivered_at, done: !!order.delivered_at },
  ]
  const lastDone = steps.reduce((acc, st, i) => (st.done ? i : acc), 0)

  const terminal = s === 'cancelled' ? 'Cancelled' : s === 'refunded' ? 'Refunded' : null
  // A cancelled or refunded order stops where it got to, then shows the end cap.
  const shown = terminal ? steps.slice(0, lastDone + 1) : steps

  return (
    <ol className="flex w-full items-start" aria-label={`Order status: ${s}`}>
      {shown.map((st, i) => {
        const isLastStep = i === shown.length - 1
        const hasConnector = !isLastStep || !!terminal
        const connectorSolid = isLastStep ? true : shown[i + 1].done
        const current = !terminal && i === lastDone
        return (
          <li key={st.key} className={cx('flex min-w-0 flex-col', hasConnector && 'flex-1')}>
            <div className="flex items-center">
              <span
                className={cx(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2',
                  st.done ? 'border-cobalt bg-cobalt' : 'border-line bg-surface',
                  current && 'ring-4 ring-cobalt-wash',
                )}
                aria-hidden
              >
                {st.done && (
                  <svg viewBox="0 0 12 12" className="h-3 w-3 text-cobalt-ink">
                    <path
                      d="M2.5 6.2 5 8.5l4.5-5"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </span>
              {hasConnector && (
                <span
                  className={cx(
                    'mx-1.5 flex-1 border-t-2',
                    connectorSolid ? 'border-cobalt' : 'border-dashed border-line',
                    isLastStep && terminal === 'Refunded' && 'border-st-red',
                    isLastStep && terminal === 'Cancelled' && 'border-st-slate',
                  )}
                />
              )}
            </div>
            <div className="mt-2 pr-2">
              <div className={cx('text-[13px] font-medium', st.done ? 'text-ink' : 'text-faint')}>{st.label}</div>
              <div className="num text-[12px] text-muted-foreground">{st.at ? (compact ? date(st.at).replace(/, \d{4}$/, '') : dateTime(st.at)) : st.done ? 'Confirmed' : 'Not yet'}</div>
            </div>
          </li>
        )
      })}
      {terminal && (
        <li className="flex shrink-0 flex-col">
          <span
            className={cx(
              'flex h-6 items-center rounded-full px-2.5 text-[12px] font-semibold',
              terminal === 'Refunded' ? 'bg-st-red-wash text-st-red' : 'bg-st-slate-wash text-st-slate',
            )}
          >
            {terminal}
          </span>
        </li>
      )}
    </ol>
  )
}
