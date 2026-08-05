# Multi-stage: build the React app, then serve it with nginx (which also proxies
# API + WebSocket to the twin core, so the browser sees a single origin).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Templated config: the image's entrypoint runs envsubst on /etc/nginx/templates/
# *.template at startup. Restrict substitution to CELLTWIN_* so nginx's own
# $host/$uri/$http_upgrade are preserved, and default the key to empty (auth off)
# so ${CELLTWIN_API_KEY} always resolves even when it isn't set.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER=CELLTWIN_
ENV CELLTWIN_API_KEY=""
EXPOSE 80
