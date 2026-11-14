import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError } from '../api/client'
import { useCreateCustomer, useCustomer, useCustomerOrders, useCustomerTickets, useCustomers } from '../api/hooks'
import type { CustomerTier } from '../api/types'
import { CUSTOMER_TIERS } from '../api/types'
import { SearchInput } from '../components/SearchInput'
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  FilterBar,
  Input,
  Loading,
  MutationError,
  OrderBadge,
  PageHeader,
  Pagination,
  Panel,
  Select,
  Table,
  Td,
  TicketBadge,
} from '../components/ui'
import { date, label, money, relative } from '../lib/format'
import { useUrlFilters } from '../lib/useUrlFilters'

const TierBadge = ({ tier }: { tier: CustomerTier }) =>
  tier === 'standard' ? (
    <span className="text-[13px] text-muted">Standard</span>
  ) : (
    <Badge tone={tier === 'platinum' ? 'violet' : 'amber'}>{label(tier)}</Badge>
  )

export function Customers() {
  const { values, page, set, setPage } = useUrlFilters(['q', 'tier'] as const)
  const [adding, setAdding] = useState(false)
  const navigate = useNavigate()
  const q = useCustomers({ q: values.q, tier: values.tier, page, page_size: 20 })

  return (
    <>
      <PageHeader
        title="Customers"
        subtitle="Everyone who has an account with the store."
        actions={
          !adding && (
            <Button variant="primary" onClick={() => setAdding(true)}>
              Add customer
            </Button>
          )
        }
      />
      {adding && <NewCustomer onDone={() => setAdding(false)} />}

      <FilterBar>
        <SearchInput value={values.q} onChange={(v) => set('q', v)} placeholder="Search name or email" />
        <Select<CustomerTier>
          value={values.tier as CustomerTier | ''}
          onChange={(v) => set('tier', v)}
          options={CUSTOMER_TIERS}
          placeholder="Any tier"
          aria-label="Tier"
        />
      </FilterBar>

      <Panel flush>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data.items.length === 0 ? (
          <Empty>No customers match. Try part of a name or email.</Empty>
        ) : (
          <>
            <Table head={['Name', 'Email', 'Location', 'Tier', 'Joined']}>
              {q.data.items.map((c) => (
                <tr key={c.id} onClick={() => navigate(`/customers/${c.id}`)} className="cursor-pointer hover:bg-sunken">
                  <Td>
                    <Link to={`/customers/${c.id}`} className="font-medium hover:text-cobalt">
                      {c.name}
                    </Link>
                  </Td>
                  <Td className="text-muted">{c.email}</Td>
                  <Td className="text-muted">{[c.city, c.country].filter(Boolean).join(', ')}</Td>
                  <Td>
                    <TierBadge tier={c.tier} />
                  </Td>
                  <Td className="whitespace-nowrap text-muted">{date(c.created_at)}</Td>
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

function NewCustomer({ onDone }: { onDone: () => void }) {
  const create = useCreateCustomer()
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', city: '', country: '', tier: 'standard' as CustomerTier })
  const errors = create.error instanceof ApiError ? create.error.fieldErrors : {}
  const up = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value })

  return (
    <Panel title="New customer" className="mb-5">
      <form
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate(
            { ...form, city: form.city || null, country: form.country || null },
            { onSuccess: (c) => navigate(`/customers/${c.id}`) },
          )
        }}
      >
        <Field label="Name" error={errors.name}>
          <Input value={form.name} onChange={up('name')} required />
        </Field>
        <Field label="Email" error={errors.email}>
          <Input type="email" value={form.email} onChange={up('email')} required />
        </Field>
        <Field label="City">
          <Input value={form.city} onChange={up('city')} />
        </Field>
        <Field label="Country">
          <Input value={form.country} onChange={up('country')} />
        </Field>
        <Field label="Tier">
          <Select<CustomerTier> value={form.tier} options={CUSTOMER_TIERS} onChange={(v) => v && setForm({ ...form, tier: v })} />
        </Field>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2 lg:col-span-5">
          <Button type="submit" variant="primary" disabled={create.isPending}>
            Add customer
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
          {!Object.keys(errors).length && <MutationError error={create.error} />}
        </div>
      </form>
    </Panel>
  )
}

export function CustomerDetail() {
  const id = Number(useParams().id)
  const q = useCustomer(id)
  const [orderPage, setOrderPage] = useState(1)
  const orders = useCustomerOrders(id, { page: orderPage, page_size: 8 })
  const tickets = useCustomerTickets(id, { page_size: 8 })

  if (q.isPending) return <Panel><Loading /></Panel>
  if (q.isError) return <Panel><ErrorState error={q.error} onRetry={() => q.refetch()} /></Panel>
  const c = q.data

  return (
    <>
      <Link to="/customers" className="mb-3 inline-block text-[13px] text-muted hover:text-ink">
        All customers
      </Link>
      <PageHeader
        title={c.name}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <TierBadge tier={c.tier} />
            <span>
              {c.email}
              {c.city && `, ${[c.city, c.country].filter(Boolean).join(', ')}`}
            </span>
          </span>
        }
      />

      <Panel className="mb-5">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            ['Lifetime value', money(c.lifetime_value_cents)],
            ['Orders', String(c.order_count)],
            ['Open tickets', String(c.open_ticket_count)],
            ['Customer since', date(c.created_at)],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[13px] text-muted">{k}</dt>
              <dd className="num text-[20px] font-semibold">{v}</dd>
            </div>
          ))}
        </dl>
      </Panel>

      <div className="grid items-start gap-5 lg:grid-cols-[1fr_1fr]">
        <Panel title="Orders" flush>
          {orders.isPending ? (
            <Loading rows={4} />
          ) : orders.isError ? (
            <ErrorState error={orders.error} />
          ) : orders.data.items.length === 0 ? (
            <Empty>No orders yet.</Empty>
          ) : (
            <>
              <ul className="divide-y divide-line">
                {orders.data.items.map((o) => (
                  <li key={o.id}>
                    <Link to={`/orders/${o.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-sunken">
                      <span className="font-mono text-[12.5px]">{o.number}</span>
                      <OrderBadge status={o.status} />
                      <span className="ml-auto text-[12.5px] text-muted">{date(o.placed_at)}</span>
                      <span className="num w-20 text-right text-[13.5px] font-medium">{money(o.total_cents)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
              {orders.data.pages > 1 && (
                <Pagination page={orders.data.page} pages={orders.data.pages} total={orders.data.total} onPage={setOrderPage} />
              )}
            </>
          )}
        </Panel>

        <Panel title="Tickets" flush>
          {tickets.isPending ? (
            <Loading rows={4} />
          ) : tickets.isError ? (
            <ErrorState error={tickets.error} />
          ) : tickets.data.items.length === 0 ? (
            <Empty>{c.name.split(' ')[0]} hasn't contacted support.</Empty>
          ) : (
            <ul className="divide-y divide-line">
              {tickets.data.items.map((t) => (
                <li key={t.id}>
                  <Link to={`/tickets/${t.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-sunken">
                    <span className="min-w-0 flex-1 truncate text-[13.5px]">{t.subject}</span>
                    <TicketBadge status={t.status} />
                    <span className="w-16 text-right text-[12px] text-muted">{relative(t.created_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  )
}
