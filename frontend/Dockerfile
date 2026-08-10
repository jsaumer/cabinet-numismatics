# Build the static frontend, then serve it from nginx.
# This image IS the compose `proxy` service; nginx.conf is mounted by compose.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.31-alpine
COPY --from=build /src/dist /usr/share/nginx/html
