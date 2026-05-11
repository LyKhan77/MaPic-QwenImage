import { useState, useEffect, useCallback } from 'react'
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

const MAX_GLOBAL_GENERATIONS = 10

interface PendingGeneration {
  prompt: string
  images?: string[]
  options?: GenerationOptions
  startedAt: number
}

export default function Dashboard({ session }: DashboardProps) {
  const queryClient = useQueryClient()
  const [currentGen, setCurrentGen] = useState<Generation | null>(null)
  const [loadProgress, setLoadProgress] = useState(0)
  const [loadMessage, setLoadMessage] = useState('')
  const [loadElapsed, setLoadElapsed] = useState(0)
  const [pendingGenParams, setPendingGenParams] = useState<{ steps: number; numRefImages: number } | null>(null)
  const [genKey, setGenKey] = useState(0)
  const [pendingGenerations, setPendingGenerations] = useState<Record<string, PendingGeneration>>({})
  const [activeGenerations, setActiveGenerations] = useState<ActiveGeneration[]>([])
  const [globalStage, setGlobalStage] = useState('idle')
  const [isViewingActiveGeneration, setIsViewingActiveGeneration] = useState(false)
  const pendingGenerationCount = Object.keys(pendingGenerations).length
  const optimisticPendingCount = Object.values(pendingGenerations).filter(pending =>
    !activeGenerations.some(gen => gen.user_id === session.user.id && gen.prompt === pending.prompt)
  ).length
  const displayedGenerationCount = activeGenerations.length + optimisticPendingCount
  const hasPendingGenerations = pendingGenerationCount > 0

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

  // Poll active generations + global stage (only when relevant)
  useEffect(() => {
    const shouldPoll = hasPendingGenerations || activeGenerations.length > 0
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
  }, [hasPendingGenerations, activeGenerations.length])

  const handleGenerate = useCallback((prompt: string, images?: string[], options?: GenerationOptions) => {
    if (displayedGenerationCount >= MAX_GLOBAL_GENERATIONS) {
      toast.error('Global generation queue is full. Try again later.')
      return
    }

    const id = typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2)
    const startedAt = Date.now()

    setPendingGenerations(prev => ({ ...prev, [id]: { prompt, images, options, startedAt } }))
    setCurrentGen(null)
    setIsViewingActiveGeneration(true)
    setGenKey((prev) => prev + 1)
    setPendingGenParams({
      steps: options?.num_inference_steps ?? 50,
      numRefImages: images?.length ?? 0,
    })

    void api.generateImage(prompt, session.user.id, images, options)
      .then((newGen) => {
        queryClient.setQueryData(['history', session.user.id], (old: Generation[] = []) => [newGen, ...old])
        setCurrentGen(newGen)
        setIsViewingActiveGeneration(false)
        toast.success('Image generated successfully!')
      })
      .catch((error) => {
        console.error(error)
        setIsViewingActiveGeneration(false)
        toast.error(error instanceof Error ? error.message : 'Failed to generate image')
      })
      .finally(() => {
        setPendingGenerations(prev => {
          const next = { ...prev }
          delete next[id]
          if (Object.keys(next).length === 0) {
            setPendingGenParams(null)
          }
          return next
        })
      })
  }, [displayedGenerationCount, queryClient, session.user.id])

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
               isLoading={hasPendingGenerations}
               steps={pendingGenParams?.steps ?? 50}
               numRefImages={pendingGenParams?.numRefImages ?? 0}
             />
           </div>
           <ImageCanvas
             currentGeneration={currentGen}
             isLoading={hasPendingGenerations}
             modelStatus={modelStatus}
             onGenerate={handleGenerate}
             pendingGenParams={pendingGenParams ?? undefined}
             genKey={genKey}
             isViewingActiveGeneration={isViewingActiveGeneration}
           />
        </div>

        {currentGen && (
          <div className="shrink-0 w-full bg-background relative z-20">
            <PromptInput
              onGenerate={handleGenerate}
              isLoading={hasPendingGenerations}
              isCentralized={false}
              initialPrompt={!isViewingActiveGeneration ? currentGen.prompt : undefined}
              initialImageUrl={!isViewingActiveGeneration ? currentGen.public_url : undefined}
              modelStatus={modelStatus}
              queueLength={Math.max(pendingGenerationCount - 1, 0)}
            />
          </div>
        )}

        <ActiveGenerationsIndicator
          activeGenerations={activeGenerations}
          pendingGenerations={pendingGenerations}
          currentUserId={session.user.id}
          globalStage={globalStage}
          onFocusMyGen={handleFocusMyGen}
        />
      </main>
    </div>
  )
}
