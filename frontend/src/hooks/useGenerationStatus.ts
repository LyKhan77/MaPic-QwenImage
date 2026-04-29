import { useState, useEffect, useRef } from 'react'

const STATUS_MESSAGES = [
  'Treading through the latent ice fields...',
  'Sniffing the aurora for inspiration...',
  'Carving the glacier pixel by pixel...',
  'Navigating the blizzard of random noise...',
  'Hibernating the details into form...',
  'Planting the MaPic flag on the visual summit...',
]

const ROTATION_INTERVAL_MS = 25000 // 25 seconds

export function useGenerationStatus(isLoading: boolean): string {
  const [index, setIndex] = useState(0)
  const wasLoadingRef = useRef(isLoading)

  useEffect(() => {
    // Reset to first message when loading starts
    if (isLoading && !wasLoadingRef.current) {
      setIndex(0)
    }
    wasLoadingRef.current = isLoading
  }, [isLoading])

  useEffect(() => {
    if (!isLoading) return

    const interval = setInterval(() => {
      setIndex((prev) => {
        if (prev < STATUS_MESSAGES.length - 1) {
          return prev + 1
        }
        return prev // Stay on last message if generate takes longer
      })
    }, ROTATION_INTERVAL_MS)

    return () => clearInterval(interval)
  }, [isLoading])

  return STATUS_MESSAGES[index]
}
