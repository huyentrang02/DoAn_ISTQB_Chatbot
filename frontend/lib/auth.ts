import { supabase } from './supabaseClient'

export type UserRole = 'admin' | 'user'

/**
 * Lấy role của user hiện tại từ auth metadata
 */
export async function getUserRole(): Promise<UserRole> {
  const { data: { session } } = await supabase.auth.getSession()
  
  if (!session) {
    return 'user'
  }

  const role = session.user.user_metadata?.role || 'user'
  return role as UserRole
}

/**
 * Kiểm tra user hiện tại có phải admin không
 */
export async function isAdmin(): Promise<boolean> {
  const role = await getUserRole()
  return role === 'admin'
}

/**
 * Lấy thông tin user hiện tại
 */
export async function getCurrentUser() {
  const { data: { session } } = await supabase.auth.getSession()
  
  if (!session) {
    return null
  }

  return {
    id: session.user.id,
    email: session.user.email,
    role: (session.user.user_metadata?.role || 'user') as UserRole,
    metadata: session.user.user_metadata
  }
}

/**
 * Hook để kiểm tra auth state
 */
export function useAuthCheck() {
  const checkAuth = async () => {
    const { data: { session } } = await supabase.auth.getSession()
    return {
      isAuthenticated: !!session,
      user: session?.user,
      role: (session?.user.user_metadata?.role || 'user') as UserRole
    }
  }

  return { checkAuth }
}

