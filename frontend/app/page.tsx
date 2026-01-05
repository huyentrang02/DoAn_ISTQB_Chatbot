'use client'
import ChatInterface from '@/components/ChatInterface'
import AppLayout from '@/components/AppLayout'

export default function Home() {
  return (
    <AppLayout>
      <div className="h-full flex flex-col">
        <ChatInterface />
      </div>
    </AppLayout>
  )
}
