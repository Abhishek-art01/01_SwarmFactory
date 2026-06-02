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
