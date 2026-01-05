import { supabase } from './supabaseClient'

export interface Message {
  id?: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

/**
 * Lấy lịch sử chat từ database
 */
export async function getChatHistory(): Promise<Message[]> {
  try {
    const { data, error } = await supabase
      .from('chat_history')
      .select('id, role, content, message_timestamp')
      .order('message_timestamp', { ascending: true })

    if (error) {
      console.error('Error fetching chat history:', error)
      return []
    }

    // Map message_timestamp to timestamp for compatibility
    return (data || []).map(msg => ({
      ...msg,
      timestamp: msg.message_timestamp
    }))
  } catch (error) {
    console.error('Error fetching chat history:', error)
    return []
  }
}

/**
 * Lưu một message vào database
 */
export async function saveMessage(message: Message): Promise<boolean> {
  try {
    const { data: { user } } = await supabase.auth.getUser()
    
    if (!user) {
      console.error('No authenticated user')
      return false
    }

    const { error } = await supabase
      .from('chat_history')
      .insert({
        user_id: user.id,
        role: message.role,
        content: message.content,
        message_timestamp: message.timestamp
      })

    if (error) {
      console.error('Error saving message:', error)
      return false
    }

    return true
  } catch (error) {
    console.error('Error saving message:', error)
    return false
  }
}

/**
 * Lưu nhiều messages cùng lúc (batch insert)
 */
export async function saveMessages(messages: Message[]): Promise<boolean> {
  try {
    const { data: { user } } = await supabase.auth.getUser()
    
    if (!user) {
      console.error('No authenticated user')
      return false
    }

    const records = messages.map(msg => ({
      user_id: user.id,
      role: msg.role,
      content: msg.content,
      message_timestamp: msg.timestamp
    }))

    const { error } = await supabase
      .from('chat_history')
      .insert(records)

    if (error) {
      console.error('Error saving messages:', error)
      return false
    }

    return true
  } catch (error) {
    console.error('Error saving messages:', error)
    return false
  }
}

/**
 * Xóa toàn bộ lịch sử chat
 */
export async function clearChatHistory(): Promise<boolean> {
  try {
    const { error } = await supabase.rpc('clear_chat_history')

    if (error) {
      console.error('Error clearing chat history:', error)
      return false
    }

    return true
  } catch (error) {
    console.error('Error clearing chat history:', error)
    return false
  }
}


