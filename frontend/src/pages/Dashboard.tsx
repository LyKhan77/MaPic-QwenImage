import { useState, useEffect } from 'react'
import type { Session } from '@supabase/supabase-js'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import Sidebar from '../components/Sidebar'
import ImageCanvas from '../components/ImageCanvas'
import PromptInput from '../components/PromptInput'
import ModelStatusBadge from '../components/ModelStatusBadge'
import type { Generation } from '../types'
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
      setGenKey((prev) => prev + 1)
      setPendingGenParams({
        steps: vars.options?.num_inference_steps ?? 50,
        numRefImages: vars.images?.length ?? 0,
      })
    },
    onSuccess: (newGen) => {
      queryClient.setQueryData(['history', session.user.id], (old: Generation[] = []) => [newGen, ...old])
      setCurrentGen(newGen)
      toast.success('Image generated successfully!')
    },
    onError: (error) => {
      console.error(error)
      toast.error(error instanceof Error ? error.message : 'Failed to generate image')
    },
    onSettled: () => {
      setPendingGenParams(null)
    },
  })

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
  }

  const handleNewChat = () => {
    setCurrentGen(null)
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
           <div className="absolute top-4 right-6 z-50">
             <ModelStatusBadge status={modelStatus} onLoad={handleLoadModel} onUnload={handleUnloadModel} progress={loadProgress} message={loadMessage} elapsed={loadElapsed} />
           </div>
           <ImageCanvas
             currentGeneration={currentGen}
             isLoading={generateMutation.isPending}
             modelStatus={modelStatus}
             onGenerate={(prompt, images, options) => generateMutation.mutate({ prompt, images, options })}
             pendingGenParams={pendingGenParams ?? undefined}
             genKey={genKey}
           />
        </div>

        {currentGen && (
          <div className="shrink-0 w-full bg-background relative z-20">
            <PromptInput
              onGenerate={(prompt, images, options) => generateMutation.mutate({ prompt, images, options })}
              isLoading={generateMutation.isPending}
              isCentralized={false}
              initialPrompt={currentGen.prompt}
              initialImageUrl={currentGen.public_url}
              modelStatus={modelStatus}
            />
          </div>
        )}
      </main>
    </div>
  )
}
