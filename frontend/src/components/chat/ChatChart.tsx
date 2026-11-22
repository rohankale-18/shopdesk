import { useEffect, useRef, useState } from 'react'

import type { ToolData } from '@/api/types'

/**
 * A chart the assistant asked for with a ```chart block. The block only names the data
 * (`data`: a tool result's data_ref) and the columns to draw; the numbers come straight from
 * the tool result, so the model never re-types them.
 */
export interface ChartSpec {
  type: 'line' | 'bar'
  data: string
  x: string
  y: string
  title?: string
}

type Row = ToolData['rows'][number]

const LABELS: Record<string, string> = {
  revenue_usd: 'Revenue',
  orders: 'Orders',
  units_sold: 'Units sold',
  product: 'Product',
  period: 'Period',
}
const label = (column: string) => LABELS[column] ?? column.replace(/_usd$/, '').replace(/_/g, ' ')

/** A value as shown in labels and tables; `tick` is the axis form: whole numbers, compact from 10K. */
function formatValue(column: string, value: number, tick = false) {
  const options: Intl.NumberFormatOptions = tick
    ? value >= 10_000
      ? { notation: 'compact', maximumFractionDigits: 1 }
      : { maximumFractionDigits: 0 }
    : column.endsWith('_usd')
      ? { minimumFractionDigits: 2, maximumFractionDigits: 2 }
      : { maximumFractionDigits: 0 }
  const text = new Intl.NumberFormat('en-US', options).format(value)
  return column.endsWith('_usd') ? `$${text}` : text
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** '2026-11-03' -> 'Nov 3', '2026-11' -> 'Nov 2026'; anything else as it is. */
function formatX(value: unknown) {
  const text = String(value ?? '')
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
  if (day) return `${MONTHS[+day[2] - 1]} ${+day[3]}`
  const month = /^(\d{4})-(\d{2})$/.exec(text)
  if (month) return `${MONTHS[+month[2] - 1]} ${month[1]}`
  return text
}

/** Round axis ticks: 0 up to a clean number at or above the maximum. */
function niceTicks(max: number, count = 4) {
  if (max <= 0) return [0, 1]
  const raw = max / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw
  return Array.from({ length: Math.ceil(max / step) + 1 }, (_, i) => i * step)
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

function LineChart({ rows, x, y }: { rows: Row[]; x: string; y: string }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const height = 220
  const pad = { top: 8, right: 8, bottom: 26, left: 56 }
  const values = rows.map((r) => Number(r[y]) || 0)
  const ticks = niceTicks(Math.max(...values))
  const top = ticks[ticks.length - 1]
  const plotW = Math.max(width - pad.left - pad.right, 1)
  const plotH = height - pad.top - pad.bottom
  const px = (i: number) => pad.left + (rows.length > 1 ? (i / (rows.length - 1)) * plotW : plotW / 2)
  const py = (v: number) => pad.top + plotH - (v / top) * plotH
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${px(i)},${py(v)}`).join(' ')
  const area = `${line} L${px(values.length - 1)},${py(0)} L${px(0)},${py(0)} Z`
  // About six x labels, always including the last.
  const every = Math.max(1, Math.ceil(rows.length / 6))
  const xTicks = rows.map((_, i) => i).filter((i) => i % every === 0 || i === rows.length - 1)
  if (xTicks.length > 1 && xTicks.at(-1)! - xTicks.at(-2)! < every / 2) xTicks.splice(-2, 1)
  const last = values.length - 1
  const shown = hover ?? last

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect()
    const i = Math.round(((e.clientX - box.left - pad.left) / plotW) * (rows.length - 1))
    setHover(Math.min(Math.max(i, 0), rows.length - 1))
  }

  return (
    <div ref={ref}>
      {/* The value under the pointer, or the latest one: one point labelled at a time, above the plot. */}
      <p className="mb-1 flex h-5 items-baseline gap-2 text-[12px]" aria-live="polite">
        <span className="text-muted-foreground">{formatX(rows[shown][x])}</span>
        <span className="font-medium tabular-nums text-ink">{formatValue(y, values[shown])}</span>
      </p>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`${label(y)} by ${label(x)}`}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
          className="block touch-none"
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={width - pad.right} y1={py(t)} y2={py(t)} stroke="var(--line)" strokeWidth={1} />
              <text x={pad.left - 8} y={py(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[11px] tabular-nums">
                {formatValue(y, t, true)}
              </text>
            </g>
          ))}
          {xTicks.map((i) => (
            // The first and last labels align to the plot's edges, so they aren't cut off.
            <text
              key={i}
              x={px(i)}
              y={height - 8}
              textAnchor={rows.length > 1 && i === 0 ? 'start' : rows.length > 1 && i === rows.length - 1 ? 'end' : 'middle'}
              className="fill-muted-foreground text-[11px]"
            >
              {formatX(rows[i][x])}
            </text>
          ))}
          <path d={area} fill="var(--viz-1)" opacity={0.1} />
          <path d={line} fill="none" stroke="var(--viz-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {hover !== null && (
            <line x1={px(hover)} x2={px(hover)} y1={pad.top} y2={pad.top + plotH} stroke="var(--faint)" strokeWidth={1} />
          )}
          <circle cx={px(shown)} cy={py(values[shown])} r={4} fill="var(--viz-1)" stroke="var(--surface)" strokeWidth={2} />
        </svg>
      )}
    </div>
  )
}

function BarChart({ rows, x, y }: { rows: Row[]; x: string; y: string }) {
  const values = rows.map((r) => Number(r[y]) || 0)
  const max = Math.max(...values, 1)
  return (
    <ul className="grid gap-2" aria-label={`${label(y)} by ${label(x)}`}>
      {rows.map((r, i) => (
        <li key={i} className="group grid grid-cols-[minmax(0,10rem)_1fr] items-center gap-3 text-[13px]" title={`${r[x]}: ${formatValue(y, values[i])}`}>
          <span className="truncate text-muted-foreground group-hover:text-ink">{String(r[x])}</span>
          <span className="flex items-center gap-2">
            <span
              className="h-5 rounded-r-[4px] bg-[var(--viz-1)] transition-opacity group-hover:opacity-80"
              style={{ width: `${(values[i] / max) * 85}%`, minWidth: 2 }}
            />
            <span className="shrink-0 font-medium tabular-nums text-ink">{formatValue(y, values[i])}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg border border-line bg-sunken/60 px-3 py-2 text-[13px] text-muted-foreground">{children}</p>
}

/** Renders a ```chart block. `source` is the block's text; `data` the reply's tool results. */
export function ChatChart({ source, data, streaming }: { source: string; data: ToolData[]; streaming?: boolean }) {
  const [table, setTable] = useState(false)
  let spec: ChartSpec
  try {
    spec = JSON.parse(source)
  } catch {
    // Mid-stream the block is half-written: hold its place instead of flashing the raw text.
    if (streaming) return <div className="h-[260px] animate-pulse rounded-xl border border-line bg-sunken/40" />
    return <Note>This chart couldn't be drawn (its description isn't valid).</Note>
  }
  const rows = data.find((d) => d.ref === spec.data)?.rows
  if (!rows) return <Note>The data for this chart isn't available. Ask again to look it up.</Note>
  if (!rows.length || !(spec.x in rows[0]) || !(spec.y in rows[0])) {
    return <Note>This chart couldn't be drawn (it names columns the data doesn't have).</Note>
  }

  return (
    <figure className="not-prose my-3 rounded-xl border border-line bg-surface p-4">
      <figcaption className="mb-3 flex items-baseline justify-between gap-3">
        <span className="text-[14px] font-semibold text-ink">{spec.title ?? `${label(spec.y)} by ${label(spec.x)}`}</span>
        <button
          type="button"
          onClick={() => setTable((t) => !t)}
          className="shrink-0 cursor-pointer text-[12px] text-muted-foreground hover:text-ink"
        >
          {table ? 'Show chart' : 'Show table'}
        </button>
      </figcaption>
      {table ? (
        <div className="chat-table">
          <table>
            <thead>
              <tr>
                <th>{label(spec.x)}</th>
                <th>{label(spec.y)}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>{spec.type === 'line' ? formatX(r[spec.x]) : String(r[spec.x])}</td>
                  <td className="tabular-nums">{formatValue(spec.y, Number(r[spec.y]) || 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : spec.type === 'bar' ? (
        <BarChart rows={rows} x={spec.x} y={spec.y} />
      ) : (
        <LineChart rows={rows} x={spec.x} y={spec.y} />
      )}
    </figure>
  )
}
