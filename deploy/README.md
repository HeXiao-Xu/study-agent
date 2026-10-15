# deploy/ — 开发环境基础服务（S0-4）

三件套：**PostgreSQL 16（pgvector/pgvector:pg16 镜像）**、**Redis 7**、**MinIO**。
所有密码从环境变量读取（默认值见根目录 `.env.example`，可复制为 `.env` 覆盖）。

## 前置要求

- Docker Desktop 已安装且引擎运行中（左下角 **Engine running**）

## 首次启动（在仓库根目录执行）

```bash
# 1.（可选）覆盖默认密码：复制模板并修改
#    Windows PowerShell: Copy-Item .env.example .env
cp .env.example .env

# 2. 启动三件套（首次会拉镜像，约 400–500MB，耐心等）
docker compose -f deploy/docker-compose.dev.yml up -d

# 3. 连通性自检（应输出 3/3 全部通过）
python scripts/check_services.py

# 4. pgvector 扩展验证（首启已由 initdb/01-extensions.sql 自动启用，此处复查）
docker exec -it study-agent-postgres psql -U study -d study_agent \
  -c "SELECT extname FROM pg_extension;"
# 输出应包含 vector
```

## 服务清单

| 服务 | 容器名 | 地址 | 说明 |
|---|---|---|---|
| PostgreSQL 16 | study-agent-postgres | `localhost:5432` | 库 `study_agent`，用户 `study`；扩展 `vector` 首启自动启用 |
| Redis 7 | study-agent-redis | `localhost:6379` | 无密码（仅本机回环可访问） |
| MinIO | study-agent-minio | `localhost:9000`（API）/ `localhost:9001`（控制台） | 控制台账号 `study` / `study123456`；bucket `study-agent` 由 minio-init 自动创建 |

## 常用命令

```bash
docker compose -f deploy/docker-compose.dev.yml ps        # 状态与健康检查
docker compose -f deploy/docker-compose.dev.yml logs -f   # 跟踪日志（加 postgres/redis/minio 只看单个）
docker compose -f deploy/docker-compose.dev.yml stop      # 停止（数据保留）
docker compose -f deploy/docker-compose.dev.yml down      # 删除容器（命名卷数据保留）
docker compose -f deploy/docker-compose.dev.yml down -v   # 连数据卷一起删（危险：清空所有数据）
```

## Windows 注意事项

- 端口都绑定了 `127.0.0.1`，只本机可访问，不会暴露到局域网；
- 端口被占用（5432/6379/9000/9001）时启动会报 `bind: address already in use`：用
  `netstat -ano | findstr 5432` 找到占用进程，或在 `.env` 里改 `POSTGRES_PORT` 等端口；
- 数据存放在命名卷 `study-agent-pgdata / study-agent-redisdata / study-agent-miniodata`，
  `down` 不会丢数据，`down -v` 才会；
- **pgvector 扩展必须在建表之前启用**：`initdb/01-extensions.sql` 已在数据卷首次初始化时
  自动执行；如果换了数据卷后扩展丢失，按文件内注释手动补建。

## 覆盖默认密码

compose 内置了开发默认值；要覆盖时把根目录 `.env` 显式传给 compose：

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml up -d
```

## 镜像加速（本机实测，2026-10）

Docker Hub 直连在本机约 110KB/s；DaoCloud 公共镜像已 502 失效。
**本机实测可用且极快的源：华为云 SWR 镜像**（60MB 约 5 秒）：

```bash
# 用法：给镜像名加前缀拉取，拉完重标记回原名
docker pull swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/<镜像名>
docker tag  swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/<镜像名> <镜像名>
```
