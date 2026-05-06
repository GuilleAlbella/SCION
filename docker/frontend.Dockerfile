# SCION frontend container — Next.js standalone runtime.
#
# Three stages: deps install, build, runtime. The runtime image only
# carries the standalone server output + static assets, ~150 MB.

# ──── Stage 1: deps ────
FROM node:22-alpine AS deps

WORKDIR /app

# Install only what's needed to resolve dependencies. Cached unless
# package*.json change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund


# ──── Stage 2: build ────
FROM node:22-alpine AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./

# Build-time API URL — baked into the static bundle. nginx routes
# /api/* to the backend, so a same-origin path is the safe default.
ARG NEXT_PUBLIC_API_BASE_URL=/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

RUN npm run build


# ──── Stage 3: runtime ────
FROM node:22-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Standalone output (next.config.ts: output: "standalone") includes
# the minimal node_modules subset Next actually needs at runtime.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

# BusyBox wget on Alpine resolves `localhost` to ::1 first; the Next
# standalone server only binds to 0.0.0.0. Use the explicit IPv4 loopback.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
    CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1

CMD ["node", "server.js"]
