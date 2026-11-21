FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG NEXT_PUBLIC_API_URL=https://tinyworlds.us
ARG NEXT_PUBLIC_GAME_PLAY_URL=https://games.tinyworlds.us
ENV NEXT_PUBLIC_GAME_PLAY_URL=$NEXT_PUBLIC_GAME_PLAY_URL
ARG NEXT_PUBLIC_BUILD_SHA=dev
ENV NEXT_PUBLIC_BUILD_SHA=$NEXT_PUBLIC_BUILD_SHA
RUN mkdir -p public && pnpm build

FROM node:22-alpine
WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
