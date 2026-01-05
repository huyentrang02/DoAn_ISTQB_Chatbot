'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabaseClient'
import Sidebar from './Sidebar'

interface AppLayoutProps {
  children: React.ReactNode
}

export default function AppLayout({ children }: AppLayoutProps) {
  const [session, setSession] = useState<any>(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    checkAuth()
  }, [])

  async function checkAuth() {
    const { data: { session } } = await supabase.auth.getSession()
    
    if (!session) {
      router.push('/login')
      return
    }

    setSession(session)

    // Lấy role từ user metadata trong auth.users
    const role = session.user.user_metadata?.role || 'user'
    
    if (role === 'admin') {
      setIsAdmin(true)
    }

    setLoading(false)

    // Listen for auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session) {
        router.push('/login')
      }
    })

    return () => subscription.unsubscribe()
  }

  if (loading) {
    return <div className="flex items-center justify-center min-h-screen">Loading...</div>
  }

  if (!session) return null

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar isAdmin={isAdmin} userEmail={session.user.email} />
      <main className="flex-1 overflow-hidden bg-gray-50">
        {children}
      </main>
    </div>
  )
}

