import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Power, Play, RefreshCw, ChevronDown, Cpu, Check } from 'lucide-react'
import type { GpuNodesResponse, ModelStatus } from '../lib/api'
import { canSelectGpuNode, formatGpuShortName, formatVramGb } from '../lib/gpuNodes'

interface ModelStatusBadgeProps {
  status: ModelStatus
  onLoad?: (gpuId?: string) => void
  onUnload?: () => void
  elapsed?: number
  gpuInfo?: GpuNodesResponse
  hasActiveGeneration?: boolean
  onOpenChange?: (open: boolean) => void
}

export default function ModelStatusBadge({
  status,
  onLoad,
  onUnload,
  elapsed = 0,
  gpuInfo,
  hasActiveGeneration = false,
  onOpenChange,
}: ModelStatusBadgeProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  const isLoading = status === 'loading'
  const isReady = status === 'ready'
  const isOffline = status === 'offline'
  const isIdle = status === 'unloaded'
  const isError = (status as string) === 'error'
  const activeGpuId = gpuInfo?.active_gpu ?? gpuInfo?.default_gpu ?? null
  const gpus = gpuInfo?.gpus ?? []

  const setPopoverOpen = useCallback((next: boolean) => {
    setOpen(next)
    onOpenChange?.(next)
  }, [onOpenChange])

  useEffect(() => {
    if (!open) return
    const handlePointerDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setPopoverOpen(false)
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPopoverOpen(false)
    }
    document.addEventListener('mousedown', handlePointerDown)
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [open, setPopoverOpen])

  const handleSelectGpu = (gpuId: string) => {
    if (!onLoad) return
    setPopoverOpen(false)
    onLoad(gpuId)
  }

  return (
    <div ref={containerRef} className="relative">
      <motion.div
        layout
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
        onClick={() => setPopoverOpen(!open)}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        aria-label="Model status and GPU node selector"
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setPopoverOpen(!open)
          }
        }}
        className="group flex cursor-pointer items-center gap-2 px-3.5 py-2 rounded-full bg-white/[0.03] ring-1 ring-white/10 transition-all hover:bg-white/[0.06] sm:gap-2.5 sm:px-4"
      >
        {/* Dot indicator */}
        {isLoading ? (
          <span className="relative flex h-2 w-2">
            <span className="absolute inset-0 rounded-full bg-amber-400 opacity-60 animate-ping" />
            <span className="relative h-2 w-2 rounded-full bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.5)]" />
          </span>
        ) : isReady ? (
          <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]" />
        ) : isOffline || isError ? (
          <span className="h-2 w-2 rounded-full bg-red-400 shadow-[0_0_6px_rgba(248,113,113,0.5)]" />
        ) : (
          <span className="h-2 w-2 rounded-full bg-zinc-500" />
        )}

        {/* Label */}
        <span className="hidden text-[10px] tracking-widest text-white/35 uppercase sm:inline">
          Model
        </span>

        {/* Bar — display:contents at sm+ so it stays a direct flex child; hidden below */}
        <span className="hidden sm:contents">
          {isOffline || isError ? (
            <div className="h-1.5 w-[6.5rem] rounded-full bg-red-400/15 border border-red-400/50" />
          ) : isLoading ? (
            <div className="h-1.5 w-[6.5rem] rounded-full bg-amber-400/[0.06] border border-amber-400/35 relative overflow-hidden">
              <div
                className="absolute inset-0 rounded-full"
                style={{
                  background: 'linear-gradient(90deg, transparent 0%, rgba(251,191,36,0.25) 50%, transparent 100%)',
                  animation: 'shimmer 1.8s ease-in-out infinite',
                  transform: 'translateX(-100%)',
                }}
              />
            </div>
          ) : isReady ? (
            <div className="h-1.5 w-[6.5rem] rounded-full bg-emerald-400/30 border border-emerald-400/50" />
          ) : (
            <div className="h-1.5 w-[6.5rem] rounded-full border border-white/[0.06]" />
          )}
        </span>

        {/* Status label */}
        <AnimatePresence mode="wait">
          <motion.span
            key={status}
            initial={{ y: -6, opacity: 0, filter: 'blur(4px)' }}
            animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
            exit={{ y: 6, opacity: 0, filter: 'blur(4px)' }}
            transition={{ duration: 0.2 }}
            className={`text-[10px] font-mono tracking-widest font-bold ${
              isReady ? 'text-emerald-400'
                : isLoading ? 'text-amber-400'
                : isIdle ? 'text-zinc-500'
                : 'text-red-400'
            }`}
          >
            {isReady ? 'READY' : isLoading ? 'LOADING' : isIdle ? 'IDLE' : isOffline ? 'OFFLINE' : 'ERROR'}
          </motion.span>
        </AnimatePresence>

        {/* Active GPU tag */}
        {activeGpuId && (
          <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-mono text-white/60">
            GPU {activeGpuId}
          </span>
        )}

        {/* Elapsed timer during loading */}
        {isLoading && elapsed > 0 && (
          <span className="text-[10px] text-amber-400/60 font-mono">
            {formatTime(elapsed)}
          </span>
        )}

        {/* Retry button (error/offline) */}
        {(isOffline || isError) && onLoad && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onLoad()
            }}
            title="Retry loading model"
            className="relative ml-1 flex items-center gap-1 text-[10px] text-red-400/50 hover:text-red-400 transition-colors after:absolute after:-inset-x-2 after:-inset-y-4 after:content-[''] lg:after:hidden"
          >
            <RefreshCw size={11} />
            <span className="font-bold uppercase">Retry</span>
          </button>
        )}

        {/* Unload button (ready, hover reveal on desktop). */}
        {isReady && onUnload && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onUnload()
            }}
            title="Unload model from GPU memory"
            className="ml-1 flex items-center gap-1 overflow-hidden max-w-0 opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 transition-all duration-300 text-white/30 hover:text-red-400"
          >
            <Power size={12} />
            <span className="text-[10px] font-mono font-bold uppercase whitespace-nowrap">Unload</span>
          </button>
        )}

        {/* Load button (idle, hover reveal on desktop) */}
        {isIdle && onLoad && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onLoad()
            }}
            title="Load model into GPU memory"
            className="ml-1 flex items-center gap-1 overflow-hidden max-w-0 opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 transition-all duration-300 text-emerald-400 hover:text-emerald-300"
          >
            <Play size={12} />
            <span className="text-[10px] font-mono font-bold uppercase whitespace-nowrap">Load</span>
          </button>
        )}

        <ChevronDown
          size={12}
          className={`text-white/40 transition-transform duration-200 ${open ? 'rotate-180 text-white/70' : ''}`}
        />

        {/* Shimmer keyframes */}
        <style>{`
          @keyframes shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
          }
        `}</style>
      </motion.div>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-full z-50 mt-2 w-[280px] max-w-[calc(100vw-2rem)] rounded-2xl border border-white/10 bg-[#141416]/95 p-3 shadow-2xl backdrop-blur-xl"
          >
            <div className="mb-2 flex items-center justify-between px-1">
              <div className="flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-wider text-white/50">
                <Cpu size={12} />
                <span>GPU Node</span>
              </div>
              <span className="text-[10px] font-mono text-white/35">
                {gpus.length > 0 ? `${gpus.length} node${gpus.length > 1 ? 's' : ''}` : 'No data'}
              </span>
            </div>

            {gpus.length > 0 ? (
              <div className="space-y-1.5">
                {gpus.map((node) => {
                  const selectable = canSelectGpuNode(node, { modelStatus: status, hasActiveGeneration })
                  const isCurrentLoaded = node.active && node.loaded && isReady
                  return (
                    <button
                      key={node.id}
                      type="button"
                      disabled={!selectable}
                      onClick={() => handleSelectGpu(node.id)}
                      title={node.name}
                      className={`w-full rounded-xl border px-3 py-2 text-left transition-all ${
                        node.active
                          ? 'border-emerald-400/35 bg-emerald-400/[0.07]'
                          : 'border-white/[0.07] bg-white/[0.02] hover:bg-white/[0.06]'
                      } disabled:cursor-not-allowed disabled:opacity-55`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="text-xs font-mono font-bold text-white">GPU {node.id}</span>
                          <span className="truncate text-[11px] text-white/60">
                            {formatGpuShortName(node.name)}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          {node.default && (
                            <span className="rounded bg-white/[0.08] px-1.5 py-0.5 text-[9px] font-mono uppercase text-white/55">
                              Default
                            </span>
                          )}
                          {isCurrentLoaded && <Check size={12} className="text-emerald-400" />}
                        </div>
                      </div>
                      <div className="mt-1 flex items-center justify-between text-[10px] font-mono">
                        {node.online ? (
                          <span className="text-white/45">
                            Free {formatVramGb(node.vram_free_mb)} / {formatVramGb(node.vram_total_mb)}
                          </span>
                        ) : (
                          <span className="text-red-400/80">Offline</span>
                        )}
                        <span className={node.active ? 'text-emerald-400/90' : 'text-white/35'}>
                          {isCurrentLoaded ? 'Loaded' : node.active ? 'Selected' : selectable ? 'Switch' : ''}
                        </span>
                      </div>
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5 text-[11px] font-mono text-white/40">
                GPU node metadata unavailable.
              </div>
            )}

            {hasActiveGeneration && (
              <p className="mt-2 px-1 text-[10px] font-mono text-amber-400/80">
                Generation active — GPU switching locked.
              </p>
            )}

            <div className="mt-2.5 flex items-center gap-2 border-t border-white/[0.08] pt-2.5">
              {isReady && onUnload ? (
                <button
                  type="button"
                  disabled={hasActiveGeneration}
                  onClick={() => {
                    setPopoverOpen(false)
                    onUnload()
                  }}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-white/[0.05] px-3 py-2 text-[11px] font-mono font-bold text-red-300 transition-colors hover:bg-red-500/15 disabled:opacity-50"
                >
                  <Power size={12} />
                  <span>Unload VRAM</span>
                </button>
              ) : onLoad ? (
                <button
                  type="button"
                  disabled={isLoading || hasActiveGeneration}
                  onClick={() => {
                    setPopoverOpen(false)
                    onLoad(activeGpuId ?? undefined)
                  }}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-500/20 px-3 py-2 text-[11px] font-mono font-bold text-emerald-300 transition-colors hover:bg-emerald-500/30 disabled:opacity-50"
                >
                  <Play size={12} />
                  <span>{isLoading ? 'Loading...' : `Load${activeGpuId ? ` GPU ${activeGpuId}` : ''}`}</span>
                </button>
              ) : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
