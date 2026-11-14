import { Suspense, useState } from 'react'
import { CheckIcon, CopyIcon, SparklesIcon } from 'lucide-react'
import { cn } from 'cn'

import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { Button } from '@/components/ui/button'
import { Message, MessageContent, MessageFooter } from '@/components/ui/message'

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

/** A reply: no bubble, full column width, so tables (and later charts) have room. */
export function AssistantMessage({ content, streaming = false }: { content: string; streaming?: boolean }) {
  return (
    <Message className="group/reply">
      <MessageContent className="gap-1">
        <div className="chat-md text-[15px] leading-7 text-ink">
          <Suspense fallback={<p className="whitespace-pre-wrap">{content}</p>}>
            <ChatMarkdown>{content}</ChatMarkdown>
          </Suspense>
        </div>
        {!streaming && (
          <MessageFooter className="-ml-2 px-0 opacity-0 transition-opacity group-hover/reply:opacity-100 focus-within:opacity-100 [@media(hover:none)]:opacity-100">
            <CopyButton text={content} />
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
