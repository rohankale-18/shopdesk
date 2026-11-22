import { startTransition, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { PanelLeftIcon, SquarePenIcon, TicketIcon, XIcon } from 'lucide-react'
import { cn } from 'cn'

import { ApiError } from '@/api/client'
import type { ToolUse } from '@/api/types'
import { useAIStatus, useConversation, useCreateConversation, useSendChatMessage, useTicket } from '@/api/hooks'
import { AssistantMark, AssistantMessage, Typing, UserMessage } from '@/components/chat/ChatMessages'
import { preloadMarkdown } from '@/components/chat/lazyMarkdown'
import { Composer } from '@/components/chat/Composer'
import { ConversationList } from '@/components/chat/ConversationList'
import { Button } from '@/components/ui/button'
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

const SIDEBAR_KEY = 'shopdesk.chat.sidebar'

const SUGGESTIONS = [
  { title: 'Draft an apology', prompt: 'Draft a polite apology for a delivery that is running late' },
  { title: 'Handle a damaged item', prompt: 'How should I respond to a customer asking for a refund on a damaged item?' },
  { title: 'Soften a message', prompt: 'Rewrite this to sound friendlier: "Your request has been denied."' },
  { title: 'Store overview', prompt: 'How are we doing this month?' },
]

// A chat opened from a ticket page ("Ask about this ticket").
const TICKET_SUGGESTIONS = [
  { title: 'What do they want?', prompt: 'What does this customer want?' },
  { title: 'Suggest a reply', prompt: 'Suggest a reply to this ticket' },
  { title: 'Check the order', prompt: 'Is there a problem with the order?' },
  { title: 'Next step', prompt: 'What should I do next on this ticket?' },
]

/**
 * The ticket a chat is about. Above the composer while it's waiting to be sent (removable), then
 * above the first message, like an attachment. Its current data goes to the model with every
 * message (the backend's page context), so follow-ups keep it too.
 */
function TicketContext({ id, onRemove, attached }: { id: number; onRemove?: () => void; attached?: boolean }) {
  const ticket = useTicket(id)
  const missing = ticket.error instanceof ApiError && ticket.error.status === 404
  return (
    <div
      className={cn(
        'flex items-center gap-2 border border-line bg-sunken/60 px-3 py-2 text-[13px]',
        attached ? 'ml-auto w-fit max-w-[80%] rounded-2xl' : 'mb-2 rounded-xl',
      )}
    >
      <TicketIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1 truncate">
        <span className="text-muted-foreground">About </span>
        <Link to={`/tickets/${id}`} className="font-medium text-cobalt hover:underline">
          ticket #{id}
        </Link>
        {ticket.data && <span className="text-muted-foreground">: {ticket.data.subject}</span>}
        {missing && <span className="text-muted-foreground"> (no longer exists)</span>}
      </span>
      {onRemove && (
        <button
          type="button"
          aria-label="Don't attach this ticket"
          title="Don't attach this ticket"
          onClick={onRemove}
          className="cursor-pointer rounded p-0.5 text-muted-foreground hover:bg-sunken hover:text-ink"
        >
          <XIcon className="size-3.5" />
        </button>
      )}
    </div>
  )
}

// The message being answered right now, the reply so far and the tools it ran.
// `key` names its two rows on screen; `savedId` is set once both messages are saved.
type Turn = {
  key: string
  conversationId: number | null
  content: string
  reply: string
  tools: ToolUse[]
  savedId?: number
}

function readSidebarPref(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) !== 'closed'
  } catch {
    return true
  }
}

function HeaderButton({ label, onClick, className, children }: {
  label: string
  onClick: () => void
  className?: string
  children: React.ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label={label}
            onClick={onClick}
            className={cn('text-muted-foreground', className)}
          >
            {children}
          </Button>
        }
      />
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}

export default function Assistant() {
  const params = useParams()
  const navigate = useNavigate()
  const activeId = params.id ? Number(params.id) : null
  const [searchParams] = useSearchParams()

  const [sidebarOpen, setSidebarOpen] = useState(readSidebarPref) // desktop
  const [drawerOpen, setDrawerOpen] = useState(false) // mobile
  const [draft, setDraft] = useState('')
  const [turn, setTurn] = useState<Turn | null>(null)
  // Saved messages that started as live rows keep the live row's key. A new key would make
  // React (and the scroller) treat them as new messages and jump.
  const [rowKeys, setRowKeys] = useState<Record<number, string>>({})
  // The conversation created by the first message of a new chat keeps the "new" scroller,
  // instead of replacing it when the URL changes.
  const [createdId, setCreatedId] = useState<number | null>(null)
  // Errors belong to the conversation they happened in.
  const [error, setError] = useState<{ conversationId: number | null; error: unknown } | null>(null)

  const status = useAIStatus()
  const convo = useConversation(activeId)
  const create = useCreateConversation()
  const send = useSendChatMessage()

  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // The ticket a new chat will be about (?ticket=12), or the one an existing chat is about.
  const newChatTicket = activeId ? null : Number(searchParams.get('ticket')) || null
  const ticketId = activeId ? (convo.data?.ticket_id ?? null) : newChatTicket
  const messages = convo.data?.messages ?? []
  const aiOff = status.data?.enabled === false
  const busy = turn !== null && turn.savedId === undefined
  // Draw the live turn in its own conversation until the saved copy arrives (no flicker).
  const liveTurn =
    turn && turn.conversationId === activeId && !messages.some((m) => m.id === turn.savedId) ? turn : null
  const notFound = convo.error instanceof ApiError && convo.error.status === 404
  const isEmpty = !activeId && !liveTurn
  // Saved and live messages in ONE list: React only matches keys within the same list, so this is
  // what lets a live row keep its element when the saved copy replaces it.
  // The first message carries the ticket, like an attached image.
  const sent = (content: string, first: boolean) =>
    first && ticketId ? (
      <div className="flex flex-col gap-1.5">
        <TicketContext id={ticketId} attached />
        <UserMessage content={content} />
      </div>
    ) : (
      <UserMessage content={content} />
    )
  const rows: { key: string; role: 'user' | 'assistant'; node: React.ReactNode }[] = messages.map((m, i) => ({
    key: rowKeys[m.id] ?? String(m.id),
    role: m.role,
    node:
      m.role === 'user' ? (
        sent(m.content, i === 0)
      ) : (
        <AssistantMessage content={m.content} tools={m.tool_calls} traceId={m.trace_id} />
      ),
  }))
  if (liveTurn) {
    rows.push(
      { key: `${liveTurn.key}-user`, role: 'user', node: sent(liveTurn.content, messages.length === 0) },
      {
        key: `${liveTurn.key}-reply`,
        role: 'assistant',
        node:
          // trim(): replies often start with a bare newline; keep the dots until real text arrives.
          liveTurn.reply.trim() || liveTurn.tools.length ? (
            <AssistantMessage content={liveTurn.reply} tools={liveTurn.tools} streaming />
          ) : (
            <Typing />
          ),
      },
    )
  }
  const lastUserKey = rows.findLast((r) => r.role === 'user')?.key

  // A fresh scroller per conversation, so each one opens at its latest message.
  const scrollerKey = activeId === null || activeId === createdId ? 'new' : String(activeId)

  useEffect(preloadMarkdown, [])

  useEffect(() => {
    inputRef.current?.focus()
  }, [activeId])

  function toggleSidebar() {
    if (window.matchMedia('(min-width: 768px)').matches) {
      setSidebarOpen((open) => {
        try {
          localStorage.setItem(SIDEBAR_KEY, open ? 'closed' : 'open')
        } catch {
          /* fine */
        }
        return !open
      })
    } else {
      setDrawerOpen((open) => !open)
    }
  }

  async function submit(text: string) {
    const content = text.trim()
    if (!content || busy || aiOff) return
    const controller = new AbortController()
    abortRef.current = controller
    let id = activeId
    const key = `turn-${Date.now()}`
    setTurn({ key, conversationId: id, content, reply: '', tools: [] })
    setDraft('')
    setError(null)
    try {
      if (!id) {
        const newId = (await create.mutateAsync(newChatTicket)).id
        id = newId
        // One render for all three (navigation alone would be a separate, later render).
        startTransition(() => {
          setCreatedId(newId)
          setTurn((t) => t && { ...t, conversationId: newId })
          navigate(`/assistant/${newId}`, { replace: true })
        })
      }
      await send(id, content, {
        onDelta: (piece) => setTurn((t) => t && { ...t, reply: t.reply + piece }),
        onTool: (tool) => setTurn((t) => t && { ...t, tools: [...t.tools, tool] }),
        onSaved: ({ user_message, assistant_message }) => {
          setRowKeys((k) => ({ ...k, [user_message.id]: `${key}-user`, [assistant_message.id]: `${key}-reply` }))
          setTurn((t) => t && { ...t, savedId: assistant_message.id })
        },
        signal: controller.signal,
      })
    } catch (e) {
      // Stopped or failed: nothing was saved. Give the text back so it can be retried.
      setTurn(null)
      setDraft(content)
      if (!controller.signal.aborted) setError({ conversationId: id, error: e })
    } finally {
      abortRef.current = null
    }
  }

  const shownError = error?.conversationId === activeId ? error.error : null
  const errorText =
    shownError instanceof ApiError
      ? shownError.message
      : shownError
        ? 'Something went wrong. Please try again.'
        : null

  const composer = (
    <Composer
      inputRef={inputRef}
      value={draft}
      onChange={setDraft}
      onSubmit={(v) => void submit(v)}
      onStop={() => abortRef.current?.abort()}
      busy={busy}
      disabled={aiOff}
    />
  )

  const notices = (
    <>
      {/* Only until it's sent: then it sits on the first message. */}
      {isEmpty && newChatTicket && <TicketContext id={newChatTicket} onRemove={() => navigate('/assistant')} />}
      {aiOff && (
        <p className="mb-3 rounded-xl border border-line bg-st-amber-wash px-4 py-2.5 text-[13px] text-st-amber">
          AI isn't configured. Set <code className="font-mono">GROQ_API_KEY</code> in{' '}
          <code className="font-mono">backend/.env</code> and restart the API.
        </p>
      )}
      {errorText && (
        <p role="alert" className="mb-3 rounded-xl bg-danger-wash px-4 py-2.5 text-[13px] text-danger">
          {errorText}
        </p>
      )}
    </>
  )

  const sidebar = (
    <ConversationList
      activeId={activeId}
      onNavigate={() => setDrawerOpen(false)}
      onDeleted={(id) => id === activeId && navigate('/assistant')}
    />
  )

  return (
    <TooltipProvider>
      {/* overflow-hidden: the collapsed sidebar slides out of view instead of over the app nav. */}
      <div className="relative flex h-full min-h-0 overflow-hidden">
        {/* Conversations: a column on desktop, a drawer on mobile. */}
        <aside
          className={cn(
            'hidden w-64 shrink-0 border-r border-line bg-paper transition-[margin] duration-200 md:block',
            !sidebarOpen && 'md:-ml-64',
          )}
          aria-hidden={!sidebarOpen}
          inert={!sidebarOpen}
        >
          {sidebar}
        </aside>
        {drawerOpen && (
          <div className="fixed inset-0 z-50 md:hidden">
            <button
              type="button"
              aria-label="Close conversations"
              className="absolute inset-0 bg-ink/30"
              onClick={() => setDrawerOpen(false)}
            />
            <div className="absolute inset-y-0 left-0 w-72 max-w-[85%] bg-paper shadow-xl">{sidebar}</div>
          </div>
        )}

        <section className="flex min-w-0 flex-1 flex-col bg-surface">
          <header className="flex h-14 shrink-0 items-center gap-1 px-2 md:px-3">
            <HeaderButton label={sidebarOpen ? 'Hide conversations' : 'Show conversations'} onClick={toggleSidebar}>
              <PanelLeftIcon />
            </HeaderButton>
            {/* The sidebar has its own New chat button; show this one when it's hidden (and on mobile). */}
            <HeaderButton label="New chat" onClick={() => navigate('/assistant')} className={cn(sidebarOpen && 'md:hidden')}>
              <SquarePenIcon />
            </HeaderButton>
            <h1 className="min-w-0 flex-1 truncate px-1 text-[15px] font-medium">
              {activeId ? (convo.data?.title ?? '') : 'New chat'}
            </h1>
            <span className="hidden items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[12px] text-muted-foreground sm:flex">
              <span className={cn('size-1.5 rounded-full', aiOff ? 'bg-danger' : 'bg-st-green')} aria-hidden />
              {status.data ? (aiOff ? 'Not configured' : status.data.model) : 'Checking…'}
            </span>
          </header>

          {notFound ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
              <p className="text-[15px] text-muted-foreground">This conversation doesn't exist or was deleted.</p>
              <Link to="/assistant" className="text-cobalt hover:underline">
                Start a new chat
              </Link>
            </div>
          ) : isEmpty ? (
            // New chat: greeting, composer and suggestions in the middle of the page.
            <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-[10vh]">
              <div className="w-full max-w-3xl">
                <div className="mb-8 flex flex-col items-center text-center">
                  <AssistantMark className="mb-4 size-12 [&_svg]:size-6" />
                  <h2 className="text-[26px] font-semibold tracking-tight">
                    {newChatTicket ? `What would you like to know about ticket #${newChatTicket}?` : 'How can I help with support today?'}
                  </h2>
                  <p className="mt-2 text-[14px] text-muted-foreground">
                    {newChatTicket
                      ? 'The ticket, its messages and its order go with every question.'
                      : 'Draft replies, handle tricky cases, or ask how the store is doing.'}
                  </p>
                </div>
                {notices}
                {composer}
                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  {(newChatTicket ? TICKET_SUGGESTIONS : SUGGESTIONS).map((s) => (
                    <button
                      key={s.title}
                      type="button"
                      disabled={aiOff}
                      onClick={() => void submit(s.prompt)}
                      className="cursor-pointer rounded-2xl border border-line px-4 py-3 text-left transition-colors hover:bg-sunken disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <div className="text-[14px] font-medium">{s.title}</div>
                      <div className="mt-0.5 line-clamp-1 text-[13px] text-muted-foreground">{s.prompt}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <>
              <div className="min-h-0 flex-1">
                {activeId && convo.isLoading ? (
                  <div className="mx-auto w-full max-w-3xl px-4 pt-8 text-[14px] text-muted-foreground">Loading…</div>
                ) : (
                  <MessageScrollerProvider key={scrollerKey} defaultScrollPosition="end">
                    <MessageScroller>
                      <MessageScrollerViewport>
                        <MessageScrollerContent className="mx-auto w-full max-w-3xl gap-8 px-4 pt-6 pb-10">
                          {rows.map((row) => (
                            // Only the latest question is a scroll anchor: the scroller pins it near the
                            // top. Older anchors would let it jump back to an earlier question.
                            <MessageScrollerItem key={row.key} messageId={row.key} scrollAnchor={row.key === lastUserKey}>
                              {row.node}
                            </MessageScrollerItem>
                          ))}
                        </MessageScrollerContent>
                      </MessageScrollerViewport>
                      <MessageScrollerButton className="rounded-full shadow-sm" />
                    </MessageScroller>
                  </MessageScrollerProvider>
                )}
              </div>
              <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-3">
                {notices}
                {composer}
                <p className="mt-2 text-center text-[12px] text-faint">AI can make mistakes. Check important details.</p>
              </div>
            </>
          )}
        </section>
      </div>
    </TooltipProvider>
  )
}
