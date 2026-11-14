import { useState } from 'react'

import { useSeed } from '../api/hooks'
import type { SeedRequest } from '../api/types'
import { Button, Field, Input, MutationError, PageHeader, Panel } from '../components/ui'

const DEFAULTS: SeedRequest = { seed: 42, customers: 60, products: 40, orders: 250, tickets: 60, reset: true }

const FIELDS: { key: keyof Omit<SeedRequest, 'reset'>; label: string; max: number }[] = [
  { key: 'seed', label: 'Seed', max: 2_147_483_647 },
  { key: 'customers', label: 'Customers', max: 5000 },
  { key: 'products', label: 'Products', max: 2000 },
  { key: 'orders', label: 'Orders', max: 20000 },
  { key: 'tickets', label: 'Tickets', max: 5000 },
]

export function TestData() {
  const seed = useSeed()
  const [form, setForm] = useState(DEFAULTS)

  return (
    <>
      <PageHeader
        title="Test data"
        subtitle="Wipe the database and generate fresh data. The same seed always produces the same records."
      />
      <div className="grid items-start gap-5 lg:grid-cols-[1fr_1fr]">
        <Panel title="Generate">
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (confirm('This deletes all current data, including anything you changed. Continue?')) seed.mutate(form)
            }}
          >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {FIELDS.map((f) => (
                <Field key={f.key} label={f.label}>
                  <Input
                    type="number"
                    min={f.key === 'seed' ? 0 : 1}
                    max={f.max}
                    value={form[f.key]}
                    onChange={(e) => setForm({ ...form, [f.key]: Number(e.target.value) })}
                    className="num"
                  />
                </Field>
              ))}
            </div>
            <MutationError error={seed.error} />
            <div className="flex gap-2">
              <Button type="submit" variant="primary" disabled={seed.isPending}>
                {seed.isPending ? 'Generating…' : 'Wipe and generate'}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setForm(DEFAULTS)}>
                Reset to defaults
              </Button>
            </div>
          </form>
        </Panel>

        <Panel title={seed.data ? `Generated with seed ${seed.data.seed}` : 'Built-in scenarios'}>
          {seed.data && (
            <p className="num mb-3 text-[14px]">
              {seed.data.customers} customers, {seed.data.products} products, {seed.data.orders} orders,{' '}
              {seed.data.tickets} tickets and {seed.data.refunds} refunds.
            </p>
          )}
          <p className="mb-3 text-[14px] text-muted">
            Every dataset starts with these support cases. Each has one correct resolution, so they make good test
            cases for an AI agent.
          </p>
          <ul className="flex flex-col gap-2 text-[13.5px]">
            {(seed.data?.scenarios ?? SCENARIOS).map((s) => {
              const [name, rest] = s.split(/:(.*)/s)
              return (
                <li key={s} className="rounded-md border border-line px-3 py-2">
                  <div className="font-medium">{name.replace(/_/g, ' ')}</div>
                  <div className="text-muted">{rest?.trim()}</div>
                </li>
              )
            })}
          </ul>
        </Panel>
      </div>
    </>
  )
}

const SCENARIOS = [
  'damaged_item: priya.sharma@example.com, ORD-00000001 (delivered) -> refund headphones $199.99',
  'late_delivery: marcus.lee@example.com, ORD-00000002 (shipped 12 days ago, not delivered)',
  'partial_refund_limit: elena.garcia@example.com, ORD-00000003 -> only $199.99 left to refund',
  'cancel_request: james.okafor@example.com, ORD-00000004 (paid, not shipped) -> cancel',
  'out_of_stock_question: james.okafor@example.com asks about SCN-0003 (stock 0)',
]
