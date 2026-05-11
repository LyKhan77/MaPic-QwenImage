import { useState, useEffect, useMemo } from 'react'
import { motion } from 'framer-motion'
import { api } from '../lib/api'

interface GenerationStageBadgeProps {
  isLoading: boolean
  steps: number
  numRefImages: number
}

interface StageInfo {
  key: string
  label: string
}

const STAGES: StageInfo[] = [
  { key: 'warmup', label: 'Pipeline warmup' },
  { key: 'encoding', label: 'Prompt encoding' },
  { key: 'ar_sampling', label: 'AR sampling' },
  { key: 'diffusion', label: 'Diffusion denoising' },
  { key: 'decoding', label: 'VAE decoding' },
]

const TIME_SLICES = [
  { key: 'warmup', end: 0.10 },
  { key: 'encoding', end: 0.25 },
  { key: 'ar_sampling', end: 0.40 },
  { key: 'diffusion', end: 0.90 },
  { key: 'decoding', end: 1.00 },
]

function estimateTotalSeconds(steps: number, numRefImages: number): number {
  const base = 45
  const diffusion = steps * 4.5
  const i2iOverhead = numRefImages > 0 ? 25 + numRefImages * 15 : 0
  return Math.round(base + diffusion + i2iOverhead)
}

function getSimulatedStage(elapsed: number, total: number): string {
  const progress = total > 0 ? elapsed / total : 0
  for (const slice of TIME_SLICES) {
    if (progress <= slice.end) return slice.key
  }
  return 'decoding'
}

export default function GenerationStageBadge({
  isLoading,
  steps,
  numRefImages,
}: GenerationStageBadgeProps) {
  const [elapsed, setElapsed] = useState(0)
  const [backendStage, setBackendStage] = useState('idle')

  const estimatedTotal = useMemo(
    () => estimateTotalSeconds(steps, numRefImages),
    [steps, numRefImages]
  )

  useEffect(() => {
    if (!isLoading) return

    const timer = setInterval(() => {
      setElapsed((prev) => prev + 1)
    }, 1000)

    const poll = setInterval(async () => {
      try {
        const data = await api.getGenerationStatus()
        if (data.stage && data.stage !== 'idle') {
          setBackendStage(data.stage)
        }
      } catch {
        // ignore polling errors
      }
    }, 1200)

    return () => {
      clearInterval(timer)
      clearInterval(poll)
    }
  }, [isLoading])

  if (!isLoading) return null

  const activeStage =
    backendStage !== 'idle' ? backendStage : getSimulatedStage(elapsed, estimatedTotal)

  const activeIndex = STAGES.findIndex((s) => s.key === activeStage)

  return (
    <motion.div
      initial={{ opacity: 0, y: -6, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -6, scale: 0.95 }}
      transition={{ duration: 0.3 }}
      className="w-48 rounded-xl border border-border/50 bg-card/30 backdrop-blur-md px-3 py-2.5 shadow-lg"
    >
      <div className="mb-1.5 text-[9px] font-mono uppercase tracking-widest text-muted-foreground/60">
        Stage Progress
      </div>
      <div className="flex flex-col gap-1">
        {STAGES.map((stage, index) => {
          const isDone = index < activeIndex
          const isActive = index === activeIndex
          const isPending = index > activeIndex

          return (
            <motion.div
              key={stage.key}
              layout
              initial={false}
              animate={
                isActive
                  ? {
                      backgroundColor: 'rgba(0, 240, 255, 0.05)',
                      paddingLeft: '6px',
                      paddingRight: '6px',
                      marginLeft: '-6px',
                      marginRight: '-6px',
                      borderRadius: '6px',
                    }
                  : {
                      backgroundColor: 'rgba(0, 0, 0, 0)',
                      paddingLeft: '0px',
                      paddingRight: '0px',
                      marginLeft: '0px',
                      marginRight: '0px',
                      borderRadius: '0px',
                    }
              }
              transition={{ duration: 0.3 }}
              className="flex items-center gap-2 py-0.5"
            >
              <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
                {isDone && (
                  <span className="text-[9px] text-emerald-400/60">&#10003;</span>
                )}
                {isActive && (
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-primary shadow-[0_0_6px_rgba(0,240,255,0.6)]" />
                  </span>
                )}
                {isPending && (
                  <span className="h-1.5 w-1.5 rounded-full border border-muted-foreground/20" />
                )}
              </span>
              <span
                className={`text-[10px] leading-tight transition-colors duration-300 ${
                  isActive
                    ? 'font-bold text-primary'
                    : isDone
                      ? 'text-muted-foreground/40'
                      : 'text-muted-foreground/20'
                }`}
              >
                {stage.label}
              </span>
            </motion.div>
          )
        })}
      </div>
    </motion.div>
  )
}
