import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, Copy, Plug, Sparkles, Scissors, Layers, X } from 'lucide-react'
import {
  buildAgentMcpPrompt,
  buildMcpConfigJson,
  resolveMcpEndpointUrl,
  type McpToolPreset,
} from '../lib/mcpPrompt'

interface ConnectMcpModalProps {
  open: boolean
  onClose: () => void
}

async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Fallback below for HTTP LAN origins where Clipboard API is restricted.
    }
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  let copied = false
  try {
    copied = document.execCommand('copy')
  } finally {
    document.body.removeChild(textarea)
  }
  return copied
}

const PRESETS: { id: McpToolPreset; label: string; icon: typeof Layers }[] = [
  { id: 'all', label: 'All Tools', icon: Layers },
  { id: 'generate', label: 'Image Generator', icon: Sparkles },
  { id: 'remove-background', label: 'Background Remover', icon: Scissors },
]

export default function ConnectMcpModal({ open, onClose }: ConnectMcpModalProps) {
  const [endpointUrl, setEndpointUrl] = useState(() =>
    resolveMcpEndpointUrl(import.meta.env.VITE_API_URL, window.location.hostname),
  )
  const [token, setToken] = useState('')
  const [preset, setPreset] = useState<McpToolPreset>('all')
  const [activeTab, setActiveTab] = useState<'prompt' | 'config'>('prompt')
  const [copiedContent, setCopiedContent] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [open, onClose])

  const content =
    activeTab === 'prompt'
      ? buildAgentMcpPrompt({ endpointUrl, token, preset })
      : buildMcpConfigJson(endpointUrl, token)

  const copied = copiedContent === content

  const handleCopy = async () => {
    const ok = await copyText(content)
    if (ok) {
      setCopiedContent(content)
      setTimeout(() => setCopiedContent((prev) => (prev === content ? null : prev)), 2000)
    }
  }

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.16 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-2xl max-h-[90dvh] flex flex-col rounded-2xl border border-border bg-card shadow-2xl overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/25">
                  <Plug size={18} />
                </div>
                <div>
                  <h2 className="text-sm font-bold tracking-wide text-foreground uppercase font-mono">
                    Connect MCP
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    Streamable HTTP MCP server for AI agents (Image Generator &amp; Background Remover)
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close MCP dialog"
                className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <X size={16} />
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4 custom-scrollbar">
              {/* Endpoint & Token inputs */}
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <label className="block text-[11px] font-mono uppercase text-muted-foreground">
                    MCP Endpoint URL
                  </label>
                  <input
                    type="text"
                    value={endpointUrl}
                    onChange={(e) => setEndpointUrl(e.target.value)}
                    placeholder="http://192.168.2.133:8281/mcp"
                    className="w-full rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-[11px] font-mono uppercase text-muted-foreground">
                    Service Token (Optional)
                  </label>
                  <input
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="<MAPIC_SERVICE_TOKEN>"
                    autoComplete="off"
                    className="w-full rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>

              <p className="text-[11px] text-muted-foreground font-mono">
                Token only fills the snippet in your browser memory — leave empty to keep{' '}
                <span className="text-foreground">&lt;MAPIC_SERVICE_TOKEN&gt;</span> placeholder.
              </p>

              {/* Preset & Tabs */}
              <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                <div className="flex flex-wrap gap-1.5">
                  {PRESETS.map((item) => {
                    const Icon = item.icon
                    const selected = preset === item.id
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setPreset(item.id)}
                        className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-mono transition-all ${
                          selected
                            ? 'bg-primary/15 text-primary ring-1 ring-primary/40'
                            : 'bg-muted/30 text-muted-foreground hover:bg-muted hover:text-foreground'
                        }`}
                      >
                        <Icon size={12} />
                        <span>{item.label}</span>
                      </button>
                    )
                  })}
                </div>

                <div className="flex rounded-lg border border-border bg-muted/20 p-0.5 text-[11px] font-mono">
                  <button
                    type="button"
                    onClick={() => setActiveTab('prompt')}
                    className={`rounded-md px-2.5 py-1 transition-colors ${
                      activeTab === 'prompt'
                        ? 'bg-foreground text-background font-bold'
                        : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    Agent Prompt
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab('config')}
                    className={`rounded-md px-2.5 py-1 transition-colors ${
                      activeTab === 'config'
                        ? 'bg-foreground text-background font-bold'
                        : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    MCP Config (JSON)
                  </button>
                </div>
              </div>

              {/* Snippet preview */}
              <div className="relative rounded-xl border border-border bg-black/50">
                <pre className="max-h-[260px] overflow-auto p-4 text-xs font-mono leading-relaxed text-white/85 whitespace-pre-wrap break-words custom-scrollbar">
                  {content}
                </pre>
              </div>
            </div>

            {/* Footer */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-muted/15 px-5 py-3.5">
              <div className="text-[11px] font-mono text-muted-foreground">
                Tools: <span className="text-foreground/80">generate_image</span>,{' '}
                <span className="text-foreground/80">remove_background</span>,{' '}
                <span className="text-foreground/80">get_model_status</span>
              </div>
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-xs font-mono font-bold text-primary-foreground transition-all hover:bg-primary/90 active:scale-[0.98]"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
                <span>
                  {copied
                    ? 'COPIED'
                    : activeTab === 'prompt'
                      ? 'COPY AGENT PROMPT'
                      : 'COPY MCP CONFIG'}
                </span>
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
