import { lazy } from 'react'

// Markdown parsing is lazy-loaded so it stays out of the main bundle.
// Call preloadMarkdown() early so the first streamed reply already renders formatted.
const loadMarkdown = () => import('./ChatMarkdown')
export const ChatMarkdown = lazy(loadMarkdown)
export const preloadMarkdown = () => void loadMarkdown()
