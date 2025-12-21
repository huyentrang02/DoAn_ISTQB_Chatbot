'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { CardContent } from '@/components/ui/card'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function AdminUpload() {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')

  const handleUpload = async () => {
    if (!file) return

    setUploading(true)
    setMessage('')
    
    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch(`${API_URL}/api/upload`, {
        method: 'POST',
        body: formData,
      })
      
      const data = await res.json()
      
      if (res.ok) {
        setMessage(`Success! Added ${data.chunks_added} chunks.`)
      } else {
        setMessage(`Error: ${data.detail || 'Upload failed'}`)
      }
    } catch (error) {
      setMessage('Error connecting to server')
    } finally {
      setUploading(false)
    }
  }

  return (
    <CardContent className="space-y-4 p-0">
      <div className="grid w-full max-w-sm items-center gap-1.5">
        <Label htmlFor="pdf">ISTQB Document (PDF)</Label>
        <Input 
            id="pdf" 
            type="file" 
            accept=".pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)} 
        />
      </div>
      
      <Button onClick={handleUpload} disabled={!file || uploading}>
        {uploading ? 'Processing...' : 'Upload & Embed'}
      </Button>
      
      {message && (
        <p className={`text-sm ${message.startsWith('Error') ? 'text-red-500' : 'text-green-500'}`}>
            {message}
        </p>
      )}
    </CardContent>
  )
}

