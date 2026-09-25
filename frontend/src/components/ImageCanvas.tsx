import { Download, Copy } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Generation, GenerationTimeParams } from '../types'
import type { ModelStatus } from '../lib/api'
import Loader from './Loader'
import BearAnimation from './BearAnimation'
import { toast } from 'sonner'
import PromptInput from './PromptInput'
import type { GenerationOptions } from './PromptInput'
import { useState } from 'react'
import { useGenerationStatus } from '../hooks/useGenerationStatus'
import GenerationTimeDisplay from './GenerationTimeDisplay'
import { isCutoutGeneration } from '../lib/removeBackground'

interface ImageCanvasProps {
  currentGeneration: Generation | null
  isLoading: boolean
  isRemovingBackground?: boolean
  modelStatus: ModelStatus
  onGenerate: (prompt: string, images?: string[], options?: GenerationOptions) => void
  onRemoveBackground?: (imageBase64: string, sourceLabel?: string) => void | Promise<void>
  pendingGenParams?: GenerationTimeParams
  genKey?: number
  isViewingActiveGeneration?: boolean
  removeBg: boolean
  onRemoveBgChange: (next: boolean) => void
}

export default function ImageCanvas({ currentGeneration, isLoading, isRemovingBackground = false, modelStatus, onGenerate, onRemoveBackground, pendingGenParams, genKey, isViewingActiveGeneration = true, removeBg, onRemoveBgChange }: ImageCanvasProps) {
  const [isTyping, setIsTyping] = useState(false)
  const generationStatus = useGenerationStatus(isLoading)
  // Deteksi hasil cutout dari label prompt server (tidak ada kolom DB baru) —
  // kosmetik belaka: prompt Create buatan pengguna dengan teks persis ini juga
  // akan menampilkan latar kotak-kotak.
  const isCutout = isCutoutGeneration(currentGeneration?.prompt)

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
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden bg-background p-3 transition-colors md:p-8">
      {/* Grid Background */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,hsl(var(--muted))_1px,transparent_1px),linear-gradient(to_bottom,hsl(var(--muted))_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-20" />
      
      {/* Content */}
      <div className="relative z-10 flex h-full w-full flex-col items-center justify-center">
        <AnimatePresence mode="wait">
          {isRemovingBackground ? (
            <motion.div
              key="cutout"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-4"
            >
              <div className="relative h-36 w-36">
                <Loader />
              </div>
              {/* Bukan stage Qwen: tidak ada step/estimasi yang bisa dilaporkan. */}
              <p className="font-mono text-sm text-primary animate-pulse mt-8 h-5">Removing background...</p>
            </motion.div>
          ) : isLoading && !currentGeneration && isViewingActiveGeneration ? (
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
                  steps={pendingGenParams?.steps ?? 40}
                  numRefImages={pendingGenParams?.numRefImages ?? 0}
                  resolution={pendingGenParams?.resolution ?? 1024}
                  cfgEnabled={pendingGenParams?.cfgEnabled ?? false}
                />
              )}
            </motion.div>
          ) : currentGeneration ? (
            <motion.div 
              key="image"
              initial={{ opacity: 0, scale: 0.95, filter: 'blur(10px)' }}
              animate={{ opacity: 1, scale: 1, filter: 'blur(0px)' }}
              transition={{ duration: 0.5 }}
              className={`group relative flex h-full max-h-[70vh] max-w-full items-center justify-center overflow-hidden rounded-lg border border-border shadow-2xl p-4 ${isCutout ? 'bg-[repeating-conic-gradient(#4b5563_0_25%,#1f2937_0_50%)] bg-[length:16px_16px]' : 'bg-card/50'}`}
            >
              <img 
                src={currentGeneration.public_url} 
                alt={currentGeneration.prompt} 
                className="h-full w-full object-contain"
              />
              
              {/* Overlay Actions */}
              <div className="absolute bottom-0 left-0 right-0 flex items-center justify-between bg-black/60 p-4 backdrop-blur-md transition-transform translate-y-0 md:translate-y-full md:group-hover:translate-y-0">
                <p className="max-w-[70%] truncate text-xs font-mono text-gray-300">
                  {currentGeneration.prompt}
                </p>
                <div className="flex gap-2">
                  <button 
                    onClick={handleDownload}
                    className="rounded-full bg-white/10 p-3 md:p-2 hover:bg-primary hover:text-black transition-colors"
                  >
                    <Download size={16} />
                  </button>
                  <button 
                    onClick={handleShare}
                    className="rounded-full bg-white/10 p-3 md:p-2 hover:bg-secondary hover:text-white transition-colors"
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
              className="flex flex-col items-center justify-start pt-28 md:pt-20 w-full max-w-4xl space-y-8 h-full"
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
                  onRemoveBackground={onRemoveBackground}
                  isLoading={isLoading}
                  isRemovingBackground={isRemovingBackground}
                  isCentralized={true}
                  onTyping={setIsTyping}
                  modelStatus={modelStatus}
                  removeBg={removeBg}
                  onRemoveBgChange={onRemoveBgChange}
               />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
