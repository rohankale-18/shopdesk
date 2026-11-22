import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from './client'
import type {
  AIStatus,
  Conversation,
  ConversationSummary,
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
  SendMessageResult,
  ToolUse,
  StatsOverview,
  Ticket,
  TicketMessage,
  TicketSummary,
  TicketUpdate,
  TraceDetail,
  TraceSummary,
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

export const useTicket = (id: number, enabled = true) =>
  useQuery({ queryKey: keys.ticket(id), queryFn: () => api.get<Ticket>(`/api/tickets/${id}`), enabled })

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

// ---------- AI chat ----------

const chatKeys = {
  status: ['ai', 'status'] as const,
  list: ['chat', 'list'] as const,
  conversation: (id: number) => ['chat', 'conversation', id] as const,
}

export const useAIStatus = () =>
  useQuery({ queryKey: chatKeys.status, queryFn: () => api.get<AIStatus>('/api/ai/status'), staleTime: 60_000 })

export const useConversations = (enabled = true) =>
  useQuery({
    queryKey: chatKeys.list,
    queryFn: () => api.get<ConversationSummary[]>('/api/chat/conversations'),
    enabled,
  })

export const useConversation = (id: number | null) =>
  useQuery({
    queryKey: chatKeys.conversation(id ?? 0),
    queryFn: () => api.get<Conversation>(`/api/chat/conversations/${id}`),
    enabled: !!id,
    staleTime: Infinity, // only this tab changes it, and we update the cache ourselves
  })

export function useDeleteConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/api/chat/conversations/${id}`),
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: chatKeys.conversation(id) })
      return qc.invalidateQueries({ queryKey: chatKeys.list })
    },
  })
}

export function useCreateConversation() {
  const qc = useQueryClient()
  return useMutation({
    /** `ticketId`: the ticket the chat is about (page context), if any. */
    mutationFn: (ticketId?: number | null) =>
      api.post<Conversation>('/api/chat/conversations', ticketId ? { ticket_id: ticketId } : undefined),
    onSuccess: (convo) => {
      qc.setQueryData(chatKeys.conversation(convo.id), convo)
      return qc.invalidateQueries({ queryKey: chatKeys.list })
    },
  })
}

/**
 * Returns `send(id, content, { onDelta, signal })`. The reply streams in through `onDelta`;
 * the promise resolves with both saved messages, or rejects with an ApiError (or AbortError).
 */
export function useSendChatMessage() {
  const qc = useQueryClient()

  return async (
    id: number,
    content: string,
    opts: {
      onDelta: (text: string) => void
      onTool?: (tool: ToolUse) => void
      /** Called with the saved messages just before they are added to the cache. */
      onSaved?: (result: SendMessageResult) => void
      signal?: AbortSignal
    },
  ): Promise<SendMessageResult> => {
    let result = null as SendMessageResult | null
    await api.stream(
      `/api/chat/conversations/${id}/messages`,
      { content },
      (event, data) => {
        if (event === 'delta') opts.onDelta((data as { text: string }).text)
        else if (event === 'tool') opts.onTool?.(data as ToolUse)
        else if (event === 'done') result = data as SendMessageResult
        else if (event === 'error') {
          const { code, message } = data as { code: string; message: string }
          throw new ApiError(502, code, message)
        }
      },
      opts.signal,
    )
    if (!result) throw new ApiError(0, 'stream_incomplete', 'The reply was cut off. Please try again.')

    // The backend saved both messages. Show them right away, then refetch in the
    // background to pick up server-side changes (the first message sets the title).
    opts.onSaved?.(result)
    const { user_message, assistant_message } = result
    qc.setQueryData<Conversation>(chatKeys.conversation(id), (old) =>
      old ? { ...old, messages: [...old.messages, user_message, assistant_message] } : old,
    )
    void qc.invalidateQueries({ queryKey: ['chat'] }) // the list and this conversation
    void qc.invalidateQueries({ queryKey: ['traces', 'list'] })
    return result
  }
}

// ---------- traces ----------

export const useTraces = () =>
  useQuery({ queryKey: ['traces', 'list'], queryFn: () => api.get<TraceSummary[]>('/api/traces', { limit: 100 }) })

export const useTrace = (id: number) =>
  useQuery({
    queryKey: ['traces', id],
    queryFn: () => api.get<TraceDetail>(`/api/traces/${id}`),
    staleTime: Infinity, // a saved trace never changes
  })
