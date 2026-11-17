import type { ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeftIcon,
  BrainIcon,
  CheckCircle2Icon,
  MessageSquareIcon,
  SparklesIcon,
  TriangleAlertIcon,
  WrenchIcon,
} from 'lucide-react'

import { useTrace, useTraces } from '../api/hooks'
import type { ModelCall, PromptMessage, ToolRun, TraceDetail, TraceStatus } from '../api/types'
import { Badge, Empty, ErrorState, Loading, PageHeader, Panel, Table, Td, cx } from '../components/ui'
import { dateTime } from '../lib/format'

// ---------- small helpers ----------

const ms = (value: number | null) =>
  value === null ? '—' : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(value < 10_000 ? 2 : 1)} s`

const tokens = (n: number) => n.toLocaleString()

const STATUS_TONE = { ok: 'green', error: 'red', stopped: 'slate' } as const

function StatusBadge({ status }: { status: TraceStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{status === 'ok' ? 'OK' : status === 'error' ? 'Error' : 'Stopped'}</Badge>
}

/** JSON (or a string holding JSON) as readable, indented text. */
function pretty(value: unknown): string {
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  return JSON.stringify(value, null, 2)
}

function Code({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <pre
      className={cx(
        'max-h-96 overflow-auto rounded-md border border-line bg-sunken px-3 py-2 font-mono text-[12.5px] leading-5 wrap-break-word whitespace-pre-wrap',
        className,
      )}
    >
      {children}
    </pre>
  )
}

/** A collapsible section (native <details>, so it works with the keyboard and screen readers). */
function Section({ title, meta, open, children }: { title: ReactNode; meta?: ReactNode; open?: boolean; children: ReactNode }) {
  return (
    <details open={open} className="group/section rounded-md border border-line">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-[13px] font-medium select-none hover:bg-sunken [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-2">
          <span className="text-faint transition-transform group-open/section:rotate-90" aria-hidden>
            ›
          </span>
          {title}
        </span>
        {meta && <span className="text-[12px] font-normal text-muted-foreground">{meta}</span>}
      </summary>
      <div className="border-t border-line p-3">{children}</div>
    </details>
  )
}

// ---------- list ----------

function TraceList() {
  const q = useTraces()
  const navigate = useNavigate()

  return (
    <>
      <PageHeader
        title="Traces"
        subtitle="What happened behind each assistant reply: every model call and tool run, with time and tokens."
      />
      <Panel flush>
        {q.isLoading ? (
          <Loading />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : !q.data?.length ? (
          <Empty>No traces yet. Ask the assistant something, then come back.</Empty>
        ) : (
          <Table
            head={['When', 'Question', 'Status', 'Tools', 'Model calls', 'Time', 'First word', 'Tokens in', 'Tokens out']}
            alignRight={[4, 5, 6, 7, 8]}
          >
            {q.data.map((t) => (
              <tr key={t.id} onClick={() => navigate(`/traces/${t.id}`)} className="cursor-pointer hover:bg-sunken">
                <Td className="whitespace-nowrap text-muted-foreground">{dateTime(t.started_at)}</Td>
                <Td className="max-w-88">
                  <Link to={`/traces/${t.id}`} className="line-clamp-1 hover:text-cobalt" title={t.question}>
                    {t.question}
                  </Link>
                </Td>
                <Td>
                  <StatusBadge status={t.status} />
                </Td>
                <Td>
                  {t.tool_runs.length ? (
                    <span className="flex flex-wrap gap-1">
                      {t.tool_runs.map((r, i) => (
                        <code key={i} className={cx('rounded bg-sunken px-1.5 py-0.5 text-[12px]', r.is_error && 'text-danger')}>
                          {r.name}
                        </code>
                      ))}
                    </span>
                  ) : (
                    <span className="text-faint">none</span>
                  )}
                </Td>
                <Td className="num whitespace-nowrap text-right">{t.steps}</Td>
                <Td className="num whitespace-nowrap text-right">{ms(t.duration_ms)}</Td>
                <Td className="num whitespace-nowrap text-right text-muted-foreground">{ms(t.first_token_ms)}</Td>
                <Td className="num whitespace-nowrap text-right">{tokens(t.prompt_tokens)}</Td>
                <Td className="num whitespace-nowrap text-right">
                  <span title={`${tokens(t.reasoning_tokens)} of them reasoning`}>{tokens(t.completion_tokens)}</span>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>
    </>
  )
}

// ---------- detail ----------

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <div className="text-[12.5px] text-muted-foreground">{label}</div>
      <div className="num mt-0.5 text-[20px] font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-0.5 text-[12px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

/** One bar for the whole reply: where the time went, model calls vs tools, in order. */
function TimeBar({ trace }: { trace: TraceDetail }) {
  const parts: { key: string; label: string; ms: number; kind: 'model' | 'tool' }[] = []
  for (const call of trace.model_calls) {
    parts.push({ key: `m${call.step}`, label: `Model call ${call.step}`, ms: call.duration_ms, kind: 'model' })
    trace.tool_runs
      .filter((r) => r.step === call.step)
      .forEach((r, i) => parts.push({ key: `t${call.step}-${i}`, label: r.name, ms: r.duration_ms, kind: 'tool' }))
  }
  const total = Math.max(1, parts.reduce((sum, p) => sum + p.ms, 0))
  return (
    <div>
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full bg-sunken">
        {parts.map((p) => (
          <div
            key={p.key}
            title={`${p.label}: ${ms(p.ms)}`}
            className={p.kind === 'model' ? 'bg-cobalt' : 'bg-st-violet'}
            style={{ width: `${Math.max(1, (p.ms / total) * 100)}%` }}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-4 text-[12px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-cobalt" /> Model calls
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-st-violet" /> Tools
        </span>
      </div>
    </div>
  )
}

// ---------- tokens ----------

// Chart slots 1 and 2 (index.css).
const REASONING_COLOR = 'var(--viz-1)'
const VISIBLE_COLOR = 'var(--viz-2)'

type Segment = { label: string; value: number; color: string; hint?: string }

const pct = (value: number, total: number) => (total ? Math.round((value / total) * 100) : 0)

/** One stacked bar plus its legend (values in the legend, so color is never the only label). */
function StackedBar({ title, total, segments }: { title: string; total: number; segments: Segment[] }) {
  const shown = segments.filter((s) => s.value > 0)
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]">
        <span className="font-medium">{title}</span>
        <span className="num text-muted-foreground">{tokens(total)} tokens</span>
      </div>
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full bg-sunken" role="img" aria-label={`${title} by part`}>
        {shown.map((s) => (
          <div
            key={s.label}
            title={`${s.label}: ${tokens(s.value)} tokens (${pct(s.value, total)}%)`}
            className="first:rounded-l-full last:rounded-r-full"
            style={{ width: `${Math.max(0.5, (s.value / Math.max(total, 1)) * 100)}%`, background: s.color }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1.5 text-[12.5px]">
        {segments.map((s) => (
          <li key={s.label} className="flex items-center gap-1.5" title={s.hint}>
            <span className="size-2.5 shrink-0 rounded-sm" style={{ background: s.color }} aria-hidden />
            <span className="text-muted-foreground">{s.label}</span>
            <span className="num">{tokens(s.value)}</span>
            <span className="num text-faint">{pct(s.value, total)}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Where the tokens went, as Groq reports them: output by kind, then per call with Groq's timings. */
function TokenBreakdown({ trace }: { trace: TraceDetail }) {
  const calls = trace.model_calls
  const visible = trace.completion_tokens - trace.reasoning_tokens

  return (
    <div className="flex flex-col gap-5">
      <StackedBar
        title="Output (written by the model)"
        total={trace.completion_tokens}
        segments={[
          { label: 'Reasoning (hidden)', value: trace.reasoning_tokens, color: REASONING_COLOR },
          { label: 'Answer and tool requests', value: visible, color: VISIBLE_COLOR },
        ]}
      />

      <div>
        <h3 className="mb-1 text-[13px] font-medium">Per call</h3>
        <Table
          head={['Call', 'Input', 'Reasoning', 'Answer and tool requests', 'Output', 'Queue', 'Reading input', 'Writing output', 'Speed']}
          alignRight={[1, 2, 3, 4, 5, 6, 7, 8]}
        >
          {calls.map((c) => (
            <tr key={c.step} className="border-t border-line">
              <Td>{c.step}</Td>
              <Td className="num text-right font-medium">{tokens(c.prompt_tokens)}</Td>
              <Td className="num text-right text-muted-foreground">{tokens(c.reasoning_tokens)}</Td>
              <Td className="num text-right text-muted-foreground">{tokens(c.completion_tokens - c.reasoning_tokens)}</Td>
              <Td className="num text-right font-medium">{tokens(c.completion_tokens)}</Td>
              <Td className="num whitespace-nowrap text-right text-muted-foreground">{ms(c.queue_ms)}</Td>
              <Td className="num whitespace-nowrap text-right text-muted-foreground">{ms(c.input_ms)}</Td>
              <Td className="num whitespace-nowrap text-right text-muted-foreground">{ms(c.output_ms)}</Td>
              <Td className="num whitespace-nowrap text-right text-muted-foreground">
                {c.output_ms ? `${Math.round(c.completion_tokens / (c.output_ms / 1000))} tokens/s` : '—'}
              </Td>
            </tr>
          ))}
        </Table>
      </div>

      <p className="text-[12.5px] text-muted-foreground">
        All numbers come from Groq. Queue, reading and writing are Groq's own times; each call's time in the steps below
        is longer because it includes the network. Groq gives the input as one total; open "Prompt sent" on a call to see
        what was in it.
      </p>
    </div>
  )
}

function PromptMessages({ messages, newFrom }: { messages: PromptMessage[]; newFrom: number }) {
  return (
    <ol className="flex flex-col gap-2">
      {messages.map((m, i) => (
        <li key={i} className={cx('rounded-md border px-3 py-2', i >= newFrom ? 'border-cobalt/40 bg-cobalt-wash/40' : 'border-line')}>
          <div className="mb-1 flex items-center gap-2 text-[12px] font-medium tracking-wide text-muted-foreground uppercase">
            {m.role}
            {m.tool_call_id && <span className="font-mono normal-case">→ {m.tool_call_id}</span>}
            {i >= newFrom && <Badge tone="blue">new this call</Badge>}
          </div>
          {m.role === 'system' && m.content ? (
            // Long and the same every call: collapsed, so the messages that change stand out.
            <details>
              <summary className="cursor-pointer text-[12.5px] text-muted-foreground select-none hover:text-ink">
                Show system prompt ({m.content.length.toLocaleString()} characters, sent with every call)
              </summary>
              <div className="mt-2 font-mono text-[12.5px] leading-5 wrap-break-word whitespace-pre-wrap">{m.content}</div>
            </details>
          ) : m.content ? (
            <div className="font-mono text-[12.5px] leading-5 wrap-break-word whitespace-pre-wrap">
              {m.role === 'tool' ? pretty(m.content) : m.content}
            </div>
          ) : null}
          {m.tool_calls?.map((c) => (
            <div key={c.id} className="font-mono text-[12.5px] text-st-violet">
              asked for {c.function.name}({c.function.arguments}) <span className="text-faint">id {c.id}</span>
            </div>
          ))}
        </li>
      ))}
    </ol>
  )
}

function ModelCallCard({
  call,
  previous,
  runs,
  flagged,
}: {
  call: ModelCall
  previous?: ModelCall
  runs: ToolRun[]
  /** Numbers to highlight in the answer: not found in any tool result. */
  flagged: string[]
}) {
  const askedForTools = call.tool_calls.length > 0
  const sent = call.request.messages
  return (
    <li className="relative pl-9">
      <span className="absolute top-3 left-0 grid size-6 place-items-center rounded-full bg-cobalt-wash text-cobalt">
        <SparklesIcon className="size-3.5" />
      </span>
      <Panel
        title={
          <span className="flex flex-wrap items-center gap-2">
            Model call {call.step}
            {call.finish_reason && (
              <Badge tone={call.finish_reason === 'stop' ? 'green' : call.finish_reason === 'tool_calls' ? 'violet' : 'amber'}>
                {call.finish_reason}
              </Badge>
            )}
          </span>
        }
        actions={
          <span className="num text-[12.5px] text-muted-foreground">
            {ms(call.duration_ms)} · {tokens(call.prompt_tokens)} in → {tokens(call.completion_tokens)} out
            {call.reasoning_tokens > 0 && ` (${tokens(call.reasoning_tokens)} reasoning)`}
          </span>
        }
      >
        <div className="flex flex-col gap-3">
          <Section
            title="Prompt sent"
            meta={`${sent.length} messages · tools: ${call.request.tools.join(', ') || 'none'} · tool_choice: ${call.request.tool_choice}`}
          >
            <PromptMessages messages={sent} newFrom={previous ? previous.request.messages.length : 0} />
          </Section>

          {call.reasoning && (
            <Section title={<span className="flex items-center gap-1.5"><BrainIcon className="size-3.5" /> Reasoning (hidden from the user)</span>} open>
              <p className="text-[13.5px] leading-6 whitespace-pre-wrap text-muted-foreground">{call.reasoning}</p>
            </Section>
          )}

          {askedForTools ? (
            <div>
              <div className="mb-1.5 text-[12.5px] font-medium text-muted-foreground">Asked to run</div>
              <ul className="flex flex-col gap-1">
                {call.tool_calls.map((t, i) => (
                  <li key={i} className="font-mono text-[12.5px]">
                    <span className="text-st-violet">{t.name}</span>({t.arguments})
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {call.response_text && (
            <div>
              <div className="mb-1.5 flex items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground">
                <MessageSquareIcon className="size-3.5" /> {askedForTools ? 'Text before the tools' : 'Answer'}
                {call.first_token_ms !== null && <span className="font-normal">· first word after {ms(call.first_token_ms)}</span>}
              </div>
              <Code>
                <Highlighted text={call.response_text} numbers={flagged} />
              </Code>
            </div>
          )}
        </div>
      </Panel>

      {runs.length > 0 && (
        <ul className="mt-3 flex flex-col gap-3">
          {runs.map((r, i) => (
            <ToolRunCard key={i} run={r} />
          ))}
        </ul>
      )}
    </li>
  )
}

function ToolRunCard({ run }: { run: ToolRun }) {
  return (
    <li className="relative">
      <span className="absolute top-3 -left-9 grid size-6 place-items-center rounded-full bg-st-violet-wash text-st-violet">
        <WrenchIcon className="size-3.5" />
      </span>
      <Panel
        title={
          <span className="flex items-center gap-2">
            Tool: <code className="font-mono">{run.name}</code>
            {run.is_error && <Badge tone="red">error</Badge>}
          </span>
        }
        actions={<span className="num text-[12.5px] text-muted-foreground">{ms(run.duration_ms)}</span>}
      >
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <div>
            <div className="mb-1.5 text-[12.5px] font-medium text-muted-foreground">Arguments (from the model)</div>
            <Code>{pretty(run.arguments)}</Code>
          </div>
          <div>
            <div className="mb-1.5 text-[12.5px] font-medium text-muted-foreground">Result (sent back to the model)</div>
            <Code className={run.is_error ? 'text-danger' : undefined}>{pretty(run.result)}</Code>
          </div>
        </div>
      </Panel>
    </li>
  )
}

/** Did every number in the answer come from somewhere? Flags the ones that didn't. */
function GroundingNote({ trace }: { trace: TraceDetail }) {
  const flagged = trace.unsupported_numbers
  if (flagged.length === 0) {
    if (trace.tool_runs.length === 0) return null
    return (
      <p className="mb-4 flex items-center gap-2 text-[13px] text-muted-foreground">
        <CheckCircle2Icon className="size-4 text-st-green" aria-hidden />
        Every number in the answer appears in a tool result or the conversation.
      </p>
    )
  }
  return (
    <div role="note" className="mb-4 rounded-lg border border-st-amber/40 bg-st-amber-wash px-4 py-3 text-[13.5px]">
      <div className="flex items-center gap-2 font-medium text-st-amber">
        <TriangleAlertIcon className="size-4" aria-hidden />
        {flagged.length === 1 ? '1 number' : `${flagged.length} numbers`} in the answer aren't in any tool result
      </div>
      <p className="mt-1 text-ink">
        {flagged.map((n, i) => (
          <span key={n}>
            {i > 0 && ', '}
            <mark className="rounded bg-st-amber/20 px-1 font-mono text-[12.5px] text-ink">{n}</mark>
          </span>
        ))}
      </p>
      <p className="mt-1 text-[12.5px] text-muted-foreground">
        The model made these up or worked them out itself (or they're dates written in an unusual way). Check them against
        the tool results below. They're highlighted in the answer.
      </p>
    </div>
  )
}

/** Text with the given numbers highlighted (whole numbers only: "9" doesn't match inside "1,904"). */
function Highlighted({ text, numbers }: { text: string; numbers: string[] }) {
  if (numbers.length === 0) return <>{text}</>
  const escaped = numbers.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`(?<![\\d.,])(${escaped.join('|')})(?![\\d]|[.,]\\d)`, 'g')
  const parts = text.split(pattern)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded bg-st-amber/25 px-0.5 text-ink">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  )
}

function TraceView({ id }: { id: number }) {
  const q = useTrace(id)
  if (q.isLoading) return <Loading rows={10} />
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const t = q.data

  return (
    <>
      <Link to="/traces" className="mb-3 inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-cobalt">
        <ArrowLeftIcon className="size-3.5" /> All traces
      </Link>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            Trace #{t.id} <StatusBadge status={t.status} />
          </span>
        }
        subtitle={
          <>
            {dateTime(t.started_at)} · {t.model}
          </>
        }
        actions={
          <Link to={`/assistant/${t.conversation_id}`} className="text-[13.5px] text-cobalt hover:underline">
            Open conversation
          </Link>
        }
      />

      <div className="mb-4 rounded-lg border border-line bg-surface px-4 py-3">
        <div className="text-[12.5px] text-muted-foreground">Question</div>
        <div className="mt-0.5 text-[15px] whitespace-pre-wrap">{t.question}</div>
      </div>

      <GroundingNote trace={t} />

      {t.error && (
        <p role="alert" className="mb-4 rounded-lg bg-danger-wash px-4 py-2.5 text-[13.5px] text-danger">
          {t.error}
        </p>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Total time" value={ms(t.duration_ms)} hint={`first word after ${ms(t.first_token_ms)}`} />
        <Stat label="Model calls" value={t.steps} hint={t.steps === 1 ? 'answered directly' : 'passes round the loop'} />
        <Stat
          label="Tools run"
          value={t.tool_runs.length}
          hint={t.tool_runs.some((r) => r.is_error) ? `${t.tool_runs.filter((r) => r.is_error).length} with errors` : undefined}
        />
        <Stat
          label="Tokens"
          value={tokens(t.total_tokens)}
          hint={`${tokens(t.prompt_tokens)} in · ${tokens(t.completion_tokens)} out · ${tokens(t.reasoning_tokens)} reasoning`}
        />
      </div>

      <Panel className="mb-4" title="Where the time went">
        <TimeBar trace={t} />
      </Panel>

      <Panel className="mb-6" title="Where the tokens went">
        <TokenBreakdown trace={t} />
      </Panel>

      <h2 className="mb-3 text-[15px] font-semibold">Step by step</h2>
      <ol className="flex flex-col gap-4 border-l border-line pl-0 [&>li]:-ml-3">
        {t.model_calls.map((call, i) => (
          <ModelCallCard
            key={call.step}
            call={call}
            previous={t.model_calls[i - 1]}
            runs={t.tool_runs.filter((r) => r.step === call.step)}
            flagged={t.unsupported_numbers}
          />
        ))}
      </ol>
    </>
  )
}

export default function Traces() {
  const { id } = useParams()
  return id ? <TraceView key={id} id={Number(id)} /> : <TraceList />
}
