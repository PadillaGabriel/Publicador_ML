export const BASE =
  import.meta.env.VITE_API_URL || "http://localhost:8000";

function apiErrorMessage(body: any, status: number): string {
  const detail = body?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const location = Array.isArray(item?.loc)
          ? item.loc
              .filter((part: unknown) => part !== "query")
              .join(".")
          : "";

        const message =
          typeof item?.msg === "string"
            ? item.msg
            : "Solicitud inválida";

        return location ? `${location}: ${message}` : message;
      })
      .join(" · ");
  }

  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string") {
      return detail.message;
    }

    return JSON.stringify(detail);
  }

  if (typeof body?.message === "string") {
    return body.message;
  }

  return `HTTP ${status}`;
}

async function parseErrorResponse(response: Response): Promise<string> {
  const body = await response
    .json()
    .catch(() => ({
      detail: response.statusText || `HTTP ${response.status}`,
    }));

  return apiErrorMessage(body, response.status);
}

export async function api<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      ...(options?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(options?.headers || {}),
    },
  });

  if (!response.ok) {
    const message = await parseErrorResponse(response);
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export function jobEvents(jobId: string): EventSource {
  return new EventSource(
    `${BASE}/api/jobs/${encodeURIComponent(jobId)}/events`
  );
}

export async function downloadFile(
  path: string,
  fallbackName: string
): Promise<void> {
  const response = await fetch(`${BASE}${path}`);

  if (!response.ok) {
    const message = await parseErrorResponse(response);
    throw new Error(message);
  }

  const blob = await response.blob();

  const disposition =
    response.headers.get("Content-Disposition") || "";

  const match =
    disposition.match(/filename\*=UTF-8''([^;]+)/i) ||
    disposition.match(/filename="?([^";]+)"?/i);

  const name = match?.[1]
    ? decodeURIComponent(match[1])
    : fallbackName;

  const url = URL.createObjectURL(blob);

  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;

    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}