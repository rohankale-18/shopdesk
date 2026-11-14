import { useNavigate } from 'react-router-dom'

import { useTickets } from '../api/hooks'
import type { TicketCategory, TicketPriority } from '../api/types'
import { TICKET_CATEGORIES, TICKET_PRIORITIES, TICKET_STATUSES } from '../api/types'
import { SearchInput } from '../components/SearchInput'
import {
  Empty,
  ErrorState,
  FilterBar,
  Loading,
  PageHeader,
  Pagination,
  Panel,
  Priority,
  Select,
  Table,
  Td,
  TicketBadge,
  cx,
} from '../components/ui'
import { label, relative } from '../lib/format'
import { useUrlFilters } from '../lib/useUrlFilters'

export function Tickets() {
  const { values, page, set, setPage } = useUrlFilters(['q', 'status', 'priority', 'category'] as const)
  const navigate = useNavigate()
  const q = useTickets({
    q: values.q,
    status: values.status ? [values.status] : undefined,
    priority: values.priority ? [values.priority] : undefined,
    category: values.category,
    page,
    page_size: 20,
  })

  return (
    <>
      <PageHeader title="Tickets" subtitle="Customer conversations, newest first." />

      <div className="mb-3 flex gap-1 overflow-x-auto border-b border-line" role="tablist" aria-label="Ticket status">
        {['', ...TICKET_STATUSES].map((s) => (
          <button
            key={s || 'all'}
            role="tab"
            aria-selected={values.status === s}
            onClick={() => set('status', s)}
            className={cx(
              '-mb-px cursor-pointer border-b-2 px-3 py-2 text-[14px] whitespace-nowrap',
              values.status === s ? 'border-cobalt font-semibold text-ink' : 'border-transparent text-muted-foreground hover:text-ink',
            )}
          >
            {s ? label(s) : 'All'}
          </button>
        ))}
      </div>

      <FilterBar>
        <SearchInput value={values.q} onChange={(v) => set('q', v)} placeholder="Search subjects" />
        <Select<TicketPriority>
          value={values.priority as TicketPriority | ''}
          onChange={(v) => set('priority', v)}
          options={TICKET_PRIORITIES}
          placeholder="Any priority"
          aria-label="Priority"
        />
        <Select<TicketCategory>
          value={values.category as TicketCategory | ''}
          onChange={(v) => set('category', v)}
          options={TICKET_CATEGORIES}
          placeholder="Any category"
          aria-label="Category"
        />
      </FilterBar>

      <Panel flush>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data.items.length === 0 ? (
          <Empty>No tickets match these filters.</Empty>
        ) : (
          <>
            <Table head={['Priority', 'Subject', 'Status', 'Assignee', 'Updated']}>
              {q.data.items.map((t) => (
                <tr
                  key={t.id}
                  onClick={() => navigate(`/tickets/${t.id}`)}
                  className="cursor-pointer hover:bg-sunken"
                >
                  <Td className="w-[120px]">
                    <Priority value={t.priority} />
                  </Td>
                  <Td>
                    <a
                      href={`/tickets/${t.id}`}
                      onClick={(e) => {
                        e.preventDefault()
                        navigate(`/tickets/${t.id}`)
                      }}
                      className="font-medium hover:text-cobalt"
                    >
                      {t.subject}
                    </a>
                    <div className="text-[12.5px] text-muted-foreground">
                      #{t.id} in {label(t.category)}
                    </div>
                  </Td>
                  <Td>
                    <TicketBadge status={t.status} />
                  </Td>
                  <Td className="text-muted-foreground">{t.assignee ? label(t.assignee) : 'Unassigned'}</Td>
                  <Td className="whitespace-nowrap text-muted-foreground">{relative(t.updated_at)}</Td>
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
