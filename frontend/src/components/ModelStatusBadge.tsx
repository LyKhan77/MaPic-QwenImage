import { motion, AnimatePresence } from 'framer-motion'
import { Power, Play } from 'lucide-react'
import type { ModelStatus } from '../lib/api'

interface ModelStatusBadgeProps {
  status: ModelStatus
  onLoad?: () => void
  onUnload?: () => void
  progress?: number
  message?: string
  elapsed?: number
}

const statusConfig: Record<ModelStatus, { label: string; color: string; pulse: boolean }> = {
  ready: { label: 'READY', color: 'bg-emerald-400 shadow-emerald-400/50', pulse: false },
  loading: { label: 'LOADING', color: 'bg-amber-400 shadow-amber-400/50', pulse: true },
  offline: { label: 'OFFLINE', color: 'bg-red-400 shadow-red-400/50', pulse: true },
  unloaded: { label: 'IDLE', color: 'bg-gray-400 shadow-gray-400/50', pulse: false },
}

export default function ModelStatusBadge({ status, onLoad, onUnload, progress = 0, message = '', elapsed = 0 }: ModelStatusBadgeProps) {
  const config = statusConfig[status] || statusConfig.offline
  const ringRadius = 8
  const ringCircumference = 2 * Math.PI * ringRadius
  const clampedProgress = Math.min(100, Math.max(0, progress))
  const ringDashOffset = ringCircumference * (1 - clampedProgress / 100)

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <motion.div
      layout
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      className="group flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 ring-1 ring-white/10 transition-all hover:bg-white/10"
    >
      {status === 'loading' ? (
        <span className="relative flex h-5 w-5 items-center justify-center">
          <svg
            className="absolute inset-0 h-5 w-5 animate-[spin_3s_linear_infinite]"
            viewBox="0 0 20 20"
            aria-hidden="true"
          >
            <g transform="rotate(-90 10 10)">
              <circle
                cx="10"
                cy="10"
                r={ringRadius}
                fill="none"
                stroke="rgba(255,255,255,0.1)"
                strokeWidth="2"
              />
              <circle
                cx="10"
                cy="10"
                r={ringRadius}
                fill="none"
                stroke="#fbbf24"
                strokeWidth="2"
                strokeLinecap="round"
                strokeDasharray={ringCircumference}
                strokeDashoffset={ringDashOffset}
              />
            </g>
          </svg>
          <span className="absolute h-2 w-2 rounded-full bg-amber-400 shadow-amber-400/50 opacity-75 animate-ping" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-400 shadow-[0_0_6px] shadow-amber-400/50" />
        </span>
      ) : (
        <span className="relative flex h-2 w-2">
          {config.pulse && (
            <span className={`absolute inset-0 rounded-full ${config.color} opacity-75 animate-ping`} />
          )}
          <motion.span
            layout
            className={`relative inline-flex h-2 w-2 rounded-full ${config.color} shadow-[0_0_6px]`}
          />
        </span>
      )}
      <span className="text-[10px] font-mono tracking-widest text-muted-foreground uppercase">
        Model
      </span>
      <AnimatePresence mode="wait">
        <motion.span
          key={status}
          initial={{ y: -6, opacity: 0, filter: 'blur(4px)' }}
          animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
          exit={{ y: 6, opacity: 0, filter: 'blur(4px)' }}
          transition={{ duration: 0.2 }}
          className={`text-[10px] font-mono tracking-widest font-bold ${
            status === 'ready' ? 'text-emerald-400'
              : status === 'loading' ? 'text-amber-400'
              : status === 'unloaded' ? 'text-gray-400'
              : 'text-red-400'
          }`}
        >
          {config.label}
        </motion.span>

        {status === 'loading' && message && (
          <motion.span
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -4 }}
            transition={{ duration: 0.2 }}
            className="ml-1.5 text-[11px] text-amber-400/80 normal-case tracking-normal whitespace-nowrap flex items-center gap-1"
          >
            <span>{message}</span>
            {elapsed > 0 && <span className="opacity-70 font-mono">({formatTime(elapsed)})</span>}
          </motion.span>
        )}
      </AnimatePresence>

      {/* Action Buttons */}
      {status === 'ready' && onUnload && (
        <button 
          onClick={onUnload}
          title="Unload model from GPU memory"
          className="ml-2 flex items-center gap-1 overflow-hidden max-w-0 opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 transition-all duration-300 ease-in-out text-muted-foreground hover:text-red-400"
        >
          <Power size={12} />
          <span className="text-[10px] font-mono font-bold uppercase whitespace-nowrap">
            Unload
          </span>
        </button>
      )}

      {status === 'unloaded' && onLoad && (
        <button 
          onClick={onLoad}
          title="Load model into GPU memory"
          className="ml-2 flex items-center gap-1 overflow-hidden max-w-0 opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 transition-all duration-300 ease-in-out text-emerald-400 hover:text-emerald-300"
        >
          <Play size={12} />
          <span className="text-[10px] font-mono font-bold uppercase whitespace-nowrap">
            Load
          </span>
        </button>
      )}
    </motion.div>
  )
}
