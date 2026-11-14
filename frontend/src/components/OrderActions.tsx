import { useState } from 'react'

import { useAdvanceOrder, useCancelOrder, useRefundOrder } from '../api/hooks'
import type { Order, OrderStatus, RefundReason } from '../api/types'
import { REFUND_REASONS } from '../api/types'
import { money, parseMoney } from '../lib/format'
import { Button, Field, Input, MutationError, Select } from './ui'

const NEXT: Partial<Record<OrderStatus, { to: OrderStatus; verb: string }>> = {
  pending: { to: 'paid', verb: 'Mark as paid' },
  paid: { to: 'shipped', verb: 'Mark as shipped' },
  shipped: { to: 'delivered', verb: 'Mark as delivered' },
}

const CAN_CANCEL: OrderStatus[] = ['pending', 'paid']
const CAN_REFUND: OrderStatus[] = ['paid', 'shipped', 'delivered']

export function OrderActions({ order }: { order: Order }) {
  const advance = useAdvanceOrder()
  const cancel = useCancelOrder()
  const [refunding, setRefunding] = useState(false)
  const next = NEXT[order.status]
  const canCancel = CAN_CANCEL.includes(order.status)
  const canRefund = CAN_REFUND.includes(order.status) && order.refundable_cents > 0

  if (!next && !canCancel && !canRefund) {
    return <p className="text-[13px] text-muted">No actions available for a {order.status} order.</p>
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {next && (
          <Button
            variant="secondary"
            disabled={advance.isPending}
            onClick={() => advance.mutate({ id: order.id, status: next.to })}
          >
            {next.verb}
          </Button>
        )}
        {canRefund && !refunding && (
          <Button variant="secondary" onClick={() => setRefunding(true)}>
            Issue refund
          </Button>
        )}
        {canCancel && (
          <Button
            variant="danger"
            disabled={cancel.isPending}
            onClick={() => {
              if (confirm(`Cancel ${order.number}? Items go back into stock.`)) cancel.mutate(order.id)
            }}
          >
            Cancel order
          </Button>
        )}
      </div>
      <MutationError error={advance.error || cancel.error} />
      {refunding && <RefundForm order={order} onDone={() => setRefunding(false)} />}
    </div>
  )
}

function RefundForm({ order, onDone }: { order: Order; onDone: () => void }) {
  const refund = useRefundOrder()
  const [amount, setAmount] = useState((order.refundable_cents / 100).toFixed(2))
  const [reason, setReason] = useState<RefundReason | ''>('')
  const [note, setNote] = useState('')
  const cents = parseMoney(amount)

  const amountError =
    cents === null
      ? 'Enter an amount like 19.99'
      : cents <= 0
        ? 'Amount must be more than zero'
        : cents > order.refundable_cents
          ? `At most ${money(order.refundable_cents)} can be refunded`
          : undefined

  return (
    <form
      className="flex flex-col gap-3 rounded-md border border-line bg-sunken p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (amountError || !reason || cents === null) return
        refund.mutate({ id: order.id, amount_cents: cents, reason, note }, { onSuccess: onDone })
      }}
    >
      <div className="text-[13px] text-muted">
        {money(order.refundable_cents)} of {money(order.total_cents)} can still be refunded.
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Amount (USD)" error={amount ? amountError : undefined}>
          <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="num" />
        </Field>
        <Field label="Reason">
          <Select<RefundReason> value={reason} onChange={setReason} options={REFUND_REASONS} placeholder="Choose a reason" required />
        </Field>
      </div>
      <Field label="Note for the record">
        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional" maxLength={500} />
      </Field>
      <MutationError error={refund.error} />
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={!!amountError || !reason || refund.isPending}>
          {refund.isPending ? 'Refunding…' : `Refund ${cents && !amountError ? money(cents) : ''}`}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
