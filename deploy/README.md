# 部署说明（101 服务器实测形态）

## 拓扑

```
浏览器 ──▶ :8380 jqeval-frontend (nginx 静态 + /api 反代)
                    │ compose 网络 jqeval-network（external，与中间件同网）
                    ▼
             jqeval-backend (uvicorn:8000，仅网络内暴露)
             jqeval-worker  (celery，同一镜像)
                    │
                    ▼
     jqeval-postgres / jqeval-redis / jqeval-minio / jqeval-milvus
     （docker-compose.yml 管理的既有中间件容器，本文件不碰）
```

## 步骤（服务器上）

```bash
cd /opt/jq-eval
# 可选：生产密钥
cp deploy/.env.example deploy/.env  # 替换两个密钥

docker compose -f deploy/docker-compose.app.yml up -d --build
docker compose -f deploy/docker-compose.app.yml ps
curl -s http://127.0.0.1:8380/api/v1/health
```

访问 `http://<服务器IP>:8380`（云安全组需放行 8380）。

## 关键决策记录

- **网络**：加入既有 `jqeval-network`（external），中间件容器名直连，
  不重新编排中间件、不碰数据卷
- **端口**：宿主 8000 已有其他 uvicorn、3000 被 new-api 占用 → 前端网关用 8380；
  后端只 `expose` 不发布端口，外网唯一入口是前端 nginx
- **worker**：`--concurrency=2 --max-tasks-per-child=50`，服务器可用内存约 2G，
  不按默认 nproc 拉满
- **磁盘**：构建前清理过旧版镜像与 build cache；前端多阶段构建，
  node_modules 只存在于 builder 层，最终镜像约 60MB
- **数据库共享**：容器后端与本机开发后端连的是同一个 Postgres（数据同源），
  启动同步（内置指标/内置基准）全部幂等，重复执行无副作用
