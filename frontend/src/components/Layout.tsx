import { NavLink, Outlet } from 'react-router-dom'

import { useStats } from '../api/hooks'
import { cx } from './ui'

// Same origin by default: Vite (dev) and nginx (Docker) both proxy /docs to FastAPI.
const API_DOCS = `${(import.meta.env.VITE_API_URL as string | undefined) ?? ''}/docs`

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/tickets', label: 'Tickets', count: 'tickets' as const },
  { to: '/orders', label: 'Orders' },
  { to: '/customers', label: 'Customers' },
  { to: '/products', label: 'Products' },
  { to: '/data', label: 'Test data', mobileOnly: true },
]

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
      <rect width="32" height="32" rx="7" className="fill-cobalt" />
      <path d="M8 12.5 16 8l8 4.5v8L16 25l-8-4.5z M8 12.5 16 17l8-4.5M16 17v8" fill="none" className="stroke-cobalt-ink" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  )
}

export function Layout() {
  const { data: stats } = useStats()

  const link = ({ isActive }: { isActive: boolean }) =>
    cx(
      'flex items-center justify-between gap-3 rounded-md px-2.5 py-1.5 text-[14px] whitespace-nowrap',
      isActive ? 'bg-surface font-semibold text-ink shadow-[inset_0_0_0_1px_var(--line)]' : 'text-muted hover:text-ink',
    )

  return (
    <div className="min-h-screen md:grid md:grid-cols-[220px_1fr]">
      <aside className="border-b border-line md:sticky md:top-0 md:h-screen md:border-r md:border-b-0">
        <div className="flex h-full flex-col gap-4 p-3 md:p-4">
          <div className="flex items-center gap-2.5 px-1">
            <Logo />
            <div className="leading-tight">
              <div className="text-[15px] font-semibold">ShopDesk</div>
              <div className="text-[12px] text-muted">Support console</div>
            </div>
          </div>

          <nav className="-mx-1 flex gap-1 overflow-x-auto px-1 md:flex-col md:overflow-visible" aria-label="Main">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={(a) => cx(link(a), n.mobileOnly && 'md:hidden')}
              >
                {n.label}
                {n.count && stats && stats.open_tickets > 0 && (
                  <span className="num rounded bg-cobalt-wash px-1.5 text-[12px] font-semibold text-cobalt">
                    {stats.open_tickets}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>

          <div className="mt-auto hidden flex-col gap-1 border-t border-line pt-3 md:flex">
            <NavLink to="/data" className={link}>
              Test data
            </NavLink>
            <a href={API_DOCS} target="_blank" rel="noreferrer" className="rounded-md px-2.5 py-1.5 text-[14px] text-muted hover:text-ink">
              API docs
            </a>
          </div>
        </div>
      </aside>

      <main className="min-w-0 px-4 py-6 md:px-8 md:py-8">
        <div className="mx-auto max-w-[1180px]">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
