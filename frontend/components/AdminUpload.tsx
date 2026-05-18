'use client'

import { useCallback, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const POLL_INTERVAL_MS = 3000 // Poll mỗi 3 giây

// ─── Types ────────────────────────────────────────────────────────────────────
type JobStatus = 'queued' | 'parsing' | 'chunking' | 'uploading' | 'done' | 'error'

interface JobState {
  job_id: string
  filename: string
  status: JobStatus
  message: string
  progress: number
  chunks_total: number | null
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
const STATUS_LABELS: Record<JobStatus, string> = {
  queued:    'Đang chờ xử lý...',
  parsing:   'Đang phân tích PDF (LlamaParse)...',
  chunking:  'Đang chia tách văn bản...',
  uploading: 'Đang nhúng & lưu vào Vector DB...',
  done:      'Hoàn tất!',
  error:     'Đã xảy ra lỗi',
}

const STATUS_COLORS: Record<JobStatus, string> = {
  queued:    'text-gray-500',
  parsing:   'text-blue-600',
  chunking:  'text-indigo-600',
  uploading: 'text-violet-600',
  done:      'text-green-600',
  error:     'text-red-600',
}

const PROGRESS_BAR_COLORS: Record<JobStatus, string> = {
  queued:    'bg-gray-400',
  parsing:   'bg-blue-500',
  chunking:  'bg-indigo-500',
  uploading: 'bg-violet-500',
  done:      'bg-green-500',
  error:     'bg-red-500',
}

// ─── Component ────────────────────────────────────────────────────────────────
export default function AdminUpload() {
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [jobs, setJobs] = useState<JobState[]>([])
  const pollRefs = useRef<Record<string, ReturnType<typeof setInterval>>>({})

  // ── File selection ──────────────────────────────────────────────────────────
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFiles(Array.from(e.target.files))
    }
  }

  const removeFile = (index: number) => {
    setFiles(files.filter((_, i) => i !== index))
  }

  // ── Polling ─────────────────────────────────────────────────────────────────
  const startPolling = useCallback((job_id: string) => {
    const intervalId = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/api/upload/status/${job_id}`)
        if (!res.ok) return
        const data: JobState = await res.json()

        setJobs(prev =>
          prev.map(j => (j.job_id === job_id ? { ...j, ...data } : j))
        )

        // Dừng polling khi xong hoặc lỗi
        if (data.status === 'done' || data.status === 'error') {
          clearInterval(pollRefs.current[job_id])
          delete pollRefs.current[job_id]

          // Nếu tất cả job đã xong → bật lại nút upload
          setJobs(prev => {
            const allDone = prev.every(
              j => j.status === 'done' || j.status === 'error'
            )
            if (allDone) setUploading(false)
            return prev
          })
        }
      } catch {
        // Bỏ qua lỗi mạng tạm thời
      }
    }, POLL_INTERVAL_MS)

    pollRefs.current[job_id] = intervalId
  }, [])

  // ── Upload handler ──────────────────────────────────────────────────────────
  const handleUpload = async () => {
    if (files.length === 0) return

    setUploading(true)
    setJobs([]) // Reset danh sách job cũ

    for (const file of files) {
      const formData = new FormData()
      formData.append('file', file)

      try {
        const res = await fetch(`${API_URL}/api/upload`, {
          method: 'POST',
          body: formData,
        })

        const data = await res.json()

        if (!res.ok) {
          // API trả về lỗi ngay lập tức (ví dụ: không phải PDF)
          setJobs(prev => [
            ...prev,
            {
              job_id: `err-${Date.now()}`,
              filename: file.name,
              status: 'error',
              message: data.detail || 'Upload thất bại.',
              progress: 0,
              chunks_total: null,
            },
          ])
          continue
        }

        // Thêm job vào danh sách và bắt đầu polling
        const newJob: JobState = {
          job_id: data.job_id,
          filename: file.name,
          status: 'queued',
          message: 'Đã thêm vào hàng chờ...',
          progress: 0,
          chunks_total: null,
        }
        setJobs(prev => [...prev, newJob])
        startPolling(data.job_id)
      } catch {
        setJobs(prev => [
          ...prev,
          {
            job_id: `err-${Date.now()}`,
            filename: file.name,
            status: 'error',
            message: 'Không thể kết nối đến server.',
            progress: 0,
            chunks_total: null,
          },
        ])
      }
    }

    setFiles([]) // Xoá danh sách file đã chọn
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-white">
        <h2 className="text-xl font-semibold text-gray-800">Upload ISTQB Documents</h2>
        <span className="text-xs text-gray-400">PDF → LlamaParse → Vector DB</span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-8 bg-white space-y-6">
        <div className="w-full max-w-2xl mx-auto space-y-6">

          {/* ── Upload Card ──────────────────────────────────────────────── */}
          <div className="border border-gray-200 rounded-xl p-8 bg-gray-50 shadow-sm space-y-6">
            {/* File Input */}
            <div className="space-y-3">
              <Label htmlFor="pdf" className="text-sm font-medium text-gray-700">
                Chọn file PDF để upload
              </Label>
              <div className="flex items-center gap-3">
                <label
                  htmlFor="pdf"
                  className="flex-shrink-0 px-6 py-2.5 bg-blue-600 text-white rounded-lg font-medium cursor-pointer hover:bg-blue-700 transition-colors"
                >
                  Chọn tệp
                </label>
                <div className="flex-1 px-4 py-2.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-500">
                  {files.length > 0
                    ? `${files.length} tệp đã chọn`
                    : 'Chưa có tệp nào được chọn'}
                </div>
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
                <div className="mt-2 space-y-2 max-h-48 overflow-y-auto">
                  {files.map((file, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between gap-2 px-3 py-2 bg-blue-50 rounded-lg border border-blue-200"
                    >
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        <svg className="w-4 h-4 text-blue-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <span className="text-sm text-blue-700 font-medium truncate">{file.name}</span>
                        <span className="text-xs text-blue-400 flex-shrink-0">
                          ({(file.size / 1024 / 1024).toFixed(2)} MB)
                        </span>
                      </div>
                      <button
                        onClick={() => removeFile(idx)}
                        disabled={uploading}
                        className="p-1 hover:bg-red-100 rounded transition-colors disabled:opacity-40"
                      >
                        <svg className="w-4 h-4 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Upload Button */}
            <div className="flex justify-center">
              <Button
                onClick={handleUpload}
                disabled={files.length === 0 || uploading}
                size="lg"
                className="px-8 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 transition-all shadow-md"
              >
                {uploading ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    Đang xử lý...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                    Upload {files.length > 0 ? `${files.length} file` : '& Embed'}
                  </span>
                )}
              </Button>
            </div>
          </div>

          {/* ── Job Progress Cards ────────────────────────────────────────── */}
          {jobs.length > 0 && (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">
                Tiến độ xử lý
              </h3>
              {jobs.map(job => (
                <div
                  key={job.job_id}
                  className={`border rounded-xl p-5 space-y-3 transition-all ${
                    job.status === 'done'
                      ? 'border-green-200 bg-green-50'
                      : job.status === 'error'
                      ? 'border-red-200 bg-red-50'
                      : 'border-blue-200 bg-blue-50'
                  }`}
                >
                  {/* File name + status badge */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <svg className="w-4 h-4 text-gray-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <span className="text-sm font-semibold text-gray-800 truncate">
                        {job.filename}
                      </span>
                    </div>
                    <span className={`text-xs font-semibold flex-shrink-0 ${STATUS_COLORS[job.status]}`}>
                      {STATUS_LABELS[job.status]}
                    </span>
                  </div>

                  {/* Progress bar */}
                  <div className="w-full bg-gray-200 rounded-full h-2.5 overflow-hidden">
                    <div
                      className={`h-2.5 rounded-full transition-all duration-700 ease-out ${PROGRESS_BAR_COLORS[job.status]}`}
                      style={{ width: `${job.progress}%` }}
                    />
                  </div>

                  {/* Details row */}
                  <div className="flex items-center justify-between text-xs text-gray-500">
                    <span className="truncate max-w-[75%]">{job.message}</span>
                    <span className="font-mono font-medium flex-shrink-0">
                      {job.progress}%
                      {job.chunks_total ? ` · ${job.chunks_total} chunks` : ''}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
