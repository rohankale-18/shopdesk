import type { ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeftIcon, BrainIcon, MessageSquareIcon, SparklesIcon, WrenchIcon } from 'lucide-react'

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

function Code({ children, className }: { children: string; className?: string }) {
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
          <Table head={['When', 'Question', 'Status', 'Tools', 'Model calls', 'Time', 'First word', 'Tokens']} alignRight={[4, 5, 6, 7]}>
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
                <Td className="num whitespace-nowrap text-right">{tokens(t.total_tokens)}</Td>
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

function ModelCallCard({ call, previous, runs }: { call: ModelCall; previous?: ModelCall; runs: ToolRun[] }) {
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
              <Code>{call.response_text}</Code>
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

      <Panel className="mb-6" title="Where the time went">
        <TimeBar trace={t} />
      </Panel>

      <h2 className="mb-3 text-[15px] font-semibold">Step by step</h2>
      <ol className="flex flex-col gap-4 border-l border-line pl-0 [&>li]:-ml-3">
        {t.model_calls.map((call, i) => (
          <ModelCallCard
            key={call.step}
            call={call}
            previous={t.model_calls[i - 1]}
            runs={t.tool_runs.filter((r) => r.step === call.step)}
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
