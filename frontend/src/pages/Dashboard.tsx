import { useState, useEffect, useCallback, useRef } from 'react'
import type { Session } from '@supabase/supabase-js'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { AlertTriangle, ExternalLink, X } from 'lucide-react'
import Sidebar from '../components/Sidebar'
import ImageCanvas from '../components/ImageCanvas'
import PromptInput from '../components/PromptInput'
import ModelStatusBadge from '../components/ModelStatusBadge'
import GenerationStageBadge from '../components/GenerationStageBadge'
import ActiveGenerationsIndicator from '../components/ActiveGenerationsIndicator'
import type { Generation, ActiveGeneration, GenerationTimeParams } from '../types'
import type { GenerationOptions } from '../components/PromptInput'
import { Toaster, toast } from 'sonner'
import {
  didGenerationWorkComplete,
  getActiveGenerationParams,
  hasGenerationWorkForUser,
  shouldShowActiveGenerationView,
} from '../lib/activeGenerationState'

interface DashboardProps {
  session: Session
}

const MAX_GLOBAL_GENERATIONS = 10

const selectGeneratedPngHistory = (data: Generation[]) =>
  data.filter((item: Generation) => item.image_path?.endsWith('.png') || item.public_url?.endsWith('.png'))

interface PendingGeneration {
  prompt: string
  images?: string[]
  options?: GenerationOptions
  startedAt: number
}

export default function Dashboard({ session }: DashboardProps) {
  const queryClient = useQueryClient()
  const [currentGen, setCurrentGen] = useState<Generation | null>(null)
  const [loadElapsed, setLoadElapsed] = useState(0)
  const [pendingGenParams, setPendingGenParams] = useState<GenerationTimeParams | null>(null)
  const [genKey, setGenKey] = useState(0)
  const [pendingGenerations, setPendingGenerations] = useState<Record<string, PendingGeneration>>({})
  const [activeGenerations, setActiveGenerations] = useState<ActiveGeneration[]>([])
  const [globalStage, setGlobalStage] = useState('idle')
  const [isViewingActiveGeneration, setIsViewingActiveGeneration] = useState(false)
  const [isNewGenerationDraft, setIsNewGenerationDraft] = useState(false)
  const [tunnelUrlMismatch, setTunnelUrlMismatch] = useState(false)
  const [tunnelDashboardUrl, setTunnelDashboardUrl] = useState('')
  const [tunnelDismissed, setTunnelDismissed] = useState(false)
  const hadCurrentUserGenerationWorkRef = useRef(false)
  const completionSyncRequestIdRef = useRef(0)
  const pendingGenerationCount = Object.keys(pendingGenerations).length
  const optimisticPendingCount = Object.values(pendingGenerations).filter(pending =>
    !activeGenerations.some(gen => gen.user_id === session.user.id && gen.prompt === pending.prompt)
  ).length
  const displayedGenerationCount = activeGenerations.length + optimisticPendingCount
  const hasCurrentUserGenerationWork = hasGenerationWorkForUser(activeGenerations, pendingGenerations, session.user.id)
  const activeGenerationParams = getActiveGenerationParams(activeGenerations, session.user.id)
  const displayedGenParams = pendingGenParams ?? activeGenerationParams
  const isViewingCurrentUserActiveGeneration = shouldShowActiveGenerationView({
    currentGeneration: currentGen,
    hasCurrentUserGenerationWork,
    isViewingActiveGeneration,
  })

  // Poll model health status
  const { data: modelStatus = 'offline' } = useQuery({
    queryKey: ['model-health'],
    queryFn: api.getHealth,
    refetchInterval: (query) => {
      if (query.state.data === 'ready') return false
      return 10000
    },
    refetchIntervalInBackground: false,
  })

  // Check if tunnel URL matches deployed VITE_API_URL (only in production)
  useEffect(() => {
    const deployedApiUrl = import.meta.env.VITE_API_URL
    if (!deployedApiUrl) return

    const check = async () => {
      try {
        const status = await api.getTunnelStatus()
        if (status.tunnel_url) {
          const tunnelApiBase = `${status.tunnel_url}/api`
          setTunnelDashboardUrl(status.vercel_dashboard)
          setTunnelUrlMismatch(tunnelApiBase !== deployedApiUrl)
        }
      } catch { /* ignore */ }
    }

    void check()
    const interval = setInterval(check, 30000)
    return () => clearInterval(interval)
  }, [])

  // Recover loading state on mount (survives page refresh)
  useEffect(() => {
    let isMounted = true
    api.getLoadState().then((state) => {
      if (!isMounted) return
      if (state.status === 'loading') {
        queryClient.setQueryData(['model-health'], 'loading')
      }
    })
    return () => { isMounted = false }
  }, [queryClient])

  // Elapsed timer during model loading
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>
    if (modelStatus === 'loading') {
      interval = setInterval(() => {
        setLoadElapsed(prev => prev + 1)
      }, 1000)
    } else {
      setLoadElapsed(0)
    }
    return () => clearInterval(interval)
  }, [modelStatus])

  // Fetch History
  const { data: history = [] } = useQuery({
    queryKey: ['history', session.user.id],
    queryFn: () => api.getHistory(session.user.id),
    select: selectGeneratedPngHistory
  })

  // Poll active generations + global stage for all users. This rehydrates active work after refresh.
  useEffect(() => {
    let isMounted = true
    let intervalId: ReturnType<typeof setInterval>

    const poll = async () => {
      const [active, status] = await Promise.all([
        api.getActiveGenerations(),
        api.getGenerationStatus(),
      ])
      if (!isMounted) return
      setActiveGenerations(active)
      setGlobalStage(status.stage && status.stage !== 'idle' ? status.stage : 'idle')
    }

    const schedulePoll = () => {
      const hasActiveWork = activeGenerations.length > 0 || globalStage !== 'idle'
      clearInterval(intervalId)
      intervalId = setInterval(poll, hasActiveWork ? 2000 : 5000)
    }

    void poll()
    schedulePoll()

    return () => {
      isMounted = false
      clearInterval(intervalId)
    }
  }, [activeGenerations.length, globalStage])

  useEffect(() => {
    let isCancelled = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    if (hasCurrentUserGenerationWork) {
      hadCurrentUserGenerationWorkRef.current = true
      if (!currentGen && !isNewGenerationDraft && !isViewingActiveGeneration) {
        setIsViewingActiveGeneration(true)
      }
      return () => { isCancelled = true }
    }

    if (!didGenerationWorkComplete(hadCurrentUserGenerationWorkRef.current, hasCurrentUserGenerationWork)) {
      return () => { isCancelled = true }
    }

    hadCurrentUserGenerationWorkRef.current = false
    const syncRequestId = completionSyncRequestIdRef.current + 1
    completionSyncRequestIdRef.current = syncRequestId

    const syncHistoryAfterCompletion = async (allowRetry: boolean) => {
      try {
        const items = await queryClient.fetchQuery({
          queryKey: ['history', session.user.id],
          queryFn: () => api.getHistory(session.user.id),
        })
        if (isCancelled || syncRequestId !== completionSyncRequestIdRef.current) return

        const generatedPngHistory = selectGeneratedPngHistory(items)
        queryClient.setQueryData(['history', session.user.id], generatedPngHistory)

        let hasFocusedGeneration = false
        setCurrentGen((prev) => {
          if (prev) {
            hasFocusedGeneration = true
            return prev
          }

          if (generatedPngHistory[0]) {
            hasFocusedGeneration = true
            return generatedPngHistory[0]
          }

          return prev
        })

        if (!hasFocusedGeneration && allowRetry) {
          retryTimer = setTimeout(() => {
            if (!isCancelled && syncRequestId === completionSyncRequestIdRef.current) {
              void syncHistoryAfterCompletion(false)
            }
          }, 1200)
          return
        }

        if (hasFocusedGeneration) {
          setIsViewingActiveGeneration(false)
          setIsNewGenerationDraft(false)
        }
      } catch (error) {
        if (!isCancelled) {
          console.error(error)
        }
      }
    }

    void syncHistoryAfterCompletion(true)

    return () => {
      isCancelled = true
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [
    currentGen,
    hasCurrentUserGenerationWork,
    isNewGenerationDraft,
    isViewingActiveGeneration,
    queryClient,
    session.user.id,
  ])

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
    setIsNewGenerationDraft(false)
    setGenKey((prev) => prev + 1)
    setPendingGenParams({
      steps: options?.num_inference_steps ?? 40,
      numRefImages: images?.length ?? 0,
      resolution: options?.resolution ?? 2048,
      cfgEnabled: Boolean(options?.true_cfg_scale && options.true_cfg_scale > 1),
    })

    void api.generateImage(prompt, session.user.id, images, options)
      .then((newGen) => {
        queryClient.setQueryData(['history', session.user.id], (old: Generation[] = []) => [newGen, ...old.filter(item => item.id !== newGen.id)])
        setCurrentGen(newGen)
        setIsViewingActiveGeneration(false)
        setIsNewGenerationDraft(false)
        toast.success('Image generated successfully!')
      })
      .catch((error) => {
        console.error(error)
        setIsViewingActiveGeneration(false)
        setIsNewGenerationDraft(false)
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
    setIsNewGenerationDraft(false)
  }

  const handleNewChat = () => {
    setCurrentGen(null)
    setIsViewingActiveGeneration(false)
    setIsNewGenerationDraft(true)
  }

  const handleLoadModel = async () => {
    try {
      queryClient.setQueryData(['model-health'], 'loading')
      setLoadElapsed(0)
      await api.loadModel()
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
    setIsNewGenerationDraft(false)
  }, [])

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground font-sans">
      <Toaster position="top-right" theme="dark" />

      {tunnelUrlMismatch && !tunnelDismissed && (
        <div className="fixed top-0 left-0 right-0 z-[100] flex items-center justify-center gap-3 px-4 py-2 bg-amber-500/90 text-black text-sm font-medium shadow-lg backdrop-blur-sm">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>Tunnel URL changed. Redeploy frontend to update the API connection.</span>
          {tunnelDashboardUrl && (
            <a
              href={tunnelDashboardUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-black/20 rounded text-xs font-semibold hover:bg-black/30 transition-colors"
            >
              Vercel Dashboard <ExternalLink className="h-3 w-3" />
            </a>
          )}
          <button onClick={() => setTunnelDismissed(true)} className="ml-1 hover:bg-black/20 rounded p-0.5 transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

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
             <ModelStatusBadge status={modelStatus} onLoad={handleLoadModel} onUnload={handleUnloadModel} elapsed={loadElapsed} />
             <GenerationStageBadge
               key={`stage-${genKey}`}
               isLoading={hasCurrentUserGenerationWork}
               steps={displayedGenParams?.steps ?? 40}
               numRefImages={displayedGenParams?.numRefImages ?? 0}
             />
           </div>
           <ImageCanvas
             currentGeneration={currentGen}
             isLoading={hasCurrentUserGenerationWork}
             modelStatus={modelStatus}
             onGenerate={handleGenerate}
             pendingGenParams={displayedGenParams ?? undefined}
             genKey={genKey}
             isViewingActiveGeneration={isViewingCurrentUserActiveGeneration}
           />
        </div>

        {currentGen && (
          <div className="shrink-0 w-full bg-background relative z-20">
            <PromptInput
              onGenerate={handleGenerate}
              isLoading={hasCurrentUserGenerationWork}
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
