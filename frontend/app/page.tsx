'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabaseClient'
import { Button } from '@/components/ui/button'
import ChatInterface from '@/components/ChatInterface'
import AdminUpload from '@/components/AdminUpload'

export default function Home() {
  const [session, setSession] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
        setSession(session)
        setLoading(false)
        if (!session) router.push('/login')
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
        setSession(session)
        if (!session) router.push('/login')
    })
    return () => subscription.unsubscribe()
  }, [router])

  if (loading) return <div className="flex items-center justify-center min-h-screen">Loading...</div>
  if (!session) return null

  // Simple role check for demo (real app should use DB/Metadata)
  const isAdmin = session.user.email?.includes('admin') || true // Default to showing both for demo

  return (
    <div className="container mx-auto p-4">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">ISTQB Assistant</h1>
        <div className="flex gap-4">
            <span className="self-center text-sm text-gray-600">{session.user.email}</span>
            <Button variant="outline" onClick={() => supabase.auth.signOut()}>Sign Out</Button>
        </div>
      </div>
      
      <div className="space-y-8">
        <div className="border rounded-lg p-6 bg-white shadow-sm">
            <h2 className="text-xl font-semibold mb-4">Chat Assistant</h2>
            <ChatInterface />
        </div>

        {isAdmin && (
            <div className="border rounded-lg p-6 bg-gray-50">
                <h2 className="text-xl font-semibold mb-4">Admin Area: Upload Documents</h2>
                <AdminUpload />
            </div>
        )}
      </div>
    </div>
  )
}
