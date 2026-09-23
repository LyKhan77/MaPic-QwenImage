import { motion, AnimatePresence } from 'framer-motion'
import { Power, Play, RefreshCw } from 'lucide-react'
import type { ModelStatus } from '../lib/api'

interface ModelStatusBadgeProps {
  status: ModelStatus
  onLoad?: () => void
  onUnload?: () => void
  elapsed?: number
}

export default function ModelStatusBadge({
  status,
  onLoad,
  onUnload,
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

      {/* Elapsed timer during loading */}
      {isLoading && elapsed > 0 && (
        <span className="text-[10px] text-amber-400/60 font-mono">
          {formatTime(elapsed)}
        </span>
      )}

      {/* Retry button (error/offline) */}
      {(isOffline || isError) && onLoad && (
        <button
          onClick={onLoad}
          title="Retry loading model"
          className="relative ml-2 flex items-center gap-1 text-[10px] text-red-400/50 hover:text-red-400 transition-colors after:absolute after:-inset-x-2 after:-inset-y-4 after:content-[''] lg:after:hidden"
        >
          <RefreshCw size={11} />
          <span className="font-bold uppercase">Retry</span>
        </button>
      )}

      {/* Unload button (ready, hover reveal).
          ponytail: hover-only on mobile too — the backend auto-loads on demand, so this stays a
          desktop convenience instead of widening the badge past the 390px viewport. */}
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

      {/* Shimmer keyframes */}
      <style>{`
        @keyframes shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
      `}</style>
    </motion.div>
  )
}
