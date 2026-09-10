# AutoQA frontend — the Next.js web app.
FROM node:20-bookworm-slim AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# The API address is baked in here, not read at run time.
#
# Next inlines every NEXT_PUBLIC_* value into the JavaScript it ships to the
# browser, so this has to be the address *the visitor's machine* can reach —
# https://autoqa.example.com/api/v1, not the container name and not localhost.
# Get it wrong and the deployed UI silently calls 127.0.0.1:8000 on whatever
# laptop opened it, and every request fails with "Failed to fetch".
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build


FROM node:20-bookworm-slim

ENV NODE_ENV=production
# `next start` reads PORT, so the port moves without editing package.json.
# Odd on purpose — see the ports block in docker-compose.prod.yml.
ENV PORT=29382
WORKDIR /app

# The whole tree rather than a standalone bundle, because next.config.ts does
# not set `output: "standalone"`. Costs image size and nothing else; turning it
# on is a change to the app's own configuration, not to its deployment.
COPY --from=build /app ./

EXPOSE 29382

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://localhost:29382').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["npm", "run", "start"]
