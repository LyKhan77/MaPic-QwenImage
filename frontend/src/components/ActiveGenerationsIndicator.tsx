import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { ActiveGeneration } from '../types'
import { cn } from '../lib/utils'

interface ActiveGenerationsIndicatorProps {
  activeGenerations: ActiveGeneration[]
  currentUserId: string
  globalStage: string
  onFocusMyGen: () => void
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function ActiveGenerationsIndicator({
  activeGenerations,
  currentUserId,
  globalStage,
  onFocusMyGen,
}: ActiveGenerationsIndicatorProps) {
  const [isHovered, setIsHovered] = useState(false)
  const showHoverPanel = useCallback(() => setIsHovered(true), [])
  const hideHoverPanel = useCallback(() => setIsHovered(false), [])

  if (activeGenerations.length === 0) return null

  const myGen = activeGenerations.find(g => g.user_id === currentUserId)
  const otherGens = activeGenerations.filter(g => g.user_id !== currentUserId)

  return (
    <div
      className="fixed bottom-4 right-4 z-50"
      onMouseEnter={showHoverPanel}
      onMouseLeave={hideHoverPanel}
    >
      {/* Collapsed pill */}
      <motion.div
        layout
        className={cn(
          "flex items-center gap-2 rounded-full border border-border/50 bg-card/60 backdrop-blur-md px-3 py-1.5 shadow-lg cursor-default select-none",
          isHovered && "bg-card/80"
        )}
      >
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
        </span>
        <span className="text-xs font-mono text-muted-foreground">
          {activeGenerations.length} active
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
              {myGen && (
                <button
                  onClick={onFocusMyGen}
                  className="w-full text-left px-3 py-2.5 hover:bg-primary/10 transition-colors border-b border-border/20 cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-2 w-2 shrink-0">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                    </span>
                    <span className="text-[10px] font-bold text-primary uppercase">You</span>
                  </div>
                  <p className="text-xs font-medium text-foreground mt-1 line-clamp-1">{myGen.prompt}</p>
                  <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
                    {formatElapsed(myGen.elapsed_seconds)} · {globalStage || 'processing'}
                  </p>
                </button>
              )}

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
                    {formatElapsed(gen.elapsed_seconds)}
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
