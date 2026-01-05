/* eslint-disable @typescript-eslint/no-unused-vars */
"use client";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Send } from "lucide-react";
import { getChatHistory, saveMessage, clearChatHistory, type Message } from "@/lib/chatHistory";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Load messages from database on mount
  useEffect(() => {
    loadChatHistory();
  }, []);

  async function loadChatHistory() {
    setHistoryLoading(true);
    try {
      // Load từ database
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

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMsg: Message = {
      role: "user",
      content: input,
      timestamp: Date.now(),
    };

    // Hiển thị message ngay lập tức
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    // Lưu user message vào DB
    await saveMessage(userMsg);

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userMsg.content }),
      });

      const data = await res.json();

      const assistantMsg: Message = {
        role: "assistant",
        content: res.ok ? data.answer : "Sorry, I encountered an error.",
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, assistantMsg]);
      
      // Lưu assistant message vào DB
      await saveMessage(assistantMsg);
    } catch (error) {
      const errorMsg: Message = {
        role: "assistant",
        content: "Error connecting to server.",
        timestamp: Date.now(),
      };
      
      setMessages((prev) => [...prev, errorMsg]);
      
      // Lưu error message vào DB
      await saveMessage(errorMsg);
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
      <div className="flex items-center justify-between px-6 py-4 border-b bg-white">
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
      <div className={`flex-1 px-6 py-4 bg-gray-50/30 ${messages.length > 0 ? 'overflow-y-auto space-y-4' : 'overflow-hidden flex items-center justify-center'}`}>
        {messages.length === 0 && (
          <div className="text-center text-gray-500">
            <p className="text-lg font-medium">Welcome to ISTQB Assistant!</p>
            <p className="text-sm mt-2">Ask me anything about the syllabus.</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${
              m.role === "user" ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={`max-w-[80%] rounded-lg p-3 ${
                m.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-white border text-gray-900 shadow-sm"
              }`}
            >
              {m.role === "user" ? (
                // User message: plain text with line breaks preserved
                <div className="whitespace-pre-wrap">{m.content}</div>
              ) : (
                // Assistant message: render as markdown
                <div className="prose prose-sm max-w-none">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      // Custom styling for markdown elements
                      p: ({ node, ...props }) => (
                        <p className="mb-2 last:mb-0" {...props} />
                      ),
                      ul: ({ node, ...props }) => (
                        <ul className="list-disc list-inside mb-2" {...props} />
                      ),
                      ol: ({ node, ...props }) => (
                        <ol
                          className="list-decimal list-inside mb-2"
                          {...props}
                        />
                      ),
                      li: ({ node, ...props }) => (
                        <li className="ml-2" {...props} />
                      ),
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      code: ({ node, inline, ...props }: any) =>
                        inline ? (
                          <code
                            className="bg-gray-100 px-1 py-0.5 rounded text-sm font-mono"
                            {...props}
                          />
                        ) : (
                          <code
                            className="block bg-gray-100 p-2 rounded text-sm font-mono overflow-x-auto"
                            {...props}
                          />
                        ),
                      strong: ({ node, ...props }) => (
                        <strong className="font-bold" {...props} />
                      ),
                      em: ({ node, ...props }) => (
                        <em className="italic" {...props} />
                      ),
                      h1: ({ node, ...props }) => (
                        <h1 className="text-xl font-bold mb-2" {...props} />
                      ),
                      h2: ({ node, ...props }) => (
                        <h2 className="text-lg font-bold mb-2" {...props} />
                      ),
                      h3: ({ node, ...props }) => (
                        <h3 className="text-base font-bold mb-1" {...props} />
                      ),
                      blockquote: ({ node, ...props }) => (
                        <blockquote
                          className="border-l-4 border-gray-300 pl-3 italic"
                          {...props}
                        />
                      ),
                    }}
                  >
                    {m.content}
                  </ReactMarkdown>
                </div>
              )}
              <div
                className={`text-[10px] mt-1 ${
                  m.role === "user" ? "text-blue-100" : "text-gray-400"
                }`}
              >
                {new Date(m.timestamp).toLocaleTimeString()}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border rounded-lg p-3 shadow-sm">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                <div
                  className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                  style={{ animationDelay: "0.2s" }}
                ></div>
                <div
                  className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                  style={{ animationDelay: "0.4s" }}
                ></div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t bg-white px-6 py-4">
        <div className="relative flex items-center">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your question... (Press Enter to send, Shift+Enter for new line)"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            disabled={loading}
            rows={3}
            className="resize-none pr-12"
          />
          <Button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            size="icon"
            className="absolute right-2 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full cursor-pointer transition-all duration-200 hover:scale-110 hover:shadow-md disabled:cursor-not-allowed disabled:hover:scale-100"
          >
            <Send size={18} />
          </Button>
        </div>
      </div>
    </div>
  );
}
