import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useStats, useTickets } from '../api/hooks'
import type { OrderStatus, StatsOverview } from '../api/types'
import { ORDER_STATUSES } from '../api/types'
import { Empty, ErrorState, Loading, ORDER_TONE, PageHeader, Panel, Priority, Table, Td, cx } from '../components/ui'
import { date, label, money, moneyCompact, relative } from '../lib/format'

const TONE_BG: Record<string, string> = {
  amber: 'bg-st-amber',
  blue: 'bg-st-blue',
  violet: 'bg-st-violet',
  green: 'bg-st-green',
  red: 'bg-st-red',
  slate: 'bg-st-slate',
}

export function Overview() {
  const stats = useStats()

  return (
    <>
      <PageHeader title="Overview" subtitle="How the store is doing, and what needs a reply." />
      {stats.isPending ? (
        <Panel>
          <Loading />
        </Panel>
      ) : stats.isError ? (
        <Panel>
          <ErrorState error={stats.error} onRetry={() => stats.refetch()} />
        </Panel>
      ) : (
        <div className="grid gap-5">
          <Headline s={stats.data} />
          <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
            <NeedsReply />
            <OrdersByStatus counts={stats.data.orders_by_status} total={stats.data.orders} />
          </div>
          <LowStock s={stats.data} />
        </div>
      )}
    </>
  )
}

function Headline({ s }: { s: StatsOverview }) {
  const days = s.revenue_last_30_days
  const last30 = days.reduce((a, d) => a + d.revenue_cents, 0)
  const orders30 = days.reduce((a, d) => a + d.orders, 0)
  const max = Math.max(...days.map((d) => d.revenue_cents), 1)
  const [hover, setHover] = useState<number | null>(null)
  const shown = hover !== null ? days[hover] : null

  return (
    <Panel>
      <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
        <div className="flex flex-col justify-between gap-5">
          <div>
            <div className="text-[13px] text-muted">{shown ? date(shown.date) : 'Revenue, last 30 days'}</div>
            <div className="num mt-1 text-[34px] font-semibold leading-none tracking-[-0.02em]">
              {money(shown ? shown.revenue_cents : last30)}
            </div>
            <div className="num mt-1.5 text-[13px] text-muted">
              {shown ? `${shown.orders} orders` : `${orders30} orders`}
            </div>
          </div>
          <dl className="grid grid-cols-3 gap-3 border-t border-line pt-4 lg:grid-cols-1 lg:gap-2">
            {[
              ['All-time revenue', moneyCompact(s.revenue_cents)],
              ['Customers', s.customers.toLocaleString()],
              ['Refunded', moneyCompact(s.refunded_cents)],
            ].map(([k, v]) => (
              <div key={k} className="flex flex-col lg:flex-row lg:items-baseline lg:justify-between">
                <dt className="text-[13px] text-muted">{k}</dt>
                <dd className="num text-[15px] font-medium">{v}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="flex min-h-[180px] flex-col" onMouseLeave={() => setHover(null)}>
          <div className="flex flex-1 items-end gap-[3px]" role="img" aria-label="Daily revenue for the last 30 days">
            {days.map((d, i) => (
              <button
                key={d.date}
                type="button"
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                aria-label={`${date(d.date)}: ${money(d.revenue_cents)}, ${d.orders} orders`}
                className="group flex h-full flex-1 cursor-default items-end focus-visible:outline-offset-0"
              >
                <span
                  className={cx(
                    'w-full rounded-t-[3px] transition-colors',
                    hover === i ? 'bg-cobalt' : hover === null ? 'bg-cobalt/70' : 'bg-cobalt/30',
                  )}
                  style={{ height: `${Math.max((d.revenue_cents / max) * 100, d.revenue_cents ? 2 : 0.5)}%` }}
                />
              </button>
            ))}
          </div>
          <div className="mt-2 flex justify-between border-t border-line pt-1.5 text-[12px] text-muted">
            <span>{date(days[0].date)}</span>
            <span>Today</span>
          </div>
        </div>
      </div>
    </Panel>
  )
}

function NeedsReply() {
  const q = useTickets({ status: ['open'], priority: ['urgent', 'high'], page_size: 6 })
  return (
    <Panel
      title="Waiting on a reply"
      flush
      actions={
        <Link to="/tickets?status=open" className="text-[13px] font-medium text-cobalt hover:underline">
          Open queue
        </Link>
      }
    >
      {q.isPending ? (
        <Loading rows={4} />
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : q.data.items.length === 0 ? (
        <Empty>No high-priority tickets open. Nice.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {q.data.items.map((t) => (
            <li key={t.id}>
              <Link to={`/tickets/${t.id}`} className="flex items-center gap-4 px-4 py-2.5 hover:bg-sunken">
                <span className="w-[76px] shrink-0">
                  <Priority value={t.priority} />
                </span>
                <span className="min-w-0 flex-1 truncate text-[14px]">{t.subject}</span>
                <span className="shrink-0 text-[12px] text-muted">{relative(t.created_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function OrdersByStatus({ counts, total }: { counts: Record<OrderStatus, number>; total: number }) {
  return (
    <Panel title="Orders by status">
      <div className="flex h-3 overflow-hidden rounded-full bg-sunken" aria-hidden>
        {ORDER_STATUSES.map((s) =>
          counts[s] ? (
            <span key={s} className={TONE_BG[ORDER_TONE[s]]} style={{ width: `${(counts[s] / Math.max(total, 1)) * 100}%` }} />
          ) : null,
        )}
      </div>
      <ul className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2">
        {ORDER_STATUSES.map((s) => (
          <li key={s}>
            <Link to={`/orders?status=${s}`} className="flex items-center justify-between gap-2 text-[13.5px] hover:text-cobalt">
              <span className="flex items-center gap-2">
                <span className={cx('h-2.5 w-2.5 rounded-sm', TONE_BG[ORDER_TONE[s]])} aria-hidden />
                {label(s)}
              </span>
              <span className="num text-muted">{counts[s]}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function LowStock({ s }: { s: StatsOverview }) {
  return (
    <Panel
      title="Running low"
      flush
      actions={
        <Link to="/products?in_stock=false" className="text-[13px] font-medium text-cobalt hover:underline">
          Out of stock
        </Link>
      }
    >
      {s.low_stock_products.length === 0 ? (
        <Empty>Every active product has more than 5 in stock.</Empty>
      ) : (
        <Table head={['Product', 'SKU', 'Price', 'In stock']}>
          {s.low_stock_products.map((p) => (
            <tr key={p.id}>
              <Td>{p.name}</Td>
              <Td className="font-mono text-[12.5px] text-muted">{p.sku}</Td>
              <Td className="num">{money(p.price_cents)}</Td>
              <Td className={cx('num font-medium', p.stock === 0 ? 'text-danger' : 'text-st-amber')}>
                {p.stock === 0 ? 'Sold out' : p.stock}
              </Td>
            </tr>
          ))}
        </Table>
      )}
    </Panel>
  )
}
