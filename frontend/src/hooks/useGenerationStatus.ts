import { useState, useEffect, useRef } from 'react'

const STATUS_MESSAGES = [
  'Compiling salmon-flavored pixels in the igloo...',
  'Debugging polar bear neural pathways...',
  'Pushing commits to the Antarctic ice shelf...',
  'Optimizing hibernation cycles for max GPU perf...',
  'Pawing through latent space for the perfect fish...',
  'Writing bash scripts with thick bear claws...',
  'Deploying bear-resistant caching layers...',
  'Refactoring the glacial drift algorithms...',
  'Tuning hyperparameters over a campfire with bears...',
  'Waiting for the icebreaker ship to fetch more RAM...',
]

const ROTATION_INTERVAL_MS = 25000 // 25 seconds

export function useGenerationStatus(isLoading: boolean): string {
  const [index, setIndex] = useState(0)
  const wasLoadingRef = useRef(isLoading)

  useEffect(() => {
    // Reset to random message when loading starts
    if (isLoading && !wasLoadingRef.current) {
      setIndex(Math.floor(Math.random() * STATUS_MESSAGES.length))
    }
    wasLoadingRef.current = isLoading
  }, [isLoading])

  useEffect(() => {
    if (!isLoading) return

    const interval = setInterval(() => {
      setIndex((prev) => {
        let nextIndex;
        do {
          nextIndex = Math.floor(Math.random() * STATUS_MESSAGES.length)
        } while (nextIndex === prev)
        return nextIndex
      })
    }, ROTATION_INTERVAL_MS)

    return () => clearInterval(interval)
  }, [isLoading])

  return STATUS_MESSAGES[index]
}
