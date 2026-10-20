import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

// Typed against the backend's OpenAPI schema. schema.d.ts is generated: after a backend change, run `npm run gen:api`
// with the backend up, and the type checker shows every call that no longer matches. URLs are same-origin: the backend
// serves the built UI, and in dev Vite forwards /api to it.
export const api = createClient<paths>();

export type Schemas = components["schemas"];

/** A call's data, or an Error carrying the API's message (its "detail"). For TanStack Query's queryFn and mutationFn. */
export async function unwrap<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await call;
  if (error !== undefined || data === undefined) {
    throw new Error(detail(error) ?? `${response.status} ${response.statusText}`);
  }
  return data;
}

function detail(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("detail" in error)) return undefined;
  const value = (error as { detail: unknown }).detail;
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null && "message" in value) return String(value.message);
  return JSON.stringify(value);
}
