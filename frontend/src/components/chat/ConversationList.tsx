import { Link } from 'react-router-dom'
import { SquarePenIcon, Trash2Icon } from 'lucide-react'
import { cn } from 'cn'

import { useConversations, useDeleteConversation } from '@/api/hooks'
import type { ConversationSummary } from '@/api/types'
import { Button } from '@/components/ui/button'

const DAY = 86_400_000

// "Today", "Yesterday", ... like ChatGPT's sidebar. `list` is newest first.
function groupByDate(list: ConversationSummary[]): [string, ConversationSummary[]][] {
  const startOfToday = new Date().setHours(0, 0, 0, 0)
  const bucket = (iso: string) => {
    const t = new Date(iso).getTime()
    if (t >= startOfToday) return 'Today'
    if (t >= startOfToday - DAY) return 'Yesterday'
    if (t >= startOfToday - 7 * DAY) return 'Previous 7 days'
    if (t >= startOfToday - 30 * DAY) return 'Previous 30 days'
    return 'Older'
  }
  const groups = new Map<string, ConversationSummary[]>()
  for (const c of list) {
    const key = bucket(c.updated_at)
    groups.set(key, [...(groups.get(key) ?? []), c])
  }
  return [...groups]
}

export function ConversationList({
  activeId,
  onNavigate,
  onDeleted,
}: {
  activeId: number | null
  onNavigate?: () => void
  onDeleted: (id: number) => void
}) {
  const { data, isLoading, error } = useConversations()
  const del = useDeleteConversation()

  return (
    <div className="flex h-full flex-col">
      <div className="p-3">
        <Button
          variant="outline"
          className="h-9 w-full justify-start gap-2 bg-surface text-[14px]"
          nativeButton={false}
          render={<Link to="/assistant" onClick={onNavigate} />}
        >
          <SquarePenIcon />
          New chat
        </Button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-3 pb-4" aria-label="Conversations">
        {isLoading && <p className="px-2 py-1 text-[13px] text-muted-foreground">Loading…</p>}
        {error && <p className="px-2 py-1 text-[13px] text-danger">{(error as Error).message}</p>}
        {data?.length === 0 && <p className="px-2 py-1 text-[13px] text-muted-foreground">No conversations yet.</p>}

        {groupByDate(data ?? []).map(([label, items]) => (
          <section key={label} className="mt-3 first:mt-0">
            <h3 className="px-2 pb-1 text-[12px] font-medium text-faint">{label}</h3>
            <ul className="flex flex-col gap-px">
              {items.map((c) => (
                <li key={c.id} className="group relative">
                  <Link
                    to={`/assistant/${c.id}`}
                    onClick={onNavigate}
                    aria-current={c.id === activeId ? 'page' : undefined}
                    title={c.title}
                    className={cn(
                      'block truncate rounded-lg py-1.5 pr-9 pl-2 text-[14px] transition-colors',
                      c.id === activeId ? 'bg-sunken font-medium text-ink' : 'text-ink/85 hover:bg-sunken',
                    )}
                  >
                    {c.title}
                  </Link>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Delete "${c.title}"`}
                    disabled={del.isPending}
                    onClick={() => {
                      if (!window.confirm('Delete this conversation?')) return
                      del.mutate(c.id, { onSuccess: () => onDeleted(c.id) })
                    }}
                    className="absolute top-1/2 right-1.5 -translate-y-1/2 text-faint opacity-0 group-hover:opacity-100 hover:bg-danger-wash hover:text-danger focus-visible:opacity-100 [@media(hover:none)]:opacity-100"
                  >
                    <Trash2Icon />
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>
    </div>
  )
}
