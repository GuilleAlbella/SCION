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

export { API_BASE_URL };
export default client;
