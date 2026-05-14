const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function audioUrl(ticketId: string): string {
  return `${API_BASE_URL}/tickets/${ticketId}/audio`;
}

export function messageAudioUrl(ticketId: string, messageId: string): string {
  return `${API_BASE_URL}/tickets/${ticketId}/messages/${messageId}/audio`;
}

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: BodyInit | Record<string, unknown> | unknown[] | null;
  formData?: FormData;
};

function isJsonBody(body: ApiRequestOptions["body"]): body is Record<string, unknown> | unknown[] {
  return (
    body !== null &&
    typeof body === "object" &&
    !(body instanceof Blob) &&
    !(body instanceof ArrayBuffer) &&
    !(body instanceof FormData) &&
    !(body instanceof URLSearchParams) &&
    !(body instanceof ReadableStream)
  );
}

function formatApiDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const location = "loc" in item && Array.isArray(item.loc) ? item.loc.join(".") : "";
          return location ? `${location}: ${String(item.msg)}` : String(item.msg);
        }
        return null;
      })
      .filter(Boolean);
    if (messages.length > 0) {
      return messages.join("; ");
    }
  }
  return fallback;
}

function canRefreshAfterUnauthorized(path: string): boolean {
  return !path.startsWith("/auth/login") && !path.startsWith("/auth/register") && !path.startsWith("/auth/refresh");
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
  retryOnUnauthorized = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  let body = options.body;
  if (options.formData) {
    body = options.formData;
  } else if (isJsonBody(body)) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  } else if (typeof body === "string") {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    body,
    credentials: "include",
  });

  if (response.status === 401 && retryOnUnauthorized && canRefreshAfterUnauthorized(path)) {
    try {
      await apiRequest<unknown>("/auth/refresh", { method: "POST" }, false);
      return await apiRequest<T>(path, options, false);
    } catch {
      // Keep the original 401 response as the visible error.
    }
  }

  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = (await response.json()) as { detail?: unknown };
      message = formatApiDetail(data.detail, message);
    } catch {
      // Response is not JSON.
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
