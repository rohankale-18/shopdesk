import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

// react-markdown passes its syntax-tree `node` to every component; keep it off the HTML element.
const withoutNode = <T extends { node?: unknown }>(props: T) => {
  const rest = { ...props }
  delete rest.node
  return rest
}

const components: Components = {
  a: (props) => <a {...withoutNode(props)} target="_blank" rel="noreferrer" />,
  // A scrollable frame around tables (styled in index.css). Charts will hook in here too.
  table: (props) => (
    <div className="chat-table">
      <table {...withoutNode(props)} />
    </div>
  ),
}

// Loaded lazily (see lazyMarkdown.ts), so the Markdown parser stays out of the main bundle.
export default function ChatMarkdown({ children }: { children: string }) {
  return (
    <Markdown remarkPlugins={[remarkGfm]} components={components}>
      {children}
    </Markdown>
  )
}
