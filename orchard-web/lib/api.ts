/**
 * Typed fetch wrapper for the FastAPI backend.
 *
 * Calls are same-origin and version-prefixed (`/api/v1/...`); `next.config.ts`
 * rewrites them to `${FASTAPI_URL}/api/v1/...`. Non-2xx responses throw
 * {@link ApiError} so form handlers can read `.status` / `.detail` / `.field`.
 */
import type { Conversation, ConversationDetail } from "./chat/types";
import type {
  ApiErrorBody,
  CarePlan,
  DemoApplyResult,
  DemoCatalog,
  ExecutedTask,
  InboxTask,
  IrrigationOverview,
  SupervisorConfig,
  SupervisorProposal,
  SupervisorRunResult,
  ZoneConfig,
  RachioDevice,
  ReportResult,
  ScheduleState,
  Source,
  SourceDetail,
  TaskRead,
  TaskTemplate,
  TaskTemplatePatch,
  Tree,
  TreeInput,
  TreePatch,
  TreePhenology,
  ZoneDetail,
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

/**
 * Rachio irrigation zones. Read-only except `water` (a manual run) — there is
 * deliberately no create / update / delete. Zone config is edited in the
 * Rachio app.
 */
export const zonesApi = {
  list: () => apiClient.get<RachioDevice[]>(`${API_PREFIX}/zones`),
  get: (zoneId: string) =>
    apiClient.get<ZoneDetail>(`${API_PREFIX}/zones/${encodeURIComponent(zoneId)}`),
  water: (zoneId: string, durationMinutes: number) =>
    apiClient.post<{ status: string }>(
      `${API_PREFIX}/zones/${encodeURIComponent(zoneId)}/water`,
      { duration_minutes: durationMinutes },
    ),
};

export const treesApi = {
  list: (query?: { species?: string; zone_id?: string }) =>
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

/** Phase 4 - the Foreman's interactive JIT scheduling loop. */
export const scheduleApi = {
  plan: (availableMinutes?: number) =>
    apiClient.post<ScheduleState>(`${API_PREFIX}/schedule/plan`, {
      available_minutes: availableMinutes ?? null,
    }),
  resumeTime: (threadId: string, availableMinutes: number) =>
    apiClient.post<ScheduleState>(`${API_PREFIX}/schedule/resume`, {
      thread_id: threadId,
      available_minutes: availableMinutes,
    }),
  resumeResources: (threadId: string, haveResources: string[]) =>
    apiClient.post<ScheduleState>(`${API_PREFIX}/schedule/resume`, {
      thread_id: threadId,
      have_resources: haveResources,
    }),
  complete: (taskIds: number[]) =>
    apiClient.post<TaskRead[]>(`${API_PREFIX}/schedule/complete`, {
      task_ids: taskIds,
    }),
  report: (text: string, threadId?: string) =>
    apiClient.post<ReportResult>(`${API_PREFIX}/schedule/report`, {
      thread_id: threadId ?? null,
      text,
    }),
};

/** Per-tree Care Plan: generate (Agronomist), edit templates, run the
 *  baseline wizard to materialise the first recurring tasks. */
export const carePlanApi = {
  get: (treeId: number) =>
    apiClient.get<CarePlan>(`${API_PREFIX}/trees/${treeId}/care-plan`),
  generate: (treeId: number) =>
    apiClient.post<CarePlan>(`${API_PREFIX}/trees/${treeId}/care-plan/generate`),
  baseline: (
    treeId: number,
    answers: { template_id: number; last_done: string | null }[],
    phenology?: Partial<TreePhenology>,
  ) =>
    apiClient.post<TaskRead[]>(
      `${API_PREFIX}/trees/${treeId}/care-plan/baseline`,
      {
        answers,
        flowering_month: phenology?.flowering_month ?? null,
        harvest_month: phenology?.harvest_month ?? null,
        dormancy_month: phenology?.dormancy_month ?? null,
        flowering_months: phenology?.flowering_months ?? [],
        harvest_months: phenology?.harvest_months ?? [],
        dormancy_months: phenology?.dormancy_months ?? [],
      },
    ),
  updateTemplate: (templateId: number, patch: TaskTemplatePatch) =>
    apiClient.patch<TaskTemplate>(
      `${API_PREFIX}/care-plan/templates/${templateId}`,
      patch,
    ),
  deleteTemplate: (templateId: number) =>
    apiClient.del(`${API_PREFIX}/care-plan/templates/${templateId}`),
};

/** Irrigation supervisor (Phase 3): schedule config + the HITL approval queue. */
export const irrigationApi = {
  overview: () =>
    apiClient.get<IrrigationOverview>(`${API_PREFIX}/irrigation/overview`),
  updateSupervisor: (patch: Partial<SupervisorConfig>) =>
    apiClient.put<SupervisorConfig>(
      `${API_PREFIX}/irrigation/config/supervisor`,
      patch,
    ),
  updateZone: (
    zoneId: string,
    patch: Partial<Omit<ZoneConfig, "zone_id" | "tree_count">>,
  ) =>
    apiClient.put<ZoneConfig>(
      `${API_PREFIX}/irrigation/config/zones/${encodeURIComponent(zoneId)}`,
      patch,
    ),
  runSupervisor: (zoneIds?: string[]) =>
    apiClient.post<SupervisorRunResult>(`${API_PREFIX}/irrigation/supervisor/run`, {
      zone_ids: zoneIds ?? null,
    }),
  proposals: (status?: string) =>
    apiClient.get<SupervisorProposal[]>(`${API_PREFIX}/irrigation/proposals`, {
      query: { status },
    }),
  approve: (threadId: string) =>
    apiClient.post<SupervisorProposal>(
      `${API_PREFIX}/irrigation/proposals/${encodeURIComponent(threadId)}/approve`,
    ),
  reject: (threadId: string) =>
    apiClient.post<SupervisorProposal>(
      `${API_PREFIX}/irrigation/proposals/${encodeURIComponent(threadId)}/reject`,
    ),
  demoCatalog: () =>
    apiClient.get<DemoCatalog>(`${API_PREFIX}/irrigation/demo`),
  applyDemo: (id: string) =>
    apiClient.post<DemoApplyResult>(
      `${API_PREFIX}/irrigation/demo/${encodeURIComponent(id)}/apply`,
    ),
};

/** The schedule inbox: generated tasks, and closing them out. */
export const tasksApi = {
  list: () => apiClient.get<InboxTask[]>(`${API_PREFIX}/tasks`),
  history: (params?: {
    tree_id?: number;
    outcome?: "completed" | "skipped";
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.tree_id != null) q.set("tree_id", String(params.tree_id));
    if (params?.outcome) q.set("outcome", params.outcome);
    if (params?.limit != null) q.set("limit", String(params.limit));
    const qs = q.toString();
    return apiClient.get<ExecutedTask[]>(
      `${API_PREFIX}/tasks/history${qs ? `?${qs}` : ""}`,
    );
  },
  complete: (id: number) =>
    apiClient.post<TaskRead>(`${API_PREFIX}/tasks/${id}/complete`),
  skip: (id: number) => apiClient.post<TaskRead>(`${API_PREFIX}/tasks/${id}/skip`),
  defer: (id: number) => apiClient.post<TaskRead>(`${API_PREFIX}/tasks/${id}/defer`),
};

/** Persisted assistant conversations (history sidebar). The turn itself is
 *  streamed via `/api/chat`; these are the list / read / rename / delete. */
export const conversationsApi = {
  list: () => apiClient.get<Conversation[]>(`${API_PREFIX}/conversations`),
  get: (id: number) =>
    apiClient.get<ConversationDetail>(`${API_PREFIX}/conversations/${id}`),
  rename: (id: number, title: string) =>
    apiClient.patch<Conversation>(`${API_PREFIX}/conversations/${id}`, { title }),
  remove: (id: number) => apiClient.del(`${API_PREFIX}/conversations/${id}`),
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
