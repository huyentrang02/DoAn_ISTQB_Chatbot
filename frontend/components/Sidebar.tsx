'use client'

import { useRouter, usePathname } from 'next/navigation'
import { MessageSquare, Upload, LogOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { supabase } from '@/lib/supabaseClient'

interface SidebarProps {
  isAdmin: boolean
  userEmail: string
}

export default function Sidebar({ isAdmin, userEmail }: SidebarProps) {
  const router = useRouter()
  const pathname = usePathname()

  const navItems = [
    {
      name: 'Chatbot',
      icon: MessageSquare,
      path: '/',
      show: true
    },
    {
      name: 'Upload',
      icon: Upload,
      path: '/admin',
      show: isAdmin
    }
  ]

  const handleSignOut = async () => {
    await supabase.auth.signOut()
    router.push('/login')
  }

  return (
    <div className="w-64 h-screen bg-gray-100 text-gray-900 flex flex-col border-r border-gray-200">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <h1 className="text-xl font-bold">ISTQB Assistant</h1>
        <p className="text-xs text-gray-500 mt-1 truncate">{userEmail}</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4">
        <ul className="space-y-2">
          {navItems.filter(item => item.show).map((item) => {
            const Icon = item.icon
            const isActive = pathname === item.path
            
            return (
              <li key={item.path}>
                <button
                  onClick={() => router.push(item.path)}
                  className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors duration-200 ${
                    isActive 
                      ? 'bg-gray-900 hover:bg-black text-white font-medium shadow-md' 
                      : 'hover:bg-gray-200 hover:text-gray-900 text-gray-600'
                  }`}
                >
                  <Icon size={20} />
                  <span>{item.name}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-gray-200">
        <Button 
          variant="ghost" 
          className="w-full justify-start text-gray-600 hover:text-gray-900 hover:bg-gray-200"
          onClick={handleSignOut}
        >
          <LogOut size={20} className="mr-3" />
          Sign Out
        </Button>
      </div>
    </div>
  )
}

