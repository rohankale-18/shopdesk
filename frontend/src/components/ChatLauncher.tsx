import { Link, useMatch } from 'react-router-dom'
import { MessageCircleIcon } from 'lucide-react'

/** Floating button (bottom right) that opens the assistant page. Hidden on that page. */
export function ChatLauncher() {
  const onAssistant = useMatch({ path: '/assistant', end: false })
  if (onAssistant) return null
  return (
    <Link
      to="/assistant"
      aria-label="Open assistant"
      title="Assistant"
      className="fixed right-5 bottom-5 z-40 grid size-14 place-items-center rounded-full bg-primary text-primary-foreground shadow-[0_8px_24px_-6px_rgb(20_30_80/0.45)] transition-transform duration-200 hover:scale-105 hover:brightness-110"
    >
      <MessageCircleIcon className="size-6" />
    </Link>
  )
}
