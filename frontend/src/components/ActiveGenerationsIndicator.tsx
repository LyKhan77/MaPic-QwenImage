import { useState, useCallback, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { ActiveGeneration } from '../types'
import { cn } from '../lib/utils'
import { getDisplayedGenerations } from '../lib/activeGenerationState'

interface ActiveGenerationsIndicatorProps {
  activeGenerations: ActiveGeneration[]
  pendingGenerations: Record<string, { prompt: string; startedAt: number }>
  currentUserId: string
  globalStage: string
  onFocusMyGen: () => void
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatGenerationStatus(gen: ActiveGeneration, globalStage?: string): string {
  if (gen.status === 'queued') return 'queued'
  if (gen.status === 'saving') return `${formatElapsed(gen.elapsed_seconds)} · saving`
  return `${formatElapsed(gen.elapsed_seconds)} · ${globalStage || 'processing'}`
}

export default function ActiveGenerationsIndicator({
  activeGenerations,
  pendingGenerations,
  currentUserId,
  globalStage,
  onFocusMyGen,
}: ActiveGenerationsIndicatorProps) {
  const [isHovered, setIsHovered] = useState(false)
  const [now, setNow] = useState(0)
  const showHoverPanel = useCallback(() => setIsHovered(true), [])
  const hideHoverPanel = useCallback(() => setIsHovered(false), [])

  useEffect(() => {
    const updateNow = () => setNow(Date.now())
    updateNow()
    const intervalId = window.setInterval(updateNow, 1000)
    return () => window.clearInterval(intervalId)
  }, [])

  const displayedGenerations = getDisplayedGenerations(activeGenerations, pendingGenerations, currentUserId, now)

  if (displayedGenerations.length === 0) return null

  const myGens = displayedGenerations.filter(g => g.user_id === currentUserId)
  const otherGens = displayedGenerations.filter(g => g.user_id !== currentUserId)

  return (
    <div className="fixed bottom-24 right-4 z-50 md:bottom-4"
      onMouseEnter={showHoverPanel}
      onMouseLeave={hideHoverPanel}
      onClick={() => setIsHovered(v => !v)}
    >
      {/* Collapsed pill */}
      <motion.div
        layout
        className={cn(
          "flex items-center gap-2 rounded-full border border-border/50 bg-card/60 backdrop-blur-md px-3 py-1.5 shadow-lg cursor-pointer select-none",
          isHovered && "bg-card/80"
        )}
      >
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
        </span>
        <span className="text-xs font-mono text-muted-foreground">
          {displayedGenerations.length}/10 active
        </span>
      </motion.div>

      {/* Hover panel */}
      <AnimatePresence>
        {isHovered && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className="absolute bottom-full right-0 mb-2 w-64 rounded-xl border border-border/50 bg-card/80 backdrop-blur-md shadow-xl overflow-hidden"
          >
            <div className="px-3 py-2 border-b border-border/30">
              <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/60">
                Active Generations
              </span>
            </div>

            <div className="max-h-60 overflow-y-auto">
              {/* User's own generation */}
              {myGens.map((gen, index) => (
                <button
                  key={gen.id}
                  onClick={onFocusMyGen}
                  className="w-full text-left px-3 py-2.5 hover:bg-primary/10 transition-colors border-b border-border/20 cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-2 w-2 shrink-0">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                    </span>
                    <span className="text-[10px] font-bold text-primary uppercase">
                      You {myGens.length > 1 ? `#${index + 1}` : ''}
                    </span>
                  </div>
                  <p className="text-xs font-medium text-foreground mt-1 line-clamp-1">{gen.prompt}</p>
                  <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
                    {formatGenerationStatus(gen, globalStage)}
                  </p>
                </button>
              ))}

              {/* Other users' generations */}
              {otherGens.map(gen => (
                <div
                  key={gen.id}
                  className="px-3 py-2.5 border-b border-border/10 last:border-b-0"
                >
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/30 shrink-0" />
                    <span className="text-[10px] text-muted-foreground/60">
                      {gen.user_id.slice(0, 8)}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground/60 mt-1 line-clamp-1">{gen.prompt}</p>
                  <p className="text-[10px] font-mono text-muted-foreground/40 mt-0.5">
                    {formatGenerationStatus(gen)}
                  </p>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
