# 前端镜像：node 构建 dist → nginx:alpine 托管 + /api 反代后端容器
# 多阶段构建：builder 层（node_modules ~400MB）不会进最终镜像
FROM node:20-alpine AS build
WORKDIR /app

# 先装依赖再拷源码：锁文件不变时命中层缓存
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
