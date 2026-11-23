import { Link } from 'react-router-dom'
import { BanIcon, FilePenLineIcon, ReceiptIcon } from 'lucide-react'

import { ApiError } from '@/api/client'
import { useAction, useDecideAction } from '@/api/hooks'
import type { ActionStatus, ChatAction } from '@/api/types'
import { Badge } from '@/components/ui'
import { Button } from '@/components/ui/button'

const ICONS = { create_refund: ReceiptIcon, cancel_order: BanIcon, draft_ticket_reply: FilePenLineIcon }

const STATUS: Record<ActionStatus, { tone: 'amber' | 'green' | 'slate' | 'red'; text: string }> = {
  pending: { tone: 'amber', text: 'Waiting for approval' },
  done: { tone: 'green', text: 'Done' },
  rejected: { tone: 'slate', text: 'Rejected' },
  failed: { tone: 'red', text: 'Failed' },
}

function Details({ action }: { action: ChatAction }) {
  const a = action.arguments
  if (action.kind === 'draft_ticket_reply') {
    return (
      <blockquote className="max-h-48 overflow-y-auto rounded-lg bg-sunken/60 px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap text-ink">
        {String(a.body)}
      </blockquote>
    )
  }
  if (action.kind === 'create_refund' && a.note) {
    return <p className="text-[13px] text-muted-foreground">Note: {String(a.note)}</p>
  }
  return null
}

/**
 * A change the assistant proposed (a refund, a cancellation, a ticket draft). Nothing happens until
 * someone clicks Approve; the backend then checks the store's rules again and runs it exactly once.
 */
export function ActionCard({ id }: { id: number }) {
  const q = useAction(id)
  const decide = useDecideAction()
  const action = q.data
  if (!action) {
    return q.isError ? null : <div className="h-28 animate-pulse rounded-xl border border-line bg-sunken/40" />
  }

  const Icon = ICONS[action.kind] ?? ReceiptIcon
  const status = STATUS[action.status]
  const ticketId = action.kind === 'draft_ticket_reply' ? Number(action.arguments.ticket_id) : null
  return (
    <section className="my-3 flex flex-col gap-3 rounded-xl border border-line bg-surface p-4" aria-label="Proposed action">
      <header className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-cobalt-wash text-cobalt">
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-[14px] font-semibold text-ink">{action.summary}</p>
          <div>
            <Badge tone={status.tone}>{status.text}</Badge>
          </div>
        </div>
      </header>
      <Details action={action} />
      {action.outcome && (
        <p className={action.status === 'failed' ? 'text-[13px] text-danger' : 'text-[13px] text-muted-foreground'}>
          {action.outcome}
          {action.status === 'done' && ticketId !== null && (
            <>
              {' '}
              <Link to={`/tickets/${ticketId}`} className="text-cobalt hover:underline">
                Open ticket #{ticketId}
              </Link>
            </>
          )}
        </p>
      )}
      {action.status === 'pending' && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ id, approve: true })}>
            Approve
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={decide.isPending}
            onClick={() => decide.mutate({ id, approve: false })}
          >
            Reject
          </Button>
          <span className="text-[12px] text-muted-foreground">Nothing changes until you approve.</span>
        </div>
      )}
      {decide.error && (
        <p className="text-[13px] text-danger">
          {decide.error instanceof ApiError ? decide.error.message : 'That didn’t work. Please try again.'}
        </p>
      )}
    </section>
  )
}
