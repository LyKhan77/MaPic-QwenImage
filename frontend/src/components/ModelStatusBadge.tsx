import { motion, AnimatePresence } from 'framer-motion'
import { Power, Play, RefreshCw } from 'lucide-react'
import type { ModelStatus } from '../lib/api'

interface ModelStatusBadgeProps {
  status: ModelStatus
  onLoad?: () => void
  onUnload?: () => void
  segmentIndex?: number
  segmentProgress?: number
  message?: string
  elapsed?: number
}

const SEGMENTS = [
  { key: 'preflight', label: 'Pre-flight' },
  { key: 'weights', label: 'Weights' },
  { key: 'optimize', label: 'Optimize' },
  { key: 'finalize', label: 'Finalize' },
]

export default function ModelStatusBadge({
  status,
  onLoad,
  onUnload,
  segmentIndex = 0,
  segmentProgress = 0,
  message = '',
  elapsed = 0,
}: ModelStatusBadgeProps) {
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

  return (
    <motion.div
      layout
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      className="group flex items-center gap-2.5 px-4 py-2 rounded-full bg-white/[0.03] ring-1 ring-white/10 transition-all hover:bg-white/[0.06]"
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
      <span className="text-[10px] tracking-widest text-white/35 uppercase">
        Model
      </span>

      {/* Segments */}
      {isOffline ? (
        <div className="flex gap-[3px]">
          <div className="h-1.5 w-8 rounded-full bg-red-400/15 border border-red-400/50" />
        </div>
      ) : isIdle ? (
        <div className="flex gap-[3px]">
          {SEGMENTS.map((seg) => (
            <div key={seg.key} className="h-1.5 w-8 rounded-full border border-white/[0.06]" />
          ))}
        </div>
      ) : (
        <div className="flex gap-[3px] items-center">
          {SEGMENTS.map((seg, i) => {
            const isDone = isLoading ? i < segmentIndex : isReady
            const isActive = isLoading && i === segmentIndex
            const isErrorSegment = isError && i === segmentIndex

            if (isErrorSegment) {
              return (
                <div
                  key={seg.key}
                  className="h-1.5 w-8 rounded-full bg-red-400/15 border border-red-400/50"
                  title={seg.label}
                />
              )
            }

            if (isDone) {
              return (
                <div
                  key={seg.key}
                  className="h-1.5 w-8 rounded-full bg-emerald-400/30 border border-emerald-400/50"
                  title={seg.label}
                />
              )
            }

            if (isActive) {
              return (
                <div
                  key={seg.key}
                  className="h-1.5 w-8 rounded-full bg-cyan-400/[0.06] border border-cyan-400/35 relative overflow-hidden"
                  style={{ boxShadow: '0 0 6px rgba(0,240,255,0.25)' }}
                  title={seg.label}
                >
                  <div
                    className="absolute inset-0 bg-cyan-400/35 transition-all duration-500 ease-out"
                    style={{ width: `${Math.min(100, Math.max(0, segmentProgress * 100))}%` }}
                  />
                </div>
              )
            }

            return (
              <div
                key={seg.key}
                className="h-1.5 w-8 rounded-full bg-white/[0.015] border border-white/[0.07]"
                title={seg.label}
              />
            )
          })}
        </div>
      )}

      {/* Status label + message */}
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

        {isLoading && message && (
          <motion.span
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -4 }}
            transition={{ duration: 0.2 }}
            className="text-[10px] text-amber-400/80 normal-case tracking-normal whitespace-nowrap flex items-center gap-1"
          >
            <span>{message}</span>
            {elapsed > 0 && <span className="opacity-70 font-mono">({formatTime(elapsed)})</span>}
          </motion.span>
        )}
      </AnimatePresence>

      {/* Retry button (error/offline) */}
      {(isOffline || isError) && onLoad && (
        <button
          onClick={onLoad}
          title="Retry loading model"
          className="ml-2 flex items-center gap-1 text-[10px] text-red-400/50 hover:text-red-400 transition-colors"
        >
          <RefreshCw size={11} />
          <span className="font-bold uppercase">Retry</span>
        </button>
      )}

      {/* Unload button (ready, hover reveal) */}
      {isReady && onUnload && (
        <button
          onClick={onUnload}
          title="Unload model from GPU memory"
          className="ml-2 flex items-center gap-1 overflow-hidden max-w-0 opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 transition-all duration-300 text-white/30 hover:text-red-400"
        >
          <Power size={12} />
          <span className="text-[10px] font-mono font-bold uppercase whitespace-nowrap">Unload</span>
        </button>
      )}

      {/* Load button (idle, hover reveal) */}
      {isIdle && onLoad && (
        <button
          onClick={onLoad}
          title="Load model into GPU memory"
          className="ml-2 flex items-center gap-1 overflow-hidden max-w-0 opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 transition-all duration-300 text-emerald-400 hover:text-emerald-300"
        >
          <Play size={12} />
          <span className="text-[10px] font-mono font-bold uppercase whitespace-nowrap">Load</span>
        </button>
      )}
    </motion.div>
  )
}
