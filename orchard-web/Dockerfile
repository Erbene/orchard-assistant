# Orchard Next.js frontend.
#
# FASTAPI_URL is needed at BUILD time (next build bakes next.config.ts's
# rewrites() destination into the routes manifest) AND at RUN time
# (app/api/chat/route.ts + app/api/v1/sources/route.ts read process.env per
# request). Same value in both places; compose can override the runtime one.
ARG FASTAPI_URL=http://backend:8000

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
ARG FASTAPI_URL
ENV FASTAPI_URL=$FASTAPI_URL
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN mkdir -p public
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ARG FASTAPI_URL
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    FASTAPI_URL=$FASTAPI_URL
COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./next.config.ts
EXPOSE 3000
CMD ["npm", "run", "start"]
