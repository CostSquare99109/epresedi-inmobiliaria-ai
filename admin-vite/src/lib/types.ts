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
  street: string;
  street_number: string;
  descriptive_location: string;
  area_m2: number | null;
  floors: number | null;
  floor_offer_type: string;
  offered_floors: number[];
  has_kitchen: boolean;
  has_living_room: boolean;
  has_laundry_area: boolean;
  bedrooms: number | null;
  bedrooms_description: string;
  bathrooms: number | null;
  bathrooms_description: string;
  living_room_description: string;
  laundry_area_description: string;
  parking_spaces: number | null;
  has_parking: boolean;
  parking_description: string;
  rent_price: number | null;
  services_included: string;
  nomenclatura: string;
  visiting_hours: VisitingHour[];
  status: string;
  features: string[];
  branch: string | null;
  branch_id: string | null;
  latitude: number | null;
  longitude: number | null;
  description: string;
}

export interface VisitingHour {
  weekday: number; // 0=Monday..6=Sunday
  weekday_name: string;
  is_closed: boolean;
  intervals: TimeInterval[];
}

export interface TimeInterval {
  start: string; // HH:MM
  end: string; // HH:MM
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

export interface HealthDTO {
  ok: boolean;
  checks: Record<string, boolean>;
  errors: Record<string, string>;
}

// Dashboard Stats Types
export interface DashboardStatsDTO {
  properties: {
    total: number;
    by_status: Record<string, number>;
    by_operation: Record<string, number>;
    by_type: Record<string, number>;
    without_images: number;
    recent: Array<{
      id: string;
      code: string;
      title: string;
      status: string;
      operation: string;
      created_at: string;
    }>;
  };
  leads: {
    total: number;
    by_status: Record<string, number>;
  };
  appointments: {
    total: number;
    by_status: Record<string, number>;
    upcoming: Array<{
      id: string;
      property_id: string;
      property_code?: string | null;
      property_title?: string | null;
      property_address?: string | null;
      lead_id: string | null;
      scheduled_at: string;
      status: string;
      notes: string;
    }>;
    today: Array<{
      id: string;
      property_id: string;
      property_code?: string | null;
      property_title?: string | null;
      property_address?: string | null;
      lead_id: string | null;
      scheduled_at: string;
      status: string;
      notes: string;
    }>;
  };
  conversations: {
    total: number;
    recent: Array<{
      id: string;
      user_id: number;
      summary: string;
      updated_at: string;
    }>;
  };
  activity: Array<{
    id: number;
    action: string;
    action_label: string;
    entity: string;
    entity_id: string | null;
    metadata: Record<string, any>;
    actor_name: string;
    created_at: string;
  }>;
  system: {
    timestamp: string;
  };
}

export interface DashboardPropertyStatus {
  key: string;
  label: string;
  count: number;
  tone: "success" | "warn" | "danger" | "neutral" | "info";
}

export interface DashboardOperation {
  key: string;
  label: string;
  count: number;
}

export interface DashboardPropertyType {
  key: string;
  label: string;
  count: number;
}

export interface DashboardActivityItem {
  id: number;
  action: string;
  action_label: string;
  entity: string;
  entity_id: string | null;
  metadata: Record<string, any>;
  actor_name: string;
  created_at: string;
}

export interface DashboardUpcomingAppointment {
  id: string;
  property_id: string;
  property_code?: string | null;
  property_title?: string | null;
  property_address?: string | null;
  lead_id: string | null;
  scheduled_at: string;
  status: string;
  notes: string;
}