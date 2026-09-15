FROM node:20-alpine AS builder
ARG NEXT_PUBLIC_API_URL
ARG API_PROXY_TARGET=http://127.0.0.1:8000
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} API_PROXY_TARGET=${API_PROXY_TARGET} npm run build

FROM node:20-alpine
WORKDIR /app

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
COPY --from=builder /app/public ./public

EXPOSE 3000

ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

CMD ["npm", "start"]