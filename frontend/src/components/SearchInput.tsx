import { useEffect, useState } from 'react'

import { useDebounced } from '../lib/useUrlFilters'
import { Input } from './ui'

/** Search box that updates the URL 250ms after typing stops. */
export function SearchInput({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  const [text, setText] = useState(value)
  const debounced = useDebounced(text)

  useEffect(() => setText(value), [value])
  useEffect(() => {
    if (debounced !== value) onChange(debounced)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])

  return (
    <Input
      type="search"
      value={text}
      onChange={(e) => setText(e.target.value)}
      placeholder={placeholder}
      aria-label={placeholder}
      className="w-full sm:w-72"
    />
  )
}
