/**
 * Typed fetch wrapper for the FastAPI backend.
 *
 * Calls are same-origin and version-prefixed (`/api/v1/...`); `next.config.ts`
 * rewrites them to `${FASTAPI_URL}/api/v1/...`. Non-2xx responses throw
 * {@link ApiError} so form handlers can read `.status` / `.detail` / `.field`.
 */
import type {
  ApiErrorBody,
  Source,
  SourceDetail,
  Tree,
  TreeInput,
  TreePatch,
  Zone,
  ZoneInput,
  ZonePatch,
} from "./types";

export const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(
    /** HTTP status code (0 when the request never completed). */
    readonly status: number,
    /** Human-readable message, from the backend's `detail` when present. */
    readonly detail: string,
    /** Offending field name on a 422 `DomainValidationError`, if any. */
    readonly field?: string,
    /** Raw parsed error body, for callers that need more. */
    readonly body?: unknown,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

interface RequestOptions extends Omit<RequestInit, "body" | "method"> {
  /** Appended as a query string; nullish values are skipped. */
  query?: Query;
}

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined) params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  { query, headers, ...init }: RequestOptions = {},
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(withQuery(path, query), {
      ...init,
      method,
      headers: {
        ...(body !== undefined ? { "content-type": "application/json" } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (cause) {
    throw new ApiError(0, "Network error - the backend is unreachable.", undefined, cause);
  }

  if (res.status === 204 || res.headers.get("content-length") === "0") {
    if (!res.ok) throw new ApiError(res.status, `Request failed (${res.status})`);
    return undefined as T;
  }

  const parsed = (await res.json().catch(() => undefined)) as
    | (T & Partial<ApiErrorBody>)
    | undefined;

  if (!res.ok) {
    const err = parsed as ApiErrorBody | undefined;
    throw new ApiError(
      res.status,
      err?.detail ?? `Request failed (${res.status})`,
      err?.field,
      parsed,
    );
  }

  return parsed as T;
}

/** multipart/form-data POST (the browser sets the boundary header). */
async function requestForm<T>(path: string, form: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { method: "POST", body: form });
  } catch (cause) {
    throw new ApiError(0, "Network error - the backend is unreachable.", undefined, cause);
  }
  const parsed = (await res.json().catch(() => undefined)) as
    | (T & Partial<ApiErrorBody>)
    | undefined;
  if (!res.ok) {
    const err = parsed as ApiErrorBody | undefined;
    throw new ApiError(
      res.status,
      err?.detail ?? `Request failed (${res.status})`,
      err?.field,
      parsed,
    );
  }
  return parsed as T;
}

export const apiClient = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("POST", path, body, opts),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("PUT", path, body, opts),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("PATCH", path, body, opts),
  del: <T = void>(path: string, opts?: RequestOptions) =>
    request<T>("DELETE", path, undefined, opts),
  postForm: <T>(path: string, form: FormData) => requestForm<T>(path, form),
};

// --------------------------------------------------------------------------
// Typed resource helpers (thin wrappers over apiClient)
// --------------------------------------------------------------------------

export const zonesApi = {
  list: () => apiClient.get<Zone[]>(`${API_PREFIX}/zones`),
  get: (id: number) => apiClient.get<Zone>(`${API_PREFIX}/zones/${id}`),
  create: (input: ZoneInput) => apiClient.post<Zone>(`${API_PREFIX}/zones`, input),
  update: (id: number, patch: ZonePatch) =>
    apiClient.patch<Zone>(`${API_PREFIX}/zones/${id}`, patch),
  remove: (id: number) => apiClient.del(`${API_PREFIX}/zones/${id}`),
};

export const treesApi = {
  list: (query?: { species?: string; zone_id?: number }) =>
    apiClient.get<Tree[]>(`${API_PREFIX}/trees`, { query }),
  get: (id: number) => apiClient.get<Tree>(`${API_PREFIX}/trees/${id}`),
  create: (input: TreeInput) => apiClient.post<Tree>(`${API_PREFIX}/trees`, input),
  update: (id: number, patch: TreePatch) =>
    apiClient.patch<Tree>(`${API_PREFIX}/trees/${id}`, patch),
  remove: (id: number) => apiClient.del(`${API_PREFIX}/trees/${id}`),
  linkedSources: (id: number) =>
    apiClient.get<Source[]>(`${API_PREFIX}/trees/${id}/sources`),
  setLinkedSources: (id: number, sourceIds: number[]) =>
    apiClient.put<Source[]>(`${API_PREFIX}/trees/${id}/sources`, {
      source_ids: sourceIds,
    }),
};

export const sourcesApi = {
  list: () => apiClient.get<Source[]>(`${API_PREFIX}/sources`),
  get: (id: number) => apiClient.get<SourceDetail>(`${API_PREFIX}/sources/${id}`),
  remove: (id: number) => apiClient.del(`${API_PREFIX}/sources/${id}`),
  rename: (id: number, name: string) =>
    apiClient.patch<Source>(`${API_PREFIX}/sources/${id}`, { name }),
  ingestText: (name: string, text: string) => {
    const form = new FormData();
    form.set("name", name);
    form.set("text", text);
    return apiClient.postForm<Source>(`${API_PREFIX}/sources`, form);
  },
  ingestFile: (name: string, file: File) => {
    const form = new FormData();
    form.set("name", name);
    form.set("file", file);
    return apiClient.postForm<Source>(`${API_PREFIX}/sources`, form);
  },
};
