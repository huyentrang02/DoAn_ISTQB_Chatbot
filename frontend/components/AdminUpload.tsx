'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function AdminUpload() {
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')
  const [uploadProgress, setUploadProgress] = useState('')

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files
    if (selectedFiles && selectedFiles.length > 0) {
      setFiles(Array.from(selectedFiles))
      setMessage('')
    }
  }

  const removeFile = (index: number) => {
    setFiles(files.filter((_, i) => i !== index))
  }

  const handleUpload = async () => {
    if (files.length === 0) return

    setUploading(true)
    setMessage('')
    setUploadProgress('')
    
    let totalChunks = 0
    let successCount = 0
    let failCount = 0

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      setUploadProgress(`Uploading ${i + 1}/${files.length}: ${file.name}`)
      
      const formData = new FormData()
      formData.append('file', file)

      try {
        const res = await fetch(`${API_URL}/api/upload`, {
          method: 'POST',
          body: formData,
        })
        
        const data = await res.json()
        
        if (res.ok) {
          totalChunks += data.chunks_added
          successCount++
        } else {
          failCount++
        }
      } catch (error) {
        failCount++
      }
    }

    setUploading(false)
    setUploadProgress('')
    
    if (failCount === 0) {
      setMessage(`Success! Uploaded ${successCount} file(s), added ${totalChunks} chunks.`)
      setFiles([])
    } else if (successCount === 0) {
      setMessage(`Error: All ${failCount} file(s) failed to upload.`)
    } else {
      setMessage(`Partial success: ${successCount} succeeded, ${failCount} failed. Added ${totalChunks} chunks.`)
    }
  }

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header - giống ChatInterface */}
      <div className="flex items-center justify-between px-6 py-4 border-b bg-white">
        <h2 className="text-xl font-semibold text-gray-800">Upload ISTQB Documents</h2>
      </div>

      {/* Content Area - centered */}
      <div className="flex-1 flex items-center justify-center px-6 py-8 bg-gray-50/30">
        <div className="w-full max-w-2xl">
          <div className="border rounded-lg p-8 bg-white shadow-sm space-y-6">
            {/* File Input */}
            <div className="space-y-3">
              <Label htmlFor="pdf" className="text-sm font-medium text-gray-700">
                Select PDF Files
              </Label>
              <div className="flex items-center gap-3">
                {/* Button chọn tệp - 1 phần */}
                <label 
                  htmlFor="pdf" 
                  className="flex-shrink-0 px-6 py-2.5 bg-blue-600 text-white rounded-lg font-medium cursor-pointer hover:bg-blue-700 transition-colors text-center"
                >
                  Chọn tệp
                </label>
                
                {/* Text hiển thị số lượng file - 9 phần */}
                <div className="flex-1 px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600">
                  {files.length > 0 ? (
                    <span className="flex items-center gap-2">
                      <svg className="w-4 h-4 text-blue-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <span className="font-medium text-gray-800">
                        {files.length} tệp đã chọn
                      </span>
                    </span>
                  ) : (
                    'Không có tệp nào được chọn'
                  )}
                </div>
                
                {/* Hidden file input with multiple */}
                <Input 
                  id="pdf" 
                  type="file" 
                  accept=".pdf"
                  multiple
                  onChange={handleFileSelect}
                  className="hidden"
                />
              </div>

              {/* Danh sách file đã chọn */}
              {files.length > 0 && (
                <div className="mt-3 space-y-2 max-h-60 overflow-y-auto">
                  {files.map((file, index) => (
                    <div 
                      key={index}
                      className="flex items-center justify-between gap-2 p-3 bg-blue-50 rounded-lg border border-blue-200 hover:bg-blue-100 transition-colors"
                    >
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        <svg className="w-4 h-4 text-blue-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <span className="text-sm text-blue-700 font-medium truncate">
                          {file.name}
                        </span>
                        <span className="text-xs text-blue-500 flex-shrink-0">
                          ({(file.size / 1024 / 1024).toFixed(2)} MB)
                        </span>
                      </div>
                      <button
                        onClick={() => removeFile(index)}
                        disabled={uploading}
                        className="flex-shrink-0 p-1 hover:bg-red-100 rounded transition-colors disabled:opacity-50"
                        title="Remove file"
                      >
                        <svg className="w-4 h-4 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
        
            {/* Upload Progress */}
            {uploadProgress && (
              <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
                <p className="text-sm text-blue-700 font-medium text-center">
                  {uploadProgress}
                </p>
              </div>
            )}

            {/* Upload Button - Centered and not full width */}
            <div className="flex justify-center pt-2">
              <Button 
                onClick={handleUpload} 
                disabled={files.length === 0 || uploading}
                className="px-8 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 transition-all duration-200 shadow-md hover:shadow-lg"
                size="lg"
              >
                {uploading ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    Uploading...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                    Upload {files.length > 0 ? `${files.length} File(s)` : '& Embed'}
                  </span>
                )}
              </Button>
            </div>
            
            {/* Message */}
            {message && (
              <div className={`p-4 rounded-lg border ${
                message.startsWith('Error') 
                  ? 'bg-red-50 border-red-200' 
                  : 'bg-green-50 border-green-200'
              }`}>
                <div className="flex items-start gap-3">
                  {message.startsWith('Error') ? (
                    <svg className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  )}
                  <p className={`text-sm font-medium ${
                    message.startsWith('Error') ? 'text-red-700' : 'text-green-700'
                  }`}>
                    {message}
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

