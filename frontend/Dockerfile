# Build the static frontend, then serve it from nginx.
# This image IS the compose `proxy` service. Build context is the repo root
# (not frontend/) so this can also COPY proxy/nginx.conf in, baked into the
# image rather than bind-mounted — a bind-mounted host path can't be relied
# on to exist across every node in a Swarm/multi-host deployment.
FROM node:26-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/. .
RUN npm run build

FROM nginx:1.31-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY proxy/nginx.conf /etc/nginx/conf.d/default.conf
