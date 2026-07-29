export function requestPath(input: unknown): string {
  const url =
    input instanceof Request ? new URL(input.url) : new URL(String(input), "http://localhost");
  return `${url.pathname}${url.search}`;
}

export function requestMethod(input: unknown, init?: RequestInit): string {
  return input instanceof Request ? input.method : (init?.method ?? "GET");
}

export function requestHeaders(input: unknown, init?: RequestInit): Headers {
  return input instanceof Request ? input.headers : new Headers(init?.headers);
}

export async function requestJson<T>(input: unknown, init?: RequestInit): Promise<T> {
  const text =
    input instanceof Request
      ? await input.clone().text()
      : typeof init?.body === "string"
        ? init.body
        : "";
  if (!text) throw new Error("Expected a JSON request body.");
  return JSON.parse(text) as T;
}
