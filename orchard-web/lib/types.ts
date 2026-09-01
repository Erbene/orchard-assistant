/**
 * Shared domain types. Mirrors the orchard-server (FastAPI) schemas.
 * Descriptive fields (`species`, `variety`) are free text - stored as typed,
 * no enums, no coercion. Irrigation zones live in Rachio (read-only).
 */

/**
 * Irrigation zones come from the grower's Rachio account. They are
 * **read-only** here — every setting is edited in the official Rachio app.
 * Shapes mirror `app/services/rachio.py` (serialized snake_case).
 */
export interface RachioCustom {
  name?: string;
  [key: string]: unknown;
}

export interface RachioZone {
  id: string;
  name: string;
  enabled: boolean;
  zone_number: number;
  custom_nozzle: RachioCustom | null;
  custom_soil: RachioCustom | null;
  custom_slope: RachioCustom | null;
  custom_crop: RachioCustom | null; // vegetation type
  custom_shade: RachioCustom | null; // sun exposure
  [key: string]: unknown;
}

export interface RachioDevice {
  id: string;
  name: string;
  status: string;
  model: string | null;
  zones: RachioZone[];
  [key: string]: unknown;
}

export interface ZoneDetail {
  device_id: string;
  device_name: string;
  zone: RachioZone;
}

export interface Tree {
  tree_id: number;
  species: string;
  variety: string;
  /** Rachio zone id (free text; not validated). */
  zone_id: string | null;
  planted_date: string | null;
  additional_context: string | null;
  notes: string | null;
  age_days: number | null;
  age_years: number | null;
}

export interface TreeInput {
  species: string;
  variety: string;
  zone_id?: string | null;
  planted_date?: string | null;
  additional_context?: string | null;
  notes?: string | null;
}

export type TreePatch = Partial<TreeInput>;

export type SourceType = "file" | "text";

export interface Source {
  id: number;
  name: string;
  source_type: SourceType;
  file_path: string | null;
  upload_date: string;
}

export interface SourceDetail extends Source {
  raw_content: string;
}

/** Shape of a 4xx body returned by the FastAPI error handlers. */
export interface ApiErrorBody {
  detail: string;
  /** Present on 422 DomainValidationError - the offending field name. */
  field?: string;
}
