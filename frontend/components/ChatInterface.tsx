/* eslint-disable @typescript-eslint/no-unused-vars */
"use client";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useEffect, useRef, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Send, ImagePlus, X } from "lucide-react";
import { getChatHistory, saveMessage, clearChatHistory, uploadImage, type Message } from "@/lib/chatHistory";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const MAX_IMAGE_SIZE_MB = 4;

// Message type mở rộng — chỉ dùng ở runtime, không lưu DB
interface MessageWithImage extends Message {
  image_base64?: string;
  image_mime?: string;
}

export default function ChatInterface() {
  const [messages, setMessages] = useState<MessageWithImage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);

  // Image state
  const [pendingImage, setPendingImage] = useState<string | null>(null); // base64
  const [pendingMime, setPendingMime] = useState<string>("image/png");
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load messages from database on mount
  useEffect(() => {
    loadChatHistory();
  }, []);

  async function loadChatHistory() {
    setHistoryLoading(true);
    try {
      const history = await getChatHistory();
      setMessages(history);
    } catch (error) {
      console.error("Error loading chat history:", error);
    } finally {
      setHistoryLoading(false);
    }
  }

  // Auto scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── Image helpers ──────────────────────────────────────────────────────────

  const processImageFile = useCallback((file: File) => {
    setImageError(null);

    if (!file.type.startsWith("image/")) {
      setImageError("Chỉ hỗ trợ file ảnh (PNG, JPG, GIF, WEBP).");
      return;
    }

    if (file.size > MAX_IMAGE_SIZE_MB * 1024 * 1024) {
      setImageError(`Ảnh quá lớn. Vui lòng chọn ảnh dưới ${MAX_IMAGE_SIZE_MB}MB.`);
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      const result = e.target?.result as string;
      // result = "data:image/png;base64,XXXX..." → bỏ prefix
      const base64 = result.split(",")[1];
      setPendingImage(base64);
      setPendingMime(file.type);
      setPendingFile(file);
    };
    reader.readAsDataURL(file);
  }, []);

  // Ctrl+V paste ảnh từ clipboard
  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const items = Array.from(e.clipboardData.items);
      const imageItem = items.find((item) => item.type.startsWith("image/"));
      if (imageItem) {
        e.preventDefault();
        const file = imageItem.getAsFile();
        if (file) processImageFile(file);
      }
      // Nếu không có ảnh → paste text bình thường (mặc định của browser)
    },
    [processImageFile]
  );

  // Drag & drop
  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file) processImageFile(file);
    },
    [processImageFile]
  );

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
  };

  // Click upload
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processImageFile(file);
    // Reset để có thể chọn lại cùng file
    e.target.value = "";
  };

  const removePendingImage = () => {
    setPendingImage(null);
    setPendingFile(null);
    setImageError(null);
  };

  // ── Send ───────────────────────────────────────────────────────────────────

  const handleSend = async () => {
    if (!input.trim() && !pendingImage) return;

    const imageToSend = pendingImage;
    const mimeToSend = pendingMime;

    const userMsg: MessageWithImage = {
      role: "user",
      content: input,
      timestamp: Date.now(),
      image_base64: imageToSend ?? undefined,
      image_mime: mimeToSend,
    };

    // Thêm message vào UI để user thấy ngay (tạm thời không có image_url)
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setPendingImage(null);

    // Lưu lại file cần upload vì ta sẽ xóa pendingFile khỏi UI
    const fileToUpload = pendingFile;
    setPendingFile(null);
    setLoading(true);

    let imageUrl = undefined;
    if (fileToUpload) {
      const uploadedUrl = await uploadImage(fileToUpload);
      if (uploadedUrl) {
        imageUrl = uploadedUrl;
        userMsg.image_url = uploadedUrl;

        // Update URL trong messages list (để không bị mất khi render lại nếu k có base64)
        setMessages((prev) => prev.map(m => m === userMsg ? userMsg : m));
      }
    }

    // Lưu DB (lưu text và image_url)
    await saveMessage({
      role: userMsg.role,
      content: userMsg.content,
      timestamp: userMsg.timestamp,
      image_url: imageUrl
    });

    const recentHistory = messages.slice(-4).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: userMsg.content,
          history: recentHistory,
          image_base64: imageToSend ?? null,
          image_mime: imageToSend ? mimeToSend : null,
        }),
      });

      if (!res.ok) throw new Error("Network response was not ok");
      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");

      let fullContent = "";
      const assistantMsg: MessageWithImage = {
        role: "assistant",
        content: "",
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, assistantMsg]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        fullContent += decoder.decode(value, { stream: true });
        setMessages((prev) => {
          const newMessages = [...prev];
          newMessages[newMessages.length - 1] = {
            ...newMessages[newMessages.length - 1],
            content: fullContent,
          };
          return newMessages;
        });
      }

      assistantMsg.content = fullContent;
      await saveMessage({ role: assistantMsg.role, content: assistantMsg.content, timestamp: assistantMsg.timestamp });
    } catch (error) {
      const errorMsg: MessageWithImage = {
        role: "assistant",
        content: "Error connecting to server.",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
      await saveMessage({ role: errorMsg.role, content: errorMsg.content, timestamp: errorMsg.timestamp });
    } finally {
      setLoading(false);
    }
  };

  const handleClearHistory = async () => {
    if (confirm("Are you sure you want to clear chat history?")) {
      const success = await clearChatHistory();
      if (success) {
        setMessages([]);
      } else {
        alert("Failed to clear chat history. Please try again.");
      }
    }
  };

  if (historyLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading chat history...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-white">
        <h2 className="text-xl font-semibold text-gray-800">ISTQB Chat Assistant</h2>
        {messages.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClearHistory}
            className="text-gray-500 hover:text-red-500"
          >
            Clear History
          </Button>
        )}
      </div>

      {/* Messages Area */}
      <div
        className={`flex-1 px-6 py-4 bg-white ${messages.length > 0
          ? "overflow-y-auto space-y-4"
          : "overflow-hidden flex items-center justify-center"
          }`}
      >
        {messages.length === 0 && (
          <div className="text-center text-gray-500">
            <p className="text-lg font-medium">Welcome to ISTQB Assistant!</p>
            <p className="text-sm mt-2">Ask me anything about the syllabus.</p>
            <p className="text-xs mt-1 text-gray-400">Tip: Paste an image with Ctrl+V or click the 📎 icon</p>
          </div>
        )}

        {messages.map((m, i) => {
          if (!m.content && !m.image_base64 && !m.image_url) return null;
          return (
            <div
              key={i}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-lg p-3 ${m.role === "user"
                  ? "bg-blue-100 border border-blue-200 text-blue-900 shadow-sm"
                  : "bg-gray-100 border border-gray-200 text-gray-900 shadow-sm"
                  }`}
              >
                {/* Ảnh thumbnail trong user bubble */}
                {m.role === "user" && (m.image_url || m.image_base64) && (
                  <div className="mb-2">
                    <img
                      src={m.image_url ? m.image_url : `data:${m.image_mime ?? "image/png"};base64,${m.image_base64}`}
                      alt="Attached"
                      className="max-h-48 max-w-xs rounded-md object-contain border border-blue-300 cursor-pointer"
                      onClick={() => {
                        // Mở ảnh đầy đủ trong tab mới
                        const win = window.open();
                        win?.document.write(
                          `<img src="${m.image_url ? m.image_url : `data:${m.image_mime ?? "image/png"};base64,${m.image_base64}`}" style="max-width:100%" />`
                        );
                      }}
                      title="Click để xem đầy đủ"
                    />
                  </div>
                )}

                {m.role === "user" ? (
                  <div className="whitespace-pre-wrap">{m.content}</div>
                ) : (
                  <div className="prose prose-sm max-w-none">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        p: ({ node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
                        ul: ({ node, ...props }) => <ul className="list-disc list-inside mb-2" {...props} />,
                        ol: ({ node, ...props }) => <ol className="list-decimal list-inside mb-2" {...props} />,
                        li: ({ node, ...props }) => <li className="ml-2" {...props} />,
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        code: ({ node, inline, ...props }: any) =>
                          inline ? (
                            <code className="bg-gray-100 px-1 py-0.5 rounded text-sm font-mono" {...props} />
                          ) : (
                            <code className="block bg-gray-100 p-2 rounded text-sm font-mono overflow-x-auto" {...props} />
                          ),
                        strong: ({ node, ...props }) => <strong className="font-bold" {...props} />,
                        em: ({ node, ...props }) => <em className="italic" {...props} />,
                        h1: ({ node, ...props }) => <h1 className="text-xl font-bold mb-2" {...props} />,
                        h2: ({ node, ...props }) => <h2 className="text-lg font-bold mb-2" {...props} />,
                        h3: ({ node, ...props }) => <h3 className="text-base font-bold mb-1" {...props} />,
                        blockquote: ({ node, ...props }) => (
                          <blockquote className="border-l-4 border-gray-300 pl-3 italic" {...props} />
                        ),
                      }}
                    >
                      {m.content}
                    </ReactMarkdown>
                  </div>
                )}
                <div
                  className={`text-[10px] mt-1 ${m.role === "user" ? "text-blue-500" : "text-gray-400"
                    }`}
                >
                  {new Date(m.timestamp).toLocaleTimeString()}
                </div>
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border rounded-lg p-3 shadow-sm">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0.2s" }}></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0.4s" }}></div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div
        className="border-t border-gray-200 bg-white px-6 py-4"
        onDrop={handleDrop}
        onDragOver={handleDragOver}
      >
        {/* Image Preview */}
        {pendingImage && (
          <div className="mb-3 relative inline-block">
            <img
              src={`data:${pendingMime};base64,${pendingImage}`}
              alt="Preview"
              className="h-24 max-w-xs rounded-lg object-contain border border-gray-300 shadow-sm"
            />
            <button
              onClick={removePendingImage}
              className="absolute -top-2 -right-2 bg-gray-700 text-white rounded-full w-5 h-5 flex items-center justify-center hover:bg-red-500 transition-colors"
              title="Xoá ảnh"
            >
              <X size={12} />
            </button>
          </div>
        )}

        {/* Image error */}
        {imageError && (
          <p className="text-red-500 text-xs mb-2">{imageError}</p>
        )}

        <div className="relative flex items-end gap-2">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileChange}
          />

          {/* Image upload button */}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => fileInputRef.current?.click()}
            disabled={loading}
            className="shrink-0 h-9 w-9 text-gray-400 hover:text-blue-500 hover:bg-blue-50 transition-colors"
            title="Đính kèm ảnh (hoặc Ctrl+V để dán)"
          >
            <ImagePlus size={18} />
          </Button>

          <div className="relative flex-1">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                pendingImage
                  ? "Hỏi về ảnh này... (Enter để gửi)"
                  : "Nhập câu hỏi... (Enter gửi, Shift+Enter xuống dòng, Ctrl+V dán ảnh)"
              }
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              onPaste={handlePaste}
              disabled={loading}
              rows={3}
              className="resize-none pr-12"
            />
            <Button
              onClick={handleSend}
              disabled={loading || (!input.trim() && !pendingImage)}
              size="icon"
              className="absolute right-2 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full cursor-pointer transition-all duration-200 hover:scale-110 hover:shadow-md disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              <Send size={18} />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
