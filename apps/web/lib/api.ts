export const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { credentials: "include", cache: "no-store", ...init });
  if (!response.ok) {
    let message = `요청 실패 (${response.status})`;
    try { const body = await response.json(); message = body.detail ?? message; } catch { /* retain status */ }
    throw new Error(message);
  }
  return response.status === 204 ? undefined as T : response.json();
}
