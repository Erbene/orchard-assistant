/**
 * Shared domain types. Mirrors the orchard-server (FastAPI) schemas.
 * Descriptive fields (`species`, `variety`, `soil_drainage`, `water_source`)
 * are free text - stored as typed, no enums, no coercion. `zone_id` is
 * assigned by the database (auto-increment).
 */

export interface Zone {
  zone_id: number;
  name: string;
  soil_drainage: string | null;
  water_source: string | null;
}

export interface ZoneInput {
  name: string;
  soil_drainage?: string | null;
  water_source?: string | null;
}

export interface ZonePatch {
  name?: string;
  soil_drainage?: string | null;
  water_source?: string | null;
}

export interface Tree {
  tree_id: number;
  species: string;
  variety: string;
  zone_id: number | null;
  planted_date: string | null;
  additional_context: string | null;
  notes: string | null;
  age_days: number | null;
  age_years: number | null;
}

export interface TreeInput {
  species: string;
  variety: string;
  zone_id?: number | null;
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
