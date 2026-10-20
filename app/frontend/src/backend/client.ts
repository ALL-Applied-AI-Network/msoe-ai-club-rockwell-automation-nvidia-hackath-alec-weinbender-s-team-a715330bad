import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

// Typed against the backend's OpenAPI schema. schema.d.ts is generated: after a backend change, run `npm run gen:api`
// with the backend up, and the type checker shows every call that no longer matches. URLs are same-origin: the backend
// serves the built UI, and in dev Vite forwards /api to it.
export const api = createClient<paths>();

export type Schemas = components["schemas"];
