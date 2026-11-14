// Mirrors app/schemas.py on the backend. Money is always integer cents.

export type CustomerTier = 'standard' | 'gold' | 'platinum'
export type ProductCategory = 'electronics' | 'home' | 'apparel' | 'books' | 'sports' | 'beauty'
export type OrderStatus = 'pending' | 'paid' | 'shipped' | 'delivered' | 'cancelled' | 'refunded'
export type TicketStatus = 'open' | 'pending' | 'resolved' | 'closed'
export type TicketPriority = 'low' | 'medium' | 'high' | 'urgent'
export type TicketCategory = 'billing' | 'shipping' | 'product' | 'account' | 'other'
export type RefundReason =
  | 'damaged'
  | 'not_received'
  | 'wrong_item'
  | 'not_as_described'
  | 'changed_mind'
  | 'other'
export type MessageAuthor = 'customer' | 'agent' | 'system'

export const ORDER_STATUSES: OrderStatus[] = ['pending', 'paid', 'shipped', 'delivered', 'cancelled', 'refunded']
export const TICKET_STATUSES: TicketStatus[] = ['open', 'pending', 'resolved', 'closed']
export const TICKET_PRIORITIES: TicketPriority[] = ['low', 'medium', 'high', 'urgent']
export const TICKET_CATEGORIES: TicketCategory[] = ['billing', 'shipping', 'product', 'account', 'other']
export const PRODUCT_CATEGORIES: ProductCategory[] = ['electronics', 'home', 'apparel', 'books', 'sports', 'beauty']
export const CUSTOMER_TIERS: CustomerTier[] = ['standard', 'gold', 'platinum']
export const REFUND_REASONS: RefundReason[] = [
  'damaged',
  'not_received',
  'wrong_item',
  'not_as_described',
  'changed_mind',
  'other',
]

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface Customer {
  id: number
  name: string
  email: string
  phone: string | null
  city: string | null
  country: string | null
  tier: CustomerTier
  created_at: string
  updated_at: string
}

export interface CustomerDetail extends Customer {
  order_count: number
  lifetime_value_cents: number
  open_ticket_count: number
}

export interface CustomerInput {
  name: string
  email: string
  phone?: string | null
  city?: string | null
  country?: string | null
  tier?: CustomerTier
}

export interface Product {
  id: number
  sku: string
  name: string
  description: string
  category: ProductCategory
  price_cents: number
  stock: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ProductUpdate {
  name?: string
  description?: string
  category?: ProductCategory
  price_cents?: number
  stock?: number
  is_active?: boolean
}

export interface OrderSummary {
  id: number
  number: string
  customer_id: number
  status: OrderStatus
  total_cents: number
  currency: string
  placed_at: string
  item_count: number
}

export interface OrderItem {
  id: number
  product_id: number
  product_name: string
  unit_price_cents: number
  quantity: number
  line_total_cents: number
}

export interface Refund {
  id: number
  order_id: number
  amount_cents: number
  reason: RefundReason
  note: string
  created_at: string
}

export interface Order {
  id: number
  number: string
  customer_id: number
  status: OrderStatus
  total_cents: number
  refunded_cents: number
  refundable_cents: number
  currency: string
  shipping_address: string
  tracking_number: string | null
  placed_at: string
  shipped_at: string | null
  delivered_at: string | null
  items: OrderItem[]
  refunds: Refund[]
  customer: Customer
}

export interface TicketMessage {
  id: number
  author: MessageAuthor
  body: string
  created_at: string
}

export interface TicketSummary {
  id: number
  customer_id: number
  order_id: number | null
  subject: string
  status: TicketStatus
  priority: TicketPriority
  category: TicketCategory
  assignee: string | null
  created_at: string
  updated_at: string
}

export interface Ticket extends TicketSummary {
  customer: Customer
  messages: TicketMessage[]
}

export interface TicketUpdate {
  status?: TicketStatus
  priority?: TicketPriority
  category?: TicketCategory
  assignee?: string | null
}

export interface StatsOverview {
  customers: number
  products: number
  orders: number
  revenue_cents: number
  refunded_cents: number
  open_tickets: number
  orders_by_status: Record<OrderStatus, number>
  tickets_by_status: Record<TicketStatus, number>
  revenue_last_30_days: { date: string; revenue_cents: number; orders: number }[]
  low_stock_products: Product[]
}

export interface SeedRequest {
  seed: number
  customers: number
  products: number
  orders: number
  tickets: number
  reset: boolean
}

export interface SeedResult {
  seed: number
  customers: number
  products: number
  orders: number
  tickets: number
  refunds: number
  scenarios: string[]
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> }
}
