import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'
import type {
  Customer,
  CustomerDetail,
  CustomerInput,
  Order,
  OrderStatus,
  OrderSummary,
  Page,
  Product,
  ProductUpdate,
  Refund,
  RefundReason,
  SeedRequest,
  SeedResult,
  StatsOverview,
  Ticket,
  TicketMessage,
  TicketSummary,
  TicketUpdate,
} from './types'

type Params = Record<string, string | number | boolean | (string | number)[] | null | undefined>

// Query keys are grouped by resource so mutations can invalidate a whole group.
export const keys = {
  stats: ['stats'] as const,
  customers: (p?: Params) => ['customers', p] as const,
  customer: (id: number) => ['customers', id] as const,
  customerOrders: (id: number, p?: Params) => ['customers', id, 'orders', p] as const,
  customerTickets: (id: number, p?: Params) => ['customers', id, 'tickets', p] as const,
  products: (p?: Params) => ['products', p] as const,
  orders: (p?: Params) => ['orders', p] as const,
  order: (id: number) => ['orders', id] as const,
  tickets: (p?: Params) => ['tickets', p] as const,
  ticket: (id: number) => ['tickets', id] as const,
}

const list = { placeholderData: keepPreviousData }

// ---------- reads ----------

export const useStats = () =>
  useQuery({ queryKey: keys.stats, queryFn: () => api.get<StatsOverview>('/api/stats/overview') })

export const useCustomers = (p: Params) =>
  useQuery({ queryKey: keys.customers(p), queryFn: () => api.get<Page<Customer>>('/api/customers', p), ...list })

export const useCustomer = (id: number) =>
  useQuery({ queryKey: keys.customer(id), queryFn: () => api.get<CustomerDetail>(`/api/customers/${id}`) })

export const useCustomerOrders = (id: number, p: Params) =>
  useQuery({
    queryKey: keys.customerOrders(id, p),
    queryFn: () => api.get<Page<OrderSummary>>(`/api/customers/${id}/orders`, p),
    ...list,
  })

export const useCustomerTickets = (id: number, p: Params) =>
  useQuery({
    queryKey: keys.customerTickets(id, p),
    queryFn: () => api.get<Page<TicketSummary>>(`/api/customers/${id}/tickets`, p),
    ...list,
  })

export const useProducts = (p: Params) =>
  useQuery({ queryKey: keys.products(p), queryFn: () => api.get<Page<Product>>('/api/products', p), ...list })

export const useOrders = (p: Params) =>
  useQuery({ queryKey: keys.orders(p), queryFn: () => api.get<Page<OrderSummary>>('/api/orders', p), ...list })

export const useOrder = (id: number | null | undefined) =>
  useQuery({
    queryKey: keys.order(id ?? 0),
    queryFn: () => api.get<Order>(`/api/orders/${id}`),
    enabled: !!id,
  })

export const useTickets = (p: Params) =>
  useQuery({ queryKey: keys.tickets(p), queryFn: () => api.get<Page<TicketSummary>>('/api/tickets', p), ...list })

export const useTicket = (id: number) =>
  useQuery({ queryKey: keys.ticket(id), queryFn: () => api.get<Ticket>(`/api/tickets/${id}`) })

// ---------- writes ----------

function useInvalidate() {
  const qc = useQueryClient()
  return (...groups: string[]) => Promise.all(groups.map((g) => qc.invalidateQueries({ queryKey: [g] })))
}

export function useCreateCustomer() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (body: CustomerInput) => api.post<Customer>('/api/customers', body),
    onSuccess: () => invalidate('customers', 'stats'),
  })
}

export function useUpdateProduct() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, ...body }: ProductUpdate & { id: number }) => api.patch<Product>(`/api/products/${id}`, body),
    onSuccess: () => invalidate('products', 'stats'),
  })
}

export function useAdvanceOrder() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: OrderStatus }) =>
      api.post<Order>(`/api/orders/${id}/status`, { status }),
    onSuccess: () => invalidate('orders', 'customers', 'stats'),
  })
}

export function useCancelOrder() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (id: number) => api.post<Order>(`/api/orders/${id}/cancel`),
    onSuccess: () => invalidate('orders', 'customers', 'products', 'stats'),
  })
}

export function useRefundOrder() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; amount_cents: number; reason: RefundReason; note: string }) =>
      api.post<Refund>(`/api/orders/${id}/refunds`, body),
    onSuccess: () => invalidate('orders', 'customers', 'stats'),
  })
}

export function useUpdateTicket() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, ...body }: TicketUpdate & { id: number }) => api.patch<Ticket>(`/api/tickets/${id}`, body),
    onSuccess: () => invalidate('tickets', 'customers', 'stats'),
  })
}

export function useReplyToTicket() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: string }) =>
      api.post<TicketMessage>(`/api/tickets/${id}/messages`, { author: 'agent', body }),
    onSuccess: () => invalidate('tickets'),
  })
}

export function useSeed() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SeedRequest) => api.post<SeedResult>('/api/admin/seed', body),
    onSuccess: () => qc.invalidateQueries(),
  })
}
