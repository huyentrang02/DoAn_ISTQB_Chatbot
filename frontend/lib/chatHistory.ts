import { supabase } from './supabaseClient'

export interface Message {
  id?: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  image_url?: string
}

/**
 * Lấy lịch sử chat từ database
 */
export async function getChatHistory(): Promise<Message[]> {
  try {
    const { data, error } = await supabase
      .from('chat_history')
      .select('id, role, content, message_timestamp, image_url')
      .order('message_timestamp', { ascending: true })

    if (error) {
      console.error('Error fetching chat history:', error)
      return []
    }

    // Map message_timestamp to timestamp for compatibility
    return (data || []).map(msg => ({
      ...msg,
      timestamp: msg.message_timestamp,
      image_url: msg.image_url
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
        message_timestamp: message.timestamp,
        image_url: message.image_url
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

/**
 * Upload ảnh lên Supabase Storage và trả về public URL
 */
export async function uploadImage(file: File): Promise<string | null> {
  try {
    const { data: { user } } = await supabase.auth.getUser()
    
    if (!user) {
      console.error('No authenticated user for image upload')
      return null
    }

    // Path pattern: {user_id}/{timestamp}.{ext}
    const ext = file.name.split('.').pop() || 'png'
    const fileName = `${Date.now()}.${ext}`
    const filePath = `${user.id}/${fileName}`

    const { error: uploadError } = await supabase.storage
      .from('chat-images')
      .upload(filePath, file)

    if (uploadError) {
      console.error('Error uploading image to Supabase:', uploadError)
      return null
    }

    // Lấy public URL
    const { data } = supabase.storage
      .from('chat-images')
      .getPublicUrl(filePath)

    return data.publicUrl
  } catch (error) {
    console.error('Error uploading image:', error)
    return null
  }
}


