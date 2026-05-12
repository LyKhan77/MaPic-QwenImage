import { Download, Copy } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Generation } from '../types'
import type { ModelStatus } from '../lib/api'
import Loader from './Loader'
import BearAnimation from './BearAnimation'
import { toast } from 'sonner'
import PromptInput from './PromptInput'
import type { GenerationOptions } from './PromptInput'
import { useState } from 'react'
import { useGenerationStatus } from '../hooks/useGenerationStatus'
import GenerationTimeDisplay from './GenerationTimeDisplay'

interface ImageCanvasProps {
  currentGeneration: Generation | null
  isLoading: boolean
  modelStatus: ModelStatus
  onGenerate: (prompt: string, images?: string[], options?: GenerationOptions) => void
  pendingGenParams?: { steps: number; numRefImages: number }
  genKey?: number
  isViewingActiveGeneration?: boolean
}

export default function ImageCanvas({ currentGeneration, isLoading, modelStatus, onGenerate, pendingGenParams, genKey, isViewingActiveGeneration = true }: ImageCanvasProps) {
  const [isTyping, setIsTyping] = useState(false)
  const generationStatus = useGenerationStatus(isLoading)

  const handleDownload = async () => {
    if (!currentGeneration?.public_url) return

    try {
      const response = await fetch(currentGeneration.public_url)
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `gen-${currentGeneration.id}.png`
      document.body.appendChild(link)
      link.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(link)
    } catch {
      console.error("Download failed")
      toast.error('Download failed')
    }
  }

  const handleShare = async () => {
    if (!currentGeneration?.public_url) return
    
    if (!navigator.clipboard || !window.ClipboardItem) {
      toast.error('Copying images requires a secure context (HTTPS) or a supported browser.')
      return
    }

    try {
      const response = await fetch(currentGeneration.public_url)
      const blob = await response.blob()
      
      // Some browsers (like Safari) might require 'image/png' explicitly
      // but dynamically using blob.type is generally safer if it's correct.
      await navigator.clipboard.write([
        new ClipboardItem({
          [blob.type]: blob
        })
      ])
      toast.success('Image copied to clipboard!')
    } catch (error) {
      console.error('Copy failed:', error)
      toast.error('Failed to copy image')
    }
  }

  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden bg-background p-8 transition-colors">
      {/* Grid Background */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,hsl(var(--muted))_1px,transparent_1px),linear-gradient(to_bottom,hsl(var(--muted))_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-20" />
      
      {/* Content */}
      <div className="relative z-10 flex h-full w-full flex-col items-center justify-center">
        <AnimatePresence mode="wait">
          {isLoading && !currentGeneration && isViewingActiveGeneration ? (
            <motion.div 
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-4"
            >
              <div className="relative h-36 w-36">
                <Loader />
              </div>
              <p className="font-mono text-sm text-primary animate-pulse mt-8 h-5">
                <AnimatePresence mode="wait">
                  {modelStatus === 'loading' ? (
                    <motion.span
                      key="loading-pipeline"
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.3 }}
                      className="inline-block"
                    >
                      Loading pipeline...
                    </motion.span>
                  ) : modelStatus === 'offline' ? (
                    <motion.span
                      key="reconnecting"
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.3 }}
                      className="inline-block"
                    >
                      Reconnecting...
                    </motion.span>
                  ) : (
                    <motion.span
                      key={generationStatus}
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.3 }}
                      className="inline-block"
                    >
                      {generationStatus}
                    </motion.span>
                  )}
                </AnimatePresence>
              </p>
              {modelStatus === 'ready' && (
                <GenerationTimeDisplay
                  key={genKey}
                  isLoading={isLoading}
                  steps={pendingGenParams?.steps ?? 50}
                  numRefImages={pendingGenParams?.numRefImages ?? 0}
                />
              )}
              {modelStatus === 'ready' && (
                <div className="w-full max-w-2xl mt-6">
                  <PromptInput
                    onGenerate={onGenerate}
                    isLoading={isLoading}
                    isCentralized={true}
                    modelStatus={modelStatus}
                  />
                </div>
              )}
            </motion.div>
          ) : currentGeneration ? (
            <motion.div 
              key="image"
              initial={{ opacity: 0, scale: 0.95, filter: 'blur(10px)' }}
              animate={{ opacity: 1, scale: 1, filter: 'blur(0px)' }}
              transition={{ duration: 0.5 }}
              className="group relative flex h-full max-h-[70vh] max-w-full items-center justify-center overflow-hidden rounded-lg border border-border bg-card/50 shadow-2xl p-4"
            >
              <img 
                src={currentGeneration.public_url} 
                alt={currentGeneration.prompt} 
                className="h-full w-full object-contain"
              />
              
              {/* Overlay Actions */}
              <div className="absolute bottom-0 left-0 right-0 flex items-center justify-between bg-black/60 p-4 backdrop-blur-md transition-transform translate-y-full group-hover:translate-y-0">
                <p className="max-w-[70%] truncate text-xs font-mono text-gray-300">
                  {currentGeneration.prompt}
                </p>
                <div className="flex gap-2">
                  <button 
                    onClick={handleDownload}
                    className="rounded-full bg-white/10 p-2 hover:bg-primary hover:text-black transition-colors"
                  >
                    <Download size={16} />
                  </button>
                  <button 
                    onClick={handleShare}
                    className="rounded-full bg-white/10 p-2 hover:bg-secondary hover:text-white transition-colors"
                    title="Copy Image"
                  >
                    <Copy size={16} />
                  </button>
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div 
              key="empty"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-start pt-20 w-full max-w-4xl space-y-8 h-full"
            >
               <div className="flex flex-col items-center">
                 <div className="-mb-10">
                   <BearAnimation isTyping={isTyping} />
                 </div>
                 <img 
                   src="/Mapic-font-trans.png" 
                   alt="MaPic" 
                   className="h-32 object-contain drop-shadow-[0_0_20px_rgba(255,255,255,0.3)]"
                 />
               </div>
               
               <PromptInput
                  onGenerate={onGenerate}
                  isLoading={isLoading}
                  isCentralized={true}
                  onTyping={setIsTyping}
                  modelStatus={modelStatus}
               />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
