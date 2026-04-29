// Shared axios instance for the SCION backend. All API modules import the
// default export and call `client.get(...)` / `client.post(...)` against it,
// so base URL and auth live in one place.
import axios from "axios";

// Fallback to localhost in dev. `NEXT_PUBLIC_*` vars are baked into the
// client bundle at build time by Next.js.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

// Inject the API key on every request. Kept as an interceptor (not set on
// `axios.create`) so we pick it up dynamically if env handling ever moves
// to runtime config, and so missing keys simply send no header rather
// than sending an empty one.
client.interceptors.request.use((config) => {
  const apiKey = process.env.NEXT_PUBLIC_API_KEY;
  if (apiKey) {
    config.headers["X-API-Key"] = apiKey;
  }
  return config;
});

// Response interceptor: turn auth errors into a single recognisable
// shape so callers don't each have to reverse-engineer the backend's
// FastAPI HTTPException(detail=...) format.
//
// 401 = backend has API_KEY set but the frontend didn't send X-API-Key
// (frontend's NEXT_PUBLIC_API_KEY is missing or wasn't built into the
// bundle). 403 = sent the wrong key. Both are config issues the user
// can act on, not transient errors — surface them clearly instead of
// "Network Error".
//
// Why we don't auto-redirect to a login page: SCION's auth is a
// shared-secret model, not user identity. There's no login flow.
client.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error?.response?.status === 401) {
      error.message =
        "API key required. Set NEXT_PUBLIC_API_KEY in frontend/.env.local " +
        "and rebuild, or unset API_KEY on the backend if you're in dev.";
    } else if (error?.response?.status === 403) {
      error.message =
        "API key rejected. The frontend sent X-API-Key but the backend " +
        "didn't accept it. Check that NEXT_PUBLIC_API_KEY matches API_KEY.";
    }
    return Promise.reject(error);
  },
);

export { API_BASE_URL };
export default client;
