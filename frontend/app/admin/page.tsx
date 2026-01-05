'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabaseClient'
import AdminUpload from '@/components/AdminUpload'
import AppLayout from '@/components/AppLayout'

export default function AdminPage() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    checkAdminRole()
  }, [])

  async function checkAdminRole() {
    const { data: { session } } = await supabase.auth.getSession()
    
    if (!session) {
      router.push('/login')
      return
    }

    // Lấy role từ user metadata trong auth.users
    const role = session.user.user_metadata?.role || 'user'

    if (role !== 'admin') {
      setIsAdmin(false)
      setLoading(false)
      return
    }

    setIsAdmin(true)
    setLoading(false)
  }

  if (loading) return <div className="flex items-center justify-center min-h-screen">Loading...</div>

  if (!isAdmin) {
    return (
      <AppLayout>
        <div className="flex flex-col items-center justify-center h-full">
          <h1 className="text-2xl font-bold text-red-600 mb-4">Access Denied</h1>
          <p className="text-gray-600">Bạn không có quyền truy cập trang này.</p>
        </div>
      </AppLayout>
    )
  }

  return (
    <AppLayout>
      <div className="h-full flex flex-col">
          <AdminUpload />
        </div>
    </AppLayout>
  )
}

