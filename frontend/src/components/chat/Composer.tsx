import type { Ref } from 'react'
import { ArrowUpIcon, SquareIcon } from 'lucide-react'
import { cn } from 'cn'

import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from '@/components/ui/input-group'

/** The message box: Enter sends, Shift+Enter adds a line. While a reply streams, Send becomes Stop. */
export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  disabled,
  placeholder = 'Ask the assistant…',
  inputRef,
  className,
}: {
  value: string
  onChange: (value: string) => void
  onSubmit: (value: string) => void
  onStop: () => void
  busy: boolean
  disabled?: boolean
  placeholder?: string
  inputRef?: Ref<HTMLTextAreaElement>
  className?: string
}) {
  return (
    <form
      className={className}
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(value)
      }}
    >
      <InputGroup
        className={cn(
          'rounded-3xl border-line bg-surface shadow-[0_2px_12px_-4px_rgb(20_30_60/0.12)]',
          'has-[[data-slot=input-group-control]:focus-visible]:ring-0',
          // shadcn fades the group when *anything* inside is disabled, including the Send button
          // (disabled while the box is empty). Only fade when the text box itself is disabled.
          'has-disabled:bg-surface has-disabled:opacity-100 dark:has-disabled:bg-surface',
          'has-[textarea:disabled]:opacity-60',
        )}
      >
        <InputGroupTextarea
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              e.currentTarget.form?.requestSubmit()
            }
          }}
          rows={1}
          maxLength={4000}
          placeholder={disabled ? 'AI is not configured' : placeholder}
          disabled={disabled}
          aria-label="Message"
          className="max-h-60 min-h-12 px-4 pt-3.5 text-[15px] focus-visible:outline-none md:text-[15px]"
        />
        <InputGroupAddon align="block-end" className="px-3 pb-3">
          <span className="hidden text-[12px] font-normal text-faint sm:inline">
            Enter to send · Shift+Enter for a new line
          </span>
          {busy ? (
            <InputGroupButton
              variant="default"
              size="icon-sm"
              className="ml-auto size-9 rounded-full"
              onClick={onStop}
              aria-label="Stop"
              title="Stop"
            >
              <SquareIcon className="size-3.5 fill-current" />
            </InputGroupButton>
          ) : (
            <InputGroupButton
              type="submit"
              variant="default"
              size="icon-sm"
              className="ml-auto size-9 rounded-full"
              disabled={disabled || !value.trim()}
              aria-label="Send"
            >
              <ArrowUpIcon className="size-4.5" />
            </InputGroupButton>
          )}
        </InputGroupAddon>
      </InputGroup>
    </form>
  )
}
