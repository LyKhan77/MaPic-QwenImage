import { useState } from 'react'
import { supabase } from '../lib/supabase'
import { motion, AnimatePresence } from 'framer-motion'
import { Eye, EyeOff, Mail, Lock, LogIn, AlertCircle } from 'lucide-react'
import { toast } from 'sonner'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [isSignUp, setIsSignUp] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)

  const handleEmailAuth = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setAuthError(null)

    try {
      if (isSignUp) {
        const { error } = await supabase.auth.signUp({ 
          email, 
          password,
          options: {
            emailRedirectTo: window.location.origin
          }
        })
        if (error) throw error
        toast.success('Registration successful! Check your email for verification.')
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        if (error) {
          // Specific feedback for common errors
          if (error.message === 'Invalid login credentials') {
            throw new Error('Invalid email or password. Please try again.')
          }
          if (error.message === 'Email not confirmed') {
            throw new Error('Email not confirmed. Please check your inbox.')
          }
          throw error
        }
        toast.success('Welcome back!')
      }
    } catch (error: any) {
      const message = error.message || 'Authentication failed'
      setAuthError(message)
      toast.error(message)
    } finally {
      setIsLoading(false)
    }
  }

  // Shake animation for error feedback
  const shakeVariants = {
    shake: {
      x: [0, -10, 10, -10, 10, 0],
      transition: { duration: 0.4 }
    }
  }

  return (
    <div className="flex min-h-dvh w-full items-center justify-center bg-background p-4 relative overflow-hidden">
      {/* Decorative Elements */}
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-primary to-transparent opacity-50" />
      <div className="absolute bottom-0 right-0 w-full h-1 bg-gradient-to-r from-transparent via-secondary to-transparent opacity-50" />
      
      <div className="absolute -top-40 -left-40 w-80 h-80 bg-primary/20 rounded-full blur-[100px] pointer-events-none mix-blend-screen" />
      <div className="absolute -bottom-40 -right-40 w-80 h-80 bg-secondary/20 rounded-full blur-[100px] pointer-events-none mix-blend-screen" />

      <motion.div 
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="z-10 w-full max-w-md space-y-8 rounded-2xl border border-white/5 bg-black/40 p-8 backdrop-blur-xl shadow-2xl ring-1 ring-white/10"
      >
        <div className="text-center space-y-4 flex flex-col items-center">
          <div className="relative h-16 w-16 mb-2">
            <div className="absolute inset-0 bg-primary/20 blur-xl rounded-full" />
            <img src="/logoMapic.png" alt="MaPic Logo" className="relative h-full w-full object-contain drop-shadow-[0_0_10px_rgba(0,255,255,0.5)]" />
          </div>
          
          <div className="space-y-1">
            <h1 className="text-4xl font-bold tracking-tighter text-transparent bg-clip-text bg-gradient-to-br from-white to-white/50">
              MaPic
            </h1>
            <p className="text-sm text-muted-foreground font-mono">
              AI IMAGE GENERATION STUDIO
            </p>
          </div>
        </div>

        <AnimatePresence mode="wait">
          {authError && (
            <motion.div 
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs font-mono"
            >
              <AlertCircle className="w-4 h-4 shrink-0" />
              <p>{authError}</p>
            </motion.div>
          )}
        </AnimatePresence>

        <form onSubmit={handleEmailAuth} className="space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-mono uppercase text-muted-foreground ml-1">Email Address</label>
            <motion.div 
              className="relative group"
              animate={authError ? "shake" : ""}
              variants={shakeVariants}
            >
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value)
                  if(authError) setAuthError(null)
                }}
                placeholder="commander@mapic.ai"
                className={`w-full bg-black/50 border ${authError ? 'border-destructive/50' : 'border-white/10'} rounded-lg py-2.5 pl-10 pr-4 text-sm font-mono focus:outline-none focus:ring-1 ${authError ? 'focus:ring-destructive' : 'focus:ring-primary'} transition-all`}
              />
            </motion.div>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <label className="text-xs font-mono uppercase text-muted-foreground ml-1">Password</label>
              {!isSignUp && (
                <button type="button" className="relative text-[10px] font-mono uppercase text-primary/60 hover:text-primary transition-colors after:absolute after:-inset-x-2 after:-inset-y-4 after:content-[''] lg:after:hidden">
                  Forgot?
                </button>
              )}
            </div>
            <motion.div 
              className="relative group"
              animate={authError ? "shake" : ""}
              variants={shakeVariants}
            >
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
              <input
                type={showPassword ? 'text' : 'password'}
                required
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  if(authError) setAuthError(null)
                }}
                placeholder="••••••••"
                className={`w-full bg-black/50 border ${authError ? 'border-destructive/50' : 'border-white/10'} rounded-lg py-2.5 pl-10 pr-12 text-sm font-mono focus:outline-none focus:ring-1 ${authError ? 'focus:ring-destructive' : 'focus:ring-primary'} transition-all`}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-3 text-muted-foreground hover:text-white transition-colors"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </motion.div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-primary hover:bg-primary/90 text-black font-mono font-bold py-2.5 rounded-lg flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50"
          >
            {isLoading ? (
              <div className="w-5 h-5 border-2 border-black/20 border-t-black rounded-full animate-spin" />
            ) : (
              <>
                <LogIn className="w-4 h-4" />
                {isSignUp ? 'INITIALIZE ACCOUNT' : 'ESTABLISH LINK'}
              </>
            )}
          </button>
        </form>

        <div className="text-center">
          <button
            onClick={() => {
              setIsSignUp(!isSignUp)
              setAuthError(null)
            }}
            className="relative text-[10px] font-mono uppercase text-muted-foreground hover:text-primary transition-colors after:absolute after:-inset-x-2 after:-inset-y-4 after:content-[''] lg:after:hidden"
          >
            {isSignUp ? 'Already have access? Establishment Link' : 'Need new credentials? Create Account'}
          </button>
        </div>

        <div className="text-center text-[10px] text-muted-foreground font-mono opacity-50 uppercase">
          Secure Connection Established
        </div>
      </motion.div>
    </div>
  )
}
