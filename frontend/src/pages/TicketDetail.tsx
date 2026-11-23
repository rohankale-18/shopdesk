import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { MessageCircleIcon } from 'lucide-react'

import { useOrder, useReplyToTicket, useTicket, useUpdateTicket } from '../api/hooks'
import type { Ticket, TicketPriority, TicketStatus } from '../api/types'
import { TICKET_PRIORITIES, TICKET_STATUSES } from '../api/types'
import { LifecycleTrack } from '../components/LifecycleTrack'
import { OrderActions } from '../components/OrderActions'
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Loading,
  MutationError,
  OrderBadge,
  PageHeader,
  Panel,
  Select,
  TicketBadge,
  cx,
} from '../components/ui'
import { dateTime, label, money, relative } from '../lib/format'

const ASSIGNEES = ['asha', 'ben', 'chen', 'dana'] as const

export function TicketDetail() {
  const id = Number(useParams().id)
  const q = useTicket(id)
  const navigate = useNavigate()

  if (q.isPending) return <Panel><Loading /></Panel>
  if (q.isError) return <Panel><ErrorState error={q.error} onRetry={() => q.refetch()} /></Panel>
  const t = q.data

  return (
    <>
      <Link to="/tickets" className="mb-3 inline-block text-[13px] text-muted-foreground hover:text-ink">
        All tickets
      </Link>
      <PageHeader
        title={t.subject}
        actions={
          <Button onClick={() => navigate(`/assistant?ticket=${t.id}`)}>
            <MessageCircleIcon className="size-4" aria-hidden />
            Ask about this ticket
          </Button>
        }
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <TicketBadge status={t.status} />
            <span>
              #{t.id} in {label(t.category)}, opened {relative(t.created_at)}
            </span>
          </span>
        }
      />

      <div className="grid items-start gap-5 lg:grid-cols-[1fr_360px]">
        <div className="grid gap-5">
          <Thread ticket={t} />
          {/* Keyed on the draft, so a newly approved assistant draft replaces what's in the box. */}
          <Reply key={t.draft_reply ?? ''} ticket={t} />
        </div>
        <aside className="grid gap-5">
          <TicketSettings ticket={t} />
          <CustomerPanel ticket={t} />
          {t.order_id && <LinkedOrder orderId={t.order_id} />}
        </aside>
      </div>
    </>
  )
}

function Thread({ ticket }: { ticket: Ticket }) {
  return (
    <Panel title="Conversation" flush>
      <ol className="divide-y divide-line">
        {ticket.messages.map((m) => {
          const isCustomer = m.author === 'customer'
          return (
            <li key={m.id} className={cx('px-4 py-3.5', !isCustomer && 'bg-cobalt-wash/40')}>
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <span className="text-[13.5px] font-semibold">
                  {isCustomer ? ticket.customer.name : m.author === 'agent' ? 'Support' : 'System'}
                </span>
                <time className="text-[12px] text-muted-foreground" dateTime={m.created_at}>
                  {dateTime(m.created_at)}
                </time>
              </div>
              <p className="max-w-[70ch] text-[14.5px] leading-relaxed whitespace-pre-wrap">{m.body}</p>
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}

function Reply({ ticket }: { ticket: Ticket }) {
  const [body, setBody] = useState(ticket.draft_reply ?? '')
  const reply = useReplyToTicket()
  const update = useUpdateTicket()
  const closed = ticket.status === 'closed'
  const fromAssistant = ticket.draft_reply !== null
  // The assistant writes "[refund decision]" where a person has to decide what to say.
  const placeholders = body.match(/\[[^\]\n]+\]/g) ?? []

  const send = (thenStatus?: TicketStatus) =>
    reply.mutate(
      { id: ticket.id, body: body.trim() },
      {
        onSuccess: () => {
          setBody('')
          if (thenStatus) update.mutate({ id: ticket.id, status: thenStatus })
        },
      },
    )

  if (closed) {
    return (
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[14px] text-muted-foreground">This ticket is closed. Reopen it to reply.</p>
          <Button onClick={() => update.mutate({ id: ticket.id, status: 'open' })}>Reopen ticket</Button>
        </div>
      </Panel>
    )
  }

  return (
    <Panel title="Reply">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (body.trim()) send()
        }}
        className="flex flex-col gap-3"
      >
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={5}
          placeholder={`Write to ${ticket.customer.name.split(' ')[0]}…`}
          aria-label="Reply"
          className="w-full resize-y rounded-md border border-line bg-surface p-3 text-[14px] leading-relaxed placeholder:text-faint focus:border-cobalt focus:outline-none"
        />
        {fromAssistant && (
          <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted-foreground">
            <span>
              Drafted by the assistant. Check it before sending.
              {placeholders.length > 0 && (
                <span className="text-danger"> Still to fill in: {placeholders.join(', ')}</span>
              )}
            </span>
            <Button type="button" onClick={() => update.mutate({ id: ticket.id, draft_reply: null })}>
              Discard draft
            </Button>
          </div>
        )}
        <MutationError error={reply.error} />
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="primary" disabled={!body.trim() || reply.isPending}>
            Send reply
          </Button>
          <Button type="button" disabled={!body.trim() || reply.isPending} onClick={() => send('pending')}>
            Send and wait for customer
          </Button>
          <Button type="button" disabled={!body.trim() || reply.isPending} onClick={() => send('resolved')}>
            Send and resolve
          </Button>
        </div>
      </form>
    </Panel>
  )
}

function TicketSettings({ ticket }: { ticket: Ticket }) {
  const update = useUpdateTicket()
  return (
    <Panel title="Ticket">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Status">
          <Select<TicketStatus>
            value={ticket.status}
            options={TICKET_STATUSES}
            onChange={(v) => v && update.mutate({ id: ticket.id, status: v })}
          />
        </Field>
        <Field label="Priority">
          <Select<TicketPriority>
            value={ticket.priority}
            options={TICKET_PRIORITIES}
            onChange={(v) => v && update.mutate({ id: ticket.id, priority: v })}
          />
        </Field>
        <div className="col-span-2">
          <Field label="Assignee">
            <Select
              value={(ticket.assignee ?? '') as (typeof ASSIGNEES)[number] | ''}
              options={ASSIGNEES}
              placeholder="Unassigned"
              onChange={(v) => update.mutate({ id: ticket.id, assignee: v || null })}
            />
          </Field>
        </div>
      </div>
      <div className="mt-2">
        <MutationError error={update.error} />
      </div>
    </Panel>
  )
}

function CustomerPanel({ ticket }: { ticket: Ticket }) {
  const c = ticket.customer
  return (
    <Panel
      title="Customer"
      actions={
        <Link to={`/customers/${c.id}`} className="text-[13px] font-medium text-cobalt hover:underline">
          Profile
        </Link>
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium">{c.name}</div>
          <div className="truncate text-[13px] text-muted-foreground">{c.email}</div>
          {(c.city || c.country) && (
            <div className="text-[13px] text-muted-foreground">{[c.city, c.country].filter(Boolean).join(', ')}</div>
          )}
        </div>
        {c.tier !== 'standard' && <Badge tone={c.tier === 'platinum' ? 'violet' : 'amber'}>{label(c.tier)}</Badge>}
      </div>
    </Panel>
  )
}

function LinkedOrder({ orderId }: { orderId: number }) {
  const q = useOrder(orderId)
  return (
    <Panel
      title="Order"
      actions={
        q.data && (
          <Link to={`/orders/${q.data.id}`} className="font-mono text-[12.5px] text-cobalt hover:underline">
            {q.data.number}
          </Link>
        )
      }
    >
      {q.isPending ? (
        <Loading rows={3} />
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <OrderBadge status={q.data.status} />
            <span className="num font-semibold">{money(q.data.total_cents)}</span>
          </div>
          <LifecycleTrack order={q.data} compact />
          <ul className="flex flex-col gap-1 border-t border-line pt-3 text-[13px]">
            {q.data.items.map((i) => (
              <li key={i.id} className="flex justify-between gap-3">
                <span className="min-w-0 truncate">
                  {i.quantity} × {i.product_name}
                </span>
                <span className="num shrink-0 text-muted-foreground">{money(i.line_total_cents)}</span>
              </li>
            ))}
            {q.data.refunded_cents > 0 && (
              <li className="flex justify-between gap-3 text-st-red">
                <span>Refunded</span>
                <span className="num">−{money(q.data.refunded_cents)}</span>
              </li>
            )}
          </ul>
          <OrderActions order={q.data} />
        </div>
      )}
    </Panel>
  )
}
