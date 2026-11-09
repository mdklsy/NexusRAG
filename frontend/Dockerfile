FROM node:20-alpine AS build
WORKDIR /app
ARG VITE_API_BASE=/api
COPY package.json pnpm-workspace.yaml ./
# 不带 lockfile：宿主机 lockfile 按镜像源（npmmirror）生成，与 pnpm 供应链的
# tarball URL 校验（恒按 npmjs 官方源比对）天然冲突；容器内直连 npmjs 全新解析。
# 同时关闭跑脚本前的依赖预检（无 lockfile 场景下该预检必然失败）：
ENV verifyDepsBeforeRun=false
RUN corepack enable && pnpm install
COPY . .
ENV VITE_API_BASE=$VITE_API_BASE
RUN pnpm build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
