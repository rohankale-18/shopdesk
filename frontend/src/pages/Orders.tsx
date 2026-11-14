import { Link, useNavigate, useParams } from 'react-router-dom'

import { useOrder, useOrders, useTickets } from '../api/hooks'
import type { OrderStatus } from '../api/types'
import { ORDER_STATUSES } from '../api/types'
import { LifecycleTrack } from '../components/LifecycleTrack'
import { OrderActions } from '../components/OrderActions'
import { SearchInput } from '../components/SearchInput'
import {
  Empty,
  ErrorState,
  FilterBar,
  Loading,
  OrderBadge,
  PageHeader,
  Pagination,
  Panel,
  Select,
  Table,
  Td,
  TicketBadge,
  selectChrome,
} from '../components/ui'
import { date, dateTime, label, money } from '../lib/format'
import { useUrlFilters } from '../lib/useUrlFilters'

const SORTS = ['-placed_at', 'placed_at', '-total', 'total'] as const
const SORT_LABEL: Record<(typeof SORTS)[number], string> = {
  '-placed_at': 'Newest first',
  placed_at: 'Oldest first',
  '-total': 'Highest total',
  total: 'Lowest total',
}

export function Orders() {
  const { values, page, set, setPage } = useUrlFilters(['q', 'status', 'sort', 'customer_id'] as const)
  const navigate = useNavigate()
  const q = useOrders({
    q: values.q,
    status: values.status ? [values.status] : undefined,
    sort: values.sort || undefined,
    customer_id: values.customer_id || undefined,
    page,
    page_size: 20,
  })

  return (
    <>
      <PageHeader title="Orders" subtitle="Every order placed in the store." />
      <FilterBar>
        <SearchInput value={values.q} onChange={(v) => set('q', v)} placeholder="Order number, e.g. ORD-00000042" />
        <Select<OrderStatus>
          value={values.status as OrderStatus | ''}
          onChange={(v) => set('status', v)}
          options={ORDER_STATUSES}
          placeholder="Any status"
          aria-label="Status"
        />
        <select
          value={values.sort || '-placed_at'}
          onChange={(e) => set('sort', e.target.value === '-placed_at' ? '' : e.target.value)}
          aria-label="Sort"
          className={`h-8 rounded-md border border-line bg-surface px-2.5 text-[13px] text-ink focus:border-cobalt focus:outline-none ${selectChrome}`}
        >
          {SORTS.map((s) => (
            <option key={s} value={s}>
              {SORT_LABEL[s]}
            </option>
          ))}
        </select>
      </FilterBar>

      <Panel flush>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data.items.length === 0 ? (
          <Empty>No orders match these filters.</Empty>
        ) : (
          <>
            <Table head={['Order', 'Placed', 'Status', 'Items', 'Total']} alignRight={[4]}>
              {q.data.items.map((o) => (
                <tr key={o.id} onClick={() => navigate(`/orders/${o.id}`)} className="cursor-pointer hover:bg-sunken">
                  <Td>
                    <Link to={`/orders/${o.id}`} className="font-mono text-[13px] hover:text-cobalt">
                      {o.number}
                    </Link>
                  </Td>
                  <Td className="whitespace-nowrap text-muted">{date(o.placed_at)}</Td>
                  <Td>
                    <OrderBadge status={o.status} />
                  </Td>
                  <Td className="num text-muted">{o.item_count}</Td>
                  <Td className="num text-right font-medium">{money(o.total_cents)}</Td>
                </tr>
              ))}
            </Table>
            <Pagination page={q.data.page} pages={q.data.pages} total={q.data.total} onPage={setPage} />
          </>
        )}
      </Panel>
    </>
  )
}

export function OrderDetail() {
  const id = Number(useParams().id)
  const q = useOrder(id)
  const tickets = useTickets({ order_id: id, page_size: 10 })

  if (q.isPending) return <Panel><Loading /></Panel>
  if (q.isError) return <Panel><ErrorState error={q.error} onRetry={() => q.refetch()} /></Panel>
  const o = q.data

  return (
    <>
      <Link to="/orders" className="mb-3 inline-block text-[13px] text-muted hover:text-ink">
        All orders
      </Link>
      <PageHeader
        title={<span className="font-mono text-[24px] tracking-normal">{o.number}</span>}
        subtitle={
          <>
            Placed {dateTime(o.placed_at)} by{' '}
            <Link to={`/customers/${o.customer.id}`} className="text-cobalt hover:underline">
              {o.customer.name}
            </Link>
          </>
        }
      />

      <div className="grid gap-5">
        <Panel>
          <div className="grid gap-6 md:grid-cols-[1fr_auto] md:items-start">
            <LifecycleTrack order={o} />
            <div className="md:min-w-[220px] md:border-l md:border-line md:pl-6">
              <div className="text-[13px] text-muted">Tracking</div>
              <div className="font-mono text-[13px]">{o.tracking_number ?? 'Not shipped yet'}</div>
              <div className="mt-3 text-[13px] text-muted">Ship to</div>
              <div className="text-[13.5px]">{o.shipping_address}</div>
            </div>
          </div>
        </Panel>

        <div className="grid items-start gap-5 lg:grid-cols-[1fr_360px]">
          <Panel title="Items" flush>
            <Table head={['Product', 'Price', 'Qty', 'Total']} alignRight={[3]}>
              {o.items.map((i) => (
                <tr key={i.id}>
                  <Td>{i.product_name}</Td>
                  <Td className="num text-muted">{money(i.unit_price_cents)}</Td>
                  <Td className="num text-muted">{i.quantity}</Td>
                  <Td className="num text-right">{money(i.line_total_cents)}</Td>
                </tr>
              ))}
              {o.refunds.map((r) => (
                <tr key={`r${r.id}`} className="text-st-red">
                  <Td>
                    Refund, {label(r.reason).toLowerCase()}
                    {r.note && <span className="text-muted">: {r.note}</span>}
                    <div className="text-[12px] text-muted">{dateTime(r.created_at)}</div>
                  </Td>
                  <Td>{''}</Td>
                  <Td>{''}</Td>
                  <Td className="num text-right">−{money(r.amount_cents)}</Td>
                </tr>
              ))}
              <tr>
                <Td className="font-semibold">Net total</Td>
                <Td>{''}</Td>
                <Td>{''}</Td>
                <Td className="num text-right font-semibold">{money(o.total_cents - o.refunded_cents)}</Td>
              </tr>
            </Table>
          </Panel>

          <div className="grid gap-5">
            <Panel title="Actions">
              <OrderActions order={o} />
            </Panel>
            <Panel title="Related tickets" flush>
              {tickets.isPending ? (
                <Loading rows={2} />
              ) : !tickets.data?.items.length ? (
                <Empty>No tickets about this order.</Empty>
              ) : (
                <ul className="divide-y divide-line">
                  {tickets.data.items.map((t) => (
                    <li key={t.id}>
                      <Link to={`/tickets/${t.id}`} className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-sunken">
                        <span className="min-w-0 truncate text-[13.5px]">{t.subject}</span>
                        <TicketBadge status={t.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </div>
      </div>
    </>
  )
}
