import { useState, useEffect, useCallback, useRef } from 'react'
import type { Session } from '@supabase/supabase-js'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import Sidebar from '../components/Sidebar'
import ImageCanvas from '../components/ImageCanvas'
import PromptInput from '../components/PromptInput'
import ModelStatusBadge from '../components/ModelStatusBadge'
import GenerationStageBadge from '../components/GenerationStageBadge'
import ActiveGenerationsIndicator from '../components/ActiveGenerationsIndicator'
import type { Generation, ActiveGeneration } from '../types'
import type { GenerationOptions } from '../components/PromptInput'
import { Toaster, toast } from 'sonner'

interface DashboardProps {
  session: Session
}

export default function Dashboard({ session }: DashboardProps) {
  const queryClient = useQueryClient()
  const [currentGen, setCurrentGen] = useState<Generation | null>(null)
  const [loadProgress, setLoadProgress] = useState(0)
  const [loadMessage, setLoadMessage] = useState('')
  const [loadElapsed, setLoadElapsed] = useState(0)
  const [pendingGenParams, setPendingGenParams] = useState<{ steps: number; numRefImages: number } | null>(null)
  const [genKey, setGenKey] = useState(0)
  const [queue, setQueue] = useState<Array<{ prompt: string; images?: string[]; options?: GenerationOptions }>>([])
  const [activeGenerations, setActiveGenerations] = useState<ActiveGeneration[]>([])
  const [globalStage, setGlobalStage] = useState('idle')
  const [isViewingActiveGeneration, setIsViewingActiveGeneration] = useState(false)
  const isDraining = useRef(false)

  // Poll model health status
  const { data: modelStatus = 'offline' } = useQuery({
    queryKey: ['model-health'],
    queryFn: api.getHealth,
    refetchInterval: (query) => {
      if (query.state.data === 'ready') return false
      return 5000
    },
    refetchIntervalInBackground: false,
  })

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>
    if (modelStatus === 'loading') {
      interval = setInterval(() => {
        setLoadElapsed(prev => prev + 1)
        setLoadProgress(prev => {
          if (prev < 90) return prev + 0.3
          return prev
        })
      }, 1000)
    } else {
      setLoadElapsed(0)
      if (modelStatus !== 'ready') {
        setLoadProgress(0)
      }
    }
    return () => clearInterval(interval)
  }, [modelStatus])

  // Fetch History
  const { data: history = [] } = useQuery({
    queryKey: ['history', session.user.id],
    queryFn: () => api.getHistory(session.user.id),
    select: (data) => data.filter((item: Generation) => item.image_path?.endsWith('.png') || item.public_url?.endsWith('.png'))
  })

  // Generate Mutation
  const generateMutation = useMutation({
    mutationFn: ({ prompt, images, options }: { prompt: string; images?: string[]; options?: GenerationOptions }) => api.generateImage(prompt, session.user.id, images, options),
    onMutate: (vars) => {
      setCurrentGen(null)
      setIsViewingActiveGeneration(true)
      setGenKey((prev) => prev + 1)
      setPendingGenParams({
        steps: vars.options?.num_inference_steps ?? 50,
        numRefImages: vars.images?.length ?? 0,
      })
    },
    onSuccess: (newGen) => {
      queryClient.setQueryData(['history', session.user.id], (old: Generation[] = []) => [newGen, ...old])
      setCurrentGen(newGen)
      setIsViewingActiveGeneration(false)
      toast.success('Image generated successfully!')
    },
    onError: (error) => {
      console.error(error)
      setIsViewingActiveGeneration(false)
      toast.error(error instanceof Error ? error.message : 'Failed to generate image')
    },
    onSettled: () => {
      setPendingGenParams(null)
    },
  })

  // Poll active generations + global stage (only when relevant)
  useEffect(() => {
    const shouldPoll = generateMutation.isPending || activeGenerations.length > 0
    if (!shouldPoll) {
      setGlobalStage('idle')
      return
    }

    const poll = setInterval(async () => {
      const [active, status] = await Promise.all([
        api.getActiveGenerations(),
        api.getGenerationStatus(),
      ])
      setActiveGenerations(active)
      setGlobalStage(status.stage && status.stage !== 'idle' ? status.stage : 'idle')
    }, 3000)
    return () => clearInterval(poll)
  }, [generateMutation.isPending, activeGenerations.length])

  // Auto-drain queue
  useEffect(() => {
    if (!generateMutation.isPending && queue.length > 0 && !isDraining.current) {
      isDraining.current = true
      const next = queue[0]
      setQueue(prev => prev.slice(1))
      generateMutation.mutate({ prompt: next.prompt, images: next.images, options: next.options })
      // Reset flag after mutation starts
      requestAnimationFrame(() => { isDraining.current = false })
    }
  }, [generateMutation.isPending, queue])

  const handleGenerate = useCallback((prompt: string, images?: string[], options?: GenerationOptions) => {
    if (generateMutation.isPending) {
      setQueue(prev => [...prev, { prompt, images, options }])
      toast.info(`Queued (${queue.length + 1} pending)`)
    } else {
      generateMutation.mutate({ prompt, images, options })
    }
  }, [generateMutation, queue.length])

  // Delete Mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteHistory(id),
    onSuccess: (_, id) => {
      queryClient.setQueryData(['history', session.user.id], (old: Generation[] = []) =>
        old.filter(item => item.id !== id)
      )

      if (currentGen?.id === id) {
        setCurrentGen(null)
      }

      toast.success('Deleted successfully')
    },
    onError: () => toast.error('Failed to delete item')
  })

  const handleSelectHistory = (gen: Generation) => {
    setCurrentGen(gen)
    setIsViewingActiveGeneration(false)
  }

  const handleNewChat = () => {
    setCurrentGen(null)
    setIsViewingActiveGeneration(false)
  }

  const handleLoadModel = async () => {
    try {
      queryClient.setQueryData(['model-health'], 'loading')
      setLoadProgress(0)
      setLoadElapsed(0)
      setLoadMessage('Connecting...')
      await api.loadModel((p, m) => {
        setLoadProgress(prev => Math.max(prev, p))
        setLoadMessage(m)
      })
      queryClient.invalidateQueries({ queryKey: ['model-health'] })
    } catch (e) {
      console.error(e)
      queryClient.setQueryData(['model-health'], 'offline')
      toast.error('Failed to load model')
    }
  }

  const handleUnloadModel = async () => {
    try {
      queryClient.setQueryData(['model-health'], 'unloaded')
      await api.unloadModel()
      queryClient.invalidateQueries({ queryKey: ['model-health'] })
    } catch (e) {
      console.error(e)
    }
  }

  const handleFocusMyGen = useCallback(() => {
    setCurrentGen(null)
    setIsViewingActiveGeneration(true)
  }, [])

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground font-sans">
      <Toaster position="top-right" theme="dark" />

      <Sidebar
        session={session}
        history={history}
        onSelect={handleSelectHistory}
        onNewChat={handleNewChat}
        onDelete={(id) => deleteMutation.mutate(id)}
        currentId={currentGen?.id}
      />

      <main className="flex flex-1 flex-col relative min-w-0 min-h-0">
        <div className="flex-1 relative min-h-0 flex flex-col">
           <div className="absolute top-4 right-6 z-50 flex flex-col items-end gap-2">
             <ModelStatusBadge status={modelStatus} onLoad={handleLoadModel} onUnload={handleUnloadModel} progress={loadProgress} message={loadMessage} elapsed={loadElapsed} />
             <GenerationStageBadge
               key={`stage-${genKey}`}
               isLoading={generateMutation.isPending}
               steps={pendingGenParams?.steps ?? 50}
               numRefImages={pendingGenParams?.numRefImages ?? 0}
             />
           </div>
           <ImageCanvas
             currentGeneration={currentGen}
             isLoading={generateMutation.isPending}
             modelStatus={modelStatus}
             onGenerate={handleGenerate}
             pendingGenParams={pendingGenParams ?? undefined}
             genKey={genKey}
             isViewingActiveGeneration={isViewingActiveGeneration}
           />
        </div>

        {(currentGen || generateMutation.isPending) && (
          <div className="shrink-0 w-full bg-background relative z-20">
            <PromptInput
              onGenerate={handleGenerate}
              isLoading={generateMutation.isPending}
              isCentralized={false}
              initialPrompt={currentGen && !isViewingActiveGeneration ? currentGen.prompt : undefined}
              initialImageUrl={currentGen && !isViewingActiveGeneration ? currentGen.public_url : undefined}
              modelStatus={modelStatus}
              queueLength={queue.length}
            />
          </div>
        )}

        <ActiveGenerationsIndicator
          activeGenerations={activeGenerations}
          currentUserId={session.user.id}
          globalStage={globalStage}
          onFocusMyGen={handleFocusMyGen}
        />
      </main>
    </div>
  )
}
