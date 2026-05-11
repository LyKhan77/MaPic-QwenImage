import { useState, type KeyboardEvent, useRef, useEffect } from 'react'
import { Send, Paperclip, X, ChevronDown, Settings2, Info } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import type { ModelStatus } from '../lib/api'

export interface GenerationOptions {
  num_inference_steps?: number
  guidance_scale?: number
}

interface PromptInputProps {
  onGenerate: (prompt: string, images?: string[], options?: GenerationOptions) => void
  isLoading: boolean
  isCentralized?: boolean
  onTyping?: (isTyping: boolean) => void
  initialPrompt?: string
  initialImageUrl?: string
  modelStatus?: ModelStatus
  queueLength?: number
}

export default function PromptInput({ onGenerate, isLoading, isCentralized, onTyping, initialPrompt, initialImageUrl, modelStatus, queueLength = 0 }: PromptInputProps) {
  const [prompt, setPrompt] = useState('')
  const [showReferences, setShowReferences] = useState(true)
  const [images, setImages] = useState<{ id: string; base64: string }[]>([])
  const [showSettings, setShowSettings] = useState(false)
  const [steps, setSteps] = useState(50)
  const [guidance, setGuidance] = useState(1.5)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const isModelReady = modelStatus === 'ready' || modelStatus === undefined
  const isModelUnloaded = modelStatus === 'unloaded'

  useEffect(() => {
    if (initialPrompt) {
      setPrompt(initialPrompt)
    } else {
      setPrompt('')
    }

    if (initialImageUrl) {
      const fetchImage = async () => {
        try {
          const res = await fetch(initialImageUrl)
          const blob = await res.blob()
          const base64 = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader()
            reader.readAsDataURL(blob)
            reader.onload = () => resolve(reader.result as string)
            reader.onerror = error => reject(error)
          })
          setImages([{ id: 'rev-' + Math.random().toString(36).substring(7), base64 }])
        } catch (error) {
          console.error("Failed to load reference image", error)
        }
      }
      fetchImage()
    } else {
      setImages([])
    }
  }, [initialPrompt, initialImageUrl])

  useEffect(() => {
    if (!showSettings) return
    const handleEsc = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') setShowSettings(false)
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [showSettings])

  const handleChange = (val: string) => {
    setPrompt(val)
    if (onTyping) {
      onTyping(val.length > 0)
    }
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return

    if (images.length + files.length > 3) {
      alert('You can only upload up to 3 images.')
      return
    }

    const newImages = [...images]
    for (const file of files) {
      if (file.size > 2 * 1024 * 1024) {
        alert(`File ${file.name} is larger than 2MB.`)
        continue
      }

      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.readAsDataURL(file)
        reader.onload = () => resolve(reader.result as string)
        reader.onerror = error => reject(error)
      })

      newImages.push({ id: Math.random().toString(36).substring(7), base64 })
    }
    setImages(newImages)

    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const removeImage = (id: string) => {
    setImages(images.filter(img => img.id !== id))
  }

  const handleSubmit = () => {
    if (!prompt.trim() || !isModelReady) return
    if (isLoading && queueLength === undefined) return

    const cleanImages = images.length > 0
      ? images.map(img => img.base64.includes(',') ? img.base64.split(',')[1] : img.base64)
      : undefined;

    const options: GenerationOptions = {}
    if (steps !== 50) options.num_inference_steps = steps
    if (guidance !== 1.5) options.guidance_scale = guidance

    onGenerate(prompt, cleanImages, Object.keys(options).length > 0 ? options : undefined)
    setPrompt('')
    setImages([])
    if (onTyping) onTyping(false)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className={`w-full transition-all duration-500 ${isCentralized ? '' : 'border-t border-border bg-card/40 backdrop-blur-md p-6'}`}>
      <div className={`mx-auto w-full relative space-y-2 ${isCentralized ? 'max-w-2xl' : 'max-w-4xl'}`}>

        {!isCentralized && (!isModelReady || isModelUnloaded) && (
          <div className="absolute -top-8 left-1/2 right-1/2 flex items-center justify-center bg-destructive/90 backdrop-blur-sm py-1 px-3 rounded-lg z-50 whitespace-nowrap w-fit -translate-x-1/2">
            <span className="text-xs font-mono text-destructive-foreground">
              {modelStatus === 'loading' && 'Model loading...'}
              {modelStatus === 'offline' && 'Reconnecting...'}
              {modelStatus === 'unloaded' && 'Model is sleeping. Click Load to wake it up.'}
            </span>
          </div>
        )}

        {!isCentralized && (
            <div className="flex items-center justify-end px-1">
                <span className="text-[10px] text-muted-foreground font-mono">ENTER to send</span>
            </div>
        )}

        <div className={`relative flex items-center gap-2 transition-all ${isCentralized ? 'rounded-full bg-[#2a2a2a] p-1.5 shadow-xl ring-1 ring-white/5' : 'rounded-xl bg-muted/20 p-2 ring-1 ring-border focus-within:ring-primary/50'}`}>
          <input
             type="file"
             multiple
             accept="image/*"
             className="hidden"
             ref={fileInputRef}
             onChange={handleFileChange}
          />
          <button
             onClick={() => fileInputRef.current?.click()}
             disabled={isLoading || images.length >= 3 || !isModelReady}
             className={`flex shrink-0 items-center justify-center transition-all disabled:opacity-50 ${isCentralized ? 'h-10 w-10 rounded-full text-gray-400 hover:text-white hover:bg-white/10' : 'p-2 text-muted-foreground hover:text-foreground'}`}
             title="Attach reference image (Max 3, 2MB each)"
          >
             <Paperclip size={isCentralized ? 18 : 20} />
          </button>

          <input
            type="text"
            value={prompt}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={() => onTyping && onTyping(false)}
            placeholder={isCentralized ? "How can MaPic help you today?" : `Describe your imagination...`}
            disabled={isLoading || !isModelReady}
            className={`flex-1 bg-transparent px-2 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50 ${isCentralized ? 'text-lg py-3 px-4' : ''}`}
          />

          <button
            onClick={() => setShowSettings(!showSettings)}
            disabled={isLoading || !isModelReady}
            className={`shrink-0 flex items-center justify-center transition-all disabled:opacity-50 ${isCentralized ? 'h-10 w-10 rounded-full text-gray-400 hover:text-white hover:bg-white/10' : 'p-2 text-muted-foreground hover:text-foreground'} ${showSettings ? 'text-primary' : ''}`}
            title="Generation settings"
          >
            <Settings2 size={isCentralized ? 18 : 20} />
          </button>

          <button
            onClick={handleSubmit}
            disabled={!prompt.trim() || !isModelReady}
            className={`group shrink-0 flex items-center justify-center transition-all ${isCentralized ? 'h-10 w-10 rounded-full bg-white text-black hover:bg-primary disabled:bg-gray-600' : 'rounded-lg bg-foreground px-4 py-2 text-sm font-bold text-background hover:bg-primary hover:text-primary-foreground'}`}
          >
            {isCentralized ? <Send size={18} /> : (
                <>
                    <span>{isLoading ? `QUEUE (${queueLength + 1})` : 'GENERATE'}</span>
                    <Send size={14} className="ml-2 transition-transform group-hover:translate-x-1" />
                </>
            )}
          </button>
        </div>

        {/* Queue badge */}
        {queueLength > 0 && (
          <div className="flex items-center justify-end px-1">
            <span className="text-[10px] font-mono text-primary/70">
              {queueLength} queued
            </span>
          </div>
        )}

        {/* Reference Images Dropdown */}
        {images.length > 0 && (
          <div className="mt-2 border border-border rounded-lg bg-card/40 overflow-hidden animate-in fade-in slide-in-from-top-2">
            <button
              onClick={() => setShowReferences(!showReferences)}
              className="w-full flex items-center justify-between p-2.5 text-xs text-muted-foreground hover:bg-muted/50 transition-colors"
            >
              <div className="flex items-center gap-2 font-mono">
                <Paperclip size={14} />
                <span>{images.length} Reference Image{images.length > 1 ? 's' : ''} attached</span>
              </div>
              <ChevronDown size={16} className={`transition-transform duration-200 ${showReferences ? 'rotate-180' : ''}`} />
            </button>

            {showReferences && (
              <div className={`p-3 flex gap-3 flex-wrap border-t border-border bg-black/10 ${isCentralized ? 'justify-center' : ''}`}>
                {images.map(img => (
                  <div key={img.id} className="relative w-16 h-16 rounded-md overflow-hidden border border-border group bg-black/40 shadow-sm">
                    <img src={img.base64} alt="Reference" className="w-full h-full object-cover" />
                    <button
                      onClick={() => removeImage(img.id)}
                      className="absolute top-1 right-1 bg-black/60 text-white rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-500"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Settings Modal */}
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="fixed inset-0 z-50 flex items-center justify-center"
              onClick={() => setShowSettings(false)}
            >
              <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.2 }}
                className="relative z-10 w-full max-w-sm mx-4 rounded-xl border border-border bg-card/95 backdrop-blur-md p-5 shadow-2xl"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center justify-between mb-5">
                  <h3 className="text-sm font-bold tracking-tight">Generation Settings</h3>
                  <button
                    onClick={() => setShowSettings(false)}
                    className="text-muted-foreground hover:text-foreground transition-colors p-1"
                  >
                    <X size={16} />
                  </button>
                </div>

                <div className="space-y-5">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 group relative">
                        <label className="text-xs font-mono text-muted-foreground">Steps</label>
                        <Info size={13} className="text-muted-foreground hover:text-foreground cursor-pointer transition-colors" />
                        <div className="absolute left-0 bottom-full mb-2 w-56 bg-popover text-popover-foreground text-[11px] leading-relaxed rounded-md px-2.5 py-2 shadow-lg border border-border z-20 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-150 translate-y-1 group-hover:translate-y-0">
                          Number of denoising iterations. More steps yield finer detail but take longer.
                          <div className="absolute left-4 top-full -mt-px w-2 h-2 bg-popover border-r border-b border-border rotate-45" />
                        </div>
                      </div>
                      <span className="text-xs font-mono text-foreground tabular-nums">{steps}</span>
                    </div>
                    <input
                      type="range"
                      min={20}
                      max={75}
                      step={5}
                      value={steps}
                      onChange={(e) => setSteps(Number(e.target.value))}
                      className="w-full h-1 bg-muted rounded-full appearance-none cursor-pointer accent-primary"
                    />
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 group relative">
                        <label className="text-xs font-mono text-muted-foreground">Guidance</label>
                        <Info size={13} className="text-muted-foreground hover:text-foreground cursor-pointer transition-colors" />
                        <div className="absolute left-0 bottom-full mb-2 w-56 bg-popover text-popover-foreground text-[11px] leading-relaxed rounded-md px-2.5 py-2 shadow-lg border border-border z-20 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-150 translate-y-1 group-hover:translate-y-0">
                          How strongly the output follows your prompt. Higher values = stricter adherence.
                          <div className="absolute left-4 top-full -mt-px w-2 h-2 bg-popover border-r border-b border-border rotate-45" />
                        </div>
                      </div>
                      <span className="text-xs font-mono text-foreground tabular-nums">{guidance.toFixed(1)}</span>
                    </div>
                    <input
                      type="range"
                      min={1.0}
                      max={5.0}
                      step={0.1}
                      value={guidance}
                      onChange={(e) => setGuidance(Number(e.target.value))}
                      className="w-full h-1 bg-muted rounded-full appearance-none cursor-pointer accent-primary"
                    />
                  </div>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
