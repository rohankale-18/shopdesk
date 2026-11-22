import { isValidElement, useMemo, type ReactElement, type ReactNode } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { ToolData } from '@/api/types'
import { ChatChart } from './ChatChart'

// react-markdown passes its syntax-tree `node` to every component; keep it off the HTML element.
const withoutNode = <T extends { node?: unknown }>(props: T) => {
  const rest = { ...props }
  delete rest.node
  return rest
}

type CodeElement = ReactElement<{ className?: string; children?: ReactNode }>

// Loaded lazily (see lazyMarkdown.ts), so the Markdown parser stays out of the main bundle.
export default function ChatMarkdown({
  children,
  data = [],
  streaming = false,
}: {
  children: string
  /** The reply's tool results that ```chart blocks can point at. */
  data?: ToolData[]
  streaming?: boolean
}) {
  const components = useMemo<Components>(
    () => ({
      a: (props) => <a {...withoutNode(props)} target="_blank" rel="noreferrer" />,
      // A scrollable frame around tables (styled in index.css).
      table: (props) => (
        <div className="chat-table">
          <table {...withoutNode(props)} />
        </div>
      ),
      // A ```chart block becomes a real chart; other code blocks stay as they are.
      pre: (props) => {
        const code = props.children
        if (isValidElement(code) && (code as CodeElement).props.className?.includes('language-chart')) {
          const source = String((code as CodeElement).props.children ?? '')
          return <ChatChart source={source} data={data} streaming={streaming} />
        }
        return <pre {...withoutNode(props)} />
      },
    }),
    [data, streaming],
  )
  return (
    <Markdown remarkPlugins={[remarkGfm]} components={components}>
      {children}
    </Markdown>
  )
}
