import { useState } from 'react'

import { useProducts, useUpdateProduct } from '../api/hooks'
import type { Product, ProductCategory } from '../api/types'
import { PRODUCT_CATEGORIES } from '../api/types'
import { SearchInput } from '../components/SearchInput'
import {
  Button,
  Empty,
  ErrorState,
  FilterBar,
  Input,
  Loading,
  PageHeader,
  Pagination,
  Panel,
  Select,
  Table,
  Td,
  cx,
  selectChrome,
} from '../components/ui'
import { label, money } from '../lib/format'
import { useUrlFilters } from '../lib/useUrlFilters'

const STOCK = ['true', 'false'] as const

export function Products() {
  const { values, page, set, setPage } = useUrlFilters(['q', 'category', 'in_stock'] as const)
  const q = useProducts({
    q: values.q,
    category: values.category,
    in_stock: values.in_stock || undefined,
    page,
    page_size: 25,
  })

  return (
    <>
      <PageHeader title="Products" subtitle="The catalog. Edit stock inline; archived products can't be ordered." />
      <FilterBar>
        <SearchInput value={values.q} onChange={(v) => set('q', v)} placeholder="Search name or SKU" />
        <Select<ProductCategory>
          value={values.category as ProductCategory | ''}
          onChange={(v) => set('category', v)}
          options={PRODUCT_CATEGORIES}
          placeholder="All categories"
          aria-label="Category"
        />
        <select
          value={values.in_stock}
          onChange={(e) => set('in_stock', e.target.value)}
          aria-label="Stock"
          className={`h-8 rounded-md border border-line bg-surface px-2.5 text-[13px] text-ink focus:border-cobalt focus:outline-none ${selectChrome}`}
        >
          <option value="">Any stock</option>
          {STOCK.map((s) => (
            <option key={s} value={s}>
              {s === 'true' ? 'In stock' : 'Sold out'}
            </option>
          ))}
        </select>
      </FilterBar>

      <Panel flush>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data.items.length === 0 ? (
          <Empty>No products match these filters.</Empty>
        ) : (
          <>
            <Table head={['Product', 'SKU', 'Category', 'Price', 'Stock', '']}>
              {q.data.items.map((p) => (
                <ProductRow key={p.id} p={p} />
              ))}
            </Table>
            <Pagination page={q.data.page} pages={q.data.pages} total={q.data.total} onPage={setPage} />
          </>
        )}
      </Panel>
    </>
  )
}

function ProductRow({ p }: { p: Product }) {
  const update = useUpdateProduct()
  const [stock, setStock] = useState<string | null>(null)
  const editing = stock !== null
  const parsed = Number(stock)
  const valid = editing && stock !== '' && Number.isInteger(parsed) && parsed >= 0

  return (
    <tr className={cx(!p.is_active && 'opacity-55')}>
      <Td>
        <div className="font-medium">{p.name}</div>
        {!p.is_active && <div className="text-[12px] text-muted-foreground">Archived</div>}
      </Td>
      <Td className="font-mono text-[12.5px] text-muted-foreground">{p.sku}</Td>
      <Td className="text-muted-foreground">{label(p.category)}</Td>
      <Td className="num">{money(p.price_cents)}</Td>
      <Td>
        {editing ? (
          <form
            className="flex items-center gap-1.5"
            onSubmit={(e) => {
              e.preventDefault()
              if (valid) update.mutate({ id: p.id, stock: parsed }, { onSuccess: () => setStock(null) })
            }}
          >
            <Input
              autoFocus
              inputMode="numeric"
              value={stock}
              onChange={(e) => setStock(e.target.value)}
              onKeyDown={(e) => e.key === 'Escape' && setStock(null)}
              className="num w-20"
              aria-label={`Stock for ${p.name}`}
            />
            <Button type="submit" variant="primary" disabled={!valid || update.isPending}>
              Save
            </Button>
          </form>
        ) : (
          <button
            onClick={() => setStock(String(p.stock))}
            className={cx(
              'num cursor-pointer rounded px-1.5 py-0.5 hover:bg-sunken',
              p.stock === 0 ? 'font-medium text-danger' : p.stock <= 5 ? 'font-medium text-st-amber' : '',
            )}
            title="Edit stock"
          >
            {p.stock === 0 ? 'Sold out' : p.stock}
          </button>
        )}
      </Td>
      <Td className="text-right">
        <Button
          variant="ghost"
          disabled={update.isPending}
          onClick={() => update.mutate({ id: p.id, is_active: !p.is_active })}
        >
          {p.is_active ? 'Archive' : 'Restore'}
        </Button>
      </Td>
    </tr>
  )
}
