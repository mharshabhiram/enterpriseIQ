export type Role = "ADMIN" | "MANAGER" | "EMPLOYEE";
export type DocStatus = "UPLOADED" | "PROCESSING" | "COMPLETED" | "FAILED";
export type Visibility = "PUBLIC" | "RESTRICTED";

export interface User {
  id: string; name: string; email: string; role: Role; department: string | null;
  is_active: boolean; created_at: string; updated_at: string;
}
export interface DocumentItem {
  id: string; title: string; filename: string; original_filename: string; file_type: string; file_size: number;
  uploaded_by: string; uploader_name: string | null; upload_timestamp: string; department: string | null;
  tags: string[]; description: string | null; processing_status: DocStatus; processing_error: string | null;
  page_count: number | null; chunk_count: number; visibility: Visibility; embedding_model: string | null; can_manage: boolean;
}
export interface Chunk { id: string; chunk_index: number; chunk_text: string; page_number: number | null; section: string | null }
export interface Permission { id: string; role: Role | null; user_id: string | null }
export interface SearchResult {
  chunk_id: string; document_id: string; document_name: string; file_type: string; department: string | null;
  uploaded_by: string; uploader_name: string | null; upload_timestamp: string; tags: string[];
  page: number | null; section: string | null; excerpt: string; similarity: number;
}
export interface SearchResponse { query: string; results: SearchResult[] }
export interface Source {
  source_number: number; document_id: string | null; document_name: string; page: number | null;
  section: string | null; chunk_id: string | null; excerpt: string; relevance_score: number;
}
export interface Message { id: string; conversation_id: string; role: "user" | "assistant"; content: string; created_at: string; sources: Source[] }
export interface Conversation { id: string; title: string; created_at: string; updated_at: string }
export interface ConversationDetail extends Conversation { messages: Message[] }
export interface ChatResponse { conversation_id: string; answer: string; sources: Source[]; message: Message }
export interface SummaryResponse { document_id: string; title: string; type: string; strategy: string; sections_processed: number; summary: string }
export interface Change { type: string; topic: string; document_a: string; document_b: string; explanation: string }
export interface CompareResponse { document_a: string; document_b: string; overview: string; key_differences: string[]; categories: { name: string; changes: Change[] }[] }
export interface Stats {
  total_documents: number; completed_documents: number; processing_documents: number; failed_documents: number;
  total_users: number; total_chunks: number; total_conversations: number; stale_embedding_documents: number;
  top_searches: [string, number][];
  recent_uploads: { id: string; title: string; status: DocStatus; file_type: string; created_at: string }[];
  recent_conversations: { id: string; title: string; updated_at: string }[];
  activity_last_14_days: { day: string; action: string; count: number }[];
}
export interface AuditLog { id: string; user_id: string | null; action: string; resource_type: string | null; resource_id: string | null; metadata: Record<string, unknown>; created_at: string }
export interface AIHealth { reachable: boolean; missing_models: string[]; message: string }
