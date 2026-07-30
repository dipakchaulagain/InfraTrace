# Stage 1 — build
FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
# Use npm ci with lockfile (generated); --no-audit skips dev-only vulnerability noise
RUN if [ -f package-lock.json ]; then npm ci --no-audit; else npm install --no-audit; fi
COPY . .
RUN npm run build

# Stage 2 — serve with Nginx
FROM nginx:1.25-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
