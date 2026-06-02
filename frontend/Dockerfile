# Frontend Dockerfile for Swarm Factory
# Multi-stage build: build with Node, serve static files with nginx

# Build stage
FROM node:20-alpine AS builder
WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --silent

# Copy sources and build
COPY . ./
ARG VITE_API_KEY=swarm-factory-dev-key
ARG VITE_API_BASE_URL=
ARG VITE_API_URL=
ARG VITE_WS_BASE_URL=
ARG VITE_WS_URL=
ENV VITE_API_KEY=$VITE_API_KEY
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_WS_BASE_URL=$VITE_WS_BASE_URL
ENV VITE_WS_URL=$VITE_WS_URL
RUN npm run build

# Production stage
FROM nginx:stable-alpine AS production

# Remove default nginx content and copy built files
RUN rm -rf /usr/share/nginx/html/*
COPY --from=builder /app/dist/ /usr/share/nginx/html/

# Copy nginx template to enable envsubst of VITE_API_KEY into conf
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template

# Expose port 80 and run nginx
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
