/** Shared DTO types for frontend/backend communication. */

export interface PropertyDTO {
  id: string;
  code: string;
  title: string;
  property_type: string;
  operation: string;
  price: number;
  currency: string;
  city: string;
  neighborhood: string;
  address: string;
  area_m2: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  parking_spaces: number | null;
  status: string;
  features: string[];
  project: string | null;
  latitude: number | null;
  longitude: number | null;
  description: string;
}

export interface DocumentDTO {
  id: string;
  title: string;
  filename: string;
  document_type: string;
  status: string;
  version: number;
  chunk_count: number;
  error: string;
  processed_at: string | null;
  property_id: string | null;
  project_id: string | null;
  size_bytes: number;
}

export interface LeadDTO {
  id: string;
  user_id: number;
  name: string;
  phone: string;
  status: string;
  budget: number | null;
  preferences: Record<string, any>;
  notes: string;
  assigned_admin_id: string | null;
  assigned_admin_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppointmentDTO {
  id: string;
  property_id: string;
  lead_id: string | null;
  scheduled_at: string;
  duration_minutes: number;
  status: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface AiEventDTO {
  id: number;
  request_id: string;
  user_id: number | null;
  intent: string;
  model: string;
  tools: { tool: string; ok: boolean }[];
  latency_ms: number;
  status: string;
  created_at: string;
}

export interface ConversationDTO {
  id: string;
  user_id: number;
  summary: string;
  recent: { role: string; content: string }[];
}

export interface HealthDTO {
  ok: boolean;
  checks: Record<string, boolean>;
  errors: Record<string, string>;
}

export interface ProjectDTO {
  id: string;
  name: string;
  description: string;
  city: string;
  property_count: number;
  created_at: string;
  updated_at: string;
}

export interface AdminUserDTO {
  id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuditLogDTO {
  id: number;
  action: string;
  entity: string;
  entity_id: string | null;
  metadata: Record<string, any>;
  result: string;
  error_message: string | null;
  actor_email: string | null;
  actor_name: string | null;
  created_at: string;
}

export interface CmsContentDTO {
  id: string;
  key: string;
  type: string;
  value: string;
  label: string;
  description: string;
  group: string;
  is_public: boolean;
  created_at: string;
  updated_at: string;
}

export interface SystemSettingDTO {
  id: string;
  key: string;
  type: string;
  value: any;
  label: string;
  description: string;
  category: string;
  is_editable: boolean;
  created_at: string;
  updated_at: string;
}