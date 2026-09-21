import { useState, useEffect, useMemo } from 'react'
import { motion } from 'framer-motion'
import { estimateTotalSeconds } from '../lib/generation'

interface GenerationTimeDisplayProps {
  isLoading: boolean
  steps: number
  numRefImages: number
  resolution?: number
  cfgEnabled?: boolean
}

function formatTime(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60)
  const s = Math.floor(totalSeconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function GenerationTimeDisplay({
  isLoading,
  steps,
  numRefImages,
  resolution = 2048,
  cfgEnabled = false,
}: GenerationTimeDisplayProps) {
  const [elapsed, setElapsed] = useState(0)

  const estimatedTotal = useMemo(
    () => estimateTotalSeconds(steps, numRefImages, resolution, cfgEnabled),
    [steps, numRefImages, resolution, cfgEnabled]
  )

  useEffect(() => {
    if (!isLoading) return
    const interval = setInterval(() => {
      setElapsed((prev) => prev + 1)
    }, 1000)
    return () => clearInterval(interval)
  }, [isLoading])

  if (!isLoading) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.3, delay: 0.1 }}
      className="mt-2 flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground/70 tabular-nums tracking-wide"
    >
      <span>{formatTime(elapsed)} elapsed</span>
      <span className="opacity-40">/</span>
      <span>~{formatTime(estimatedTotal)} est</span>
    </motion.div>
  )
}
