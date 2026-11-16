import { lazy, Suspense } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'

import { ApiError } from './api/client'
import { Layout } from './components/Layout'
import { PageHeader } from './components/ui'
import { CustomerDetail, Customers } from './pages/Customers'
import { OrderDetail, Orders } from './pages/Orders'
import { Overview } from './pages/Overview'
import { Products } from './pages/Products'
import { TestData } from './pages/TestData'
import { TicketDetail } from './pages/TicketDetail'
import { Tickets } from './pages/Tickets'

// Lazy: the chat UI (Base UI, message scroller, Markdown) loads only when the page is opened.
const Assistant = lazy(() => import('./pages/Assistant'))
const Traces = lazy(() => import('./pages/Traces'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      // Don't retry errors that won't fix themselves (404, 422...).
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
})

function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" subtitle="That address doesn't match anything in ShopDesk." />
      <Link to="/" className="text-cobalt hover:underline">
        Go to the overview
      </Link>
    </>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="tickets" element={<Tickets />} />
            <Route path="tickets/:id" element={<TicketDetail />} />
            <Route path="orders" element={<Orders />} />
            <Route path="orders/:id" element={<OrderDetail />} />
            <Route path="customers" element={<Customers />} />
            <Route path="customers/:id" element={<CustomerDetail />} />
            <Route path="products" element={<Products />} />
            <Route path="data" element={<TestData />} />
            <Route
              path="assistant/:id?"
              element={
                <Suspense fallback={null}>
                  <Assistant />
                </Suspense>
              }
            />
            <Route
              path="traces/:id?"
              element={
                <Suspense fallback={null}>
                  <Traces />
                </Suspense>
              }
            />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
