FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_BASE_URL=
ARG VITE_GATEWAY_MCP_URL=http://localhost:18082/mcp/mcp
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_GATEWAY_MCP_URL=$VITE_GATEWAY_MCP_URL
RUN npm run build

FROM nginx:1.28-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080



