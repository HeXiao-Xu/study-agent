-- pgvector 扩展：必须在任何建表之前启用（S0-4 任务卡要求）
-- postgres 镜像只在数据卷“首次初始化”时执行本目录下的 SQL；
-- 若数据卷已存在而扩展缺失，需手动执行：
--   docker exec -it study-agent-postgres psql -U study -d study_agent -c "CREATE EXTENSION IF NOT EXISTS vector;"
CREATE EXTENSION IF NOT EXISTS vector;
