import { Suspense, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ActivityIcon, CheckIcon, CopyIcon, DatabaseIcon, SparklesIcon } from 'lucide-react'
import { cn } from 'cn'

import type { ToolUse } from '@/api/types'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { Button } from '@/components/ui/button'
import { Message, MessageContent, MessageFooter } from '@/components/ui/message'

import { ActionCard } from './ActionCard'
import { ChatMarkdown } from './lazyMarkdown'

export function AssistantMark({ className }: { className?: string }) {
  return (
    <div className={cn('grid size-8 shrink-0 place-items-center rounded-full bg-cobalt-wash text-cobalt', className)}>
      <SparklesIcon className="size-4" />
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      variant="ghost"
      size="xs"
      className="text-muted-foreground"
      onClick={() =>
        navigator.clipboard?.writeText(text).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
      {copied ? 'Copied' : 'Copy'}
    </Button>
  )
}

export function UserMessage({ content }: { content: string }) {
  return (
    <Message align="end">
      <MessageContent>
        <Bubble align="end" variant="muted" className="max-w-[80%]">
          <BubbleContent className="rounded-3xl bg-sunken px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-ink">
            {content}
          </BubbleContent>
        </Bubble>
      </MessageContent>
    </Message>
  )
}

/** The tools the assistant ran for a reply, as small chips above it. */
function ToolChips({ tools }: { tools: ToolUse[] }) {
  return (
    <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Tools used">
      {tools.map((t, i) => (
        <li
          key={i}
          title={t.name}
          className="inline-flex items-center gap-1.5 rounded-full border border-line bg-paper px-2.5 py-1 text-[12px] text-muted-foreground"
        >
          <DatabaseIcon className="size-3.5" aria-hidden />
          {t.label}
        </li>
      ))}
    </ul>
  )
}

/** A reply: no bubble, full column width, so tables (and later charts) have room. */
export function AssistantMessage({
  content,
  tools = [],
  traceId = null,
  streaming = false,
}: {
  content: string
  tools?: ToolUse[]
  /** Links to what happened behind this reply (model calls, tools, time, tokens). */
  traceId?: number | null
  streaming?: boolean
}) {
  // Stable while the tools don't change, so charts aren't redrawn from scratch on every render.
  const data = useMemo(() => tools.flatMap((t) => (t.data ? [t.data] : [])), [tools])
  // Proposed actions get a card below the reply instead of a chip.
  const lookups = tools.filter((t) => !t.action_id)
  const actionIds = [...new Set(tools.flatMap((t) => (t.action_id ? [t.action_id] : [])))]
  return (
    <Message className="group/reply">
      <MessageContent className="gap-1">
        {lookups.length > 0 && <ToolChips tools={lookups} />}
        {content.trim() ? (
          <div className="chat-md text-[15px] leading-7 text-ink">
            <Suspense fallback={<p className="whitespace-pre-wrap">{content}</p>}>
              <ChatMarkdown data={data} streaming={streaming}>
                {content}
              </ChatMarkdown>
            </Suspense>
          </div>
        ) : (
          streaming && <Typing />
        )}
        {actionIds.map((id) => (
          <ActionCard key={id} id={id} />
        ))}
        {!streaming && (
          <MessageFooter className="-ml-2 px-0 opacity-0 transition-opacity group-hover/reply:opacity-100 focus-within:opacity-100 [@media(hover:none)]:opacity-100">
            <CopyButton text={content} />
            {traceId !== null && (
              <Button
                variant="ghost"
                size="xs"
                className="text-muted-foreground"
                nativeButton={false}
                render={<Link to={`/traces/${traceId}`} />}
              >
                <ActivityIcon />
                Details
              </Button>
            )}
          </MessageFooter>
        )}
      </MessageContent>
    </Message>
  )
}

export function Typing() {
  return (
    <div className="flex h-7 items-center gap-1" aria-live="polite" aria-label="Assistant is thinking">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-2 animate-bounce rounded-full bg-faint"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  )
}
