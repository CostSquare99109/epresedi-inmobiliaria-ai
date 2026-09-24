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