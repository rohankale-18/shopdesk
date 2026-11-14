import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PanelLeftIcon, SquarePenIcon } from 'lucide-react'
import { cn } from 'cn'

import { ApiError } from '@/api/client'
import { useAIStatus, useConversation, useCreateConversation, useSendChatMessage } from '@/api/hooks'
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
  { title: 'Escalation rules', prompt: 'When should a support ticket be escalated, and to whom?' },
]

// The message being answered right now and the reply so far. `savedId` is set once both are saved.
type Turn = { conversationId: number | null; content: string; reply: string; savedId?: number }

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

  const [sidebarOpen, setSidebarOpen] = useState(readSidebarPref) // desktop
  const [drawerOpen, setDrawerOpen] = useState(false) // mobile
  const [draft, setDraft] = useState('')
  const [turn, setTurn] = useState<Turn | null>(null)
  // Errors belong to the conversation they happened in.
  const [error, setError] = useState<{ conversationId: number | null; error: unknown } | null>(null)

  const status = useAIStatus()
  const convo = useConversation(activeId)
  const create = useCreateConversation()
  const send = useSendChatMessage()

  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const messages = convo.data?.messages ?? []
  const aiOff = status.data?.enabled === false
  const busy = turn !== null && turn.savedId === undefined
  // Draw the live turn in its own conversation until the saved copy arrives (no flicker).
  const liveTurn =
    turn && turn.conversationId === activeId && !messages.some((m) => m.id === turn.savedId) ? turn : null
  const notFound = convo.error instanceof ApiError && convo.error.status === 404
  const isEmpty = !activeId && !liveTurn

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
    setTurn({ conversationId: id, content, reply: '' })
    setDraft('')
    setError(null)
    try {
      if (!id) {
        id = (await create.mutateAsync()).id
        const newId = id
        setTurn((t) => t && { ...t, conversationId: newId })
        navigate(`/assistant/${id}`, { replace: true })
      }
      const result = await send(id, content, {
        onDelta: (piece) => setTurn((t) => t && { ...t, reply: t.reply + piece }),
        signal: controller.signal,
      })
      setTurn((t) => t && { ...t, savedId: result.assistant_message.id })
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
                  <h2 className="text-[26px] font-semibold tracking-tight">How can I help with support today?</h2>
                  <p className="mt-2 text-[14px] text-muted-foreground">
                    Draft replies, handle tricky cases, or check support best practices.
                  </p>
                </div>
                {notices}
                {composer}
                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
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
                  // key: a fresh scroller per conversation, so each one opens at its latest message
                  <MessageScrollerProvider key={activeId ?? 'new'} autoScroll defaultScrollPosition="end">
                    <MessageScroller>
                      <MessageScrollerViewport>
                        <MessageScrollerContent className="mx-auto w-full max-w-3xl gap-8 px-4 pt-6 pb-10">
                          {messages.map((m) => (
                            <MessageScrollerItem key={m.id} messageId={String(m.id)} scrollAnchor={m.role === 'user'}>
                              {m.role === 'user' ? (
                                <UserMessage content={m.content} />
                              ) : (
                                <AssistantMessage content={m.content} />
                              )}
                            </MessageScrollerItem>
                          ))}
                          {liveTurn && (
                            <>
                              <MessageScrollerItem messageId="live-user" scrollAnchor>
                                <UserMessage content={liveTurn.content} />
                              </MessageScrollerItem>
                              <MessageScrollerItem messageId="live-reply">
                                {liveTurn.reply ? <AssistantMessage content={liveTurn.reply} streaming /> : <Typing />}
                              </MessageScrollerItem>
                            </>
                          )}
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
