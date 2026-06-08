# GameOps Center

Production hardening is documented in `docs/production-operations.md`. It covers managed MySQL backups/slow-query logging/pool monitoring, Alembic and Flyway migrations, SSO/OIDC, approval and rollback governance, trusted-runtime dry-run controls, least-privilege Kubernetes RBAC, and Prometheus/Grafana/Alertmanager ownership of long-term metrics and alert routing.

GameOps Center 是一个面向游戏区服的自动化运维项目。它把区服抽象成 Kubernetes `Deployment / Pod / Service`，用 CMDB 记录资产关系，用 MySQL 持久化告警、日志、发布记录、用户会话和指标历史，并提供 Prometheus `/metrics`、Docker/Kubernetes 运维动作、登录与 RBAC、通知渠道、CI/CD、IaC、配置管理和 AI 辅助诊断报告。

## 核心能力

- CMDB：记录战区、Deployment、Service、镜像、容量、副本数和负责人。
- 真实指标：采集宿主机 CPU、内存、磁盘；可通过 Docker CLI 或 kubectl 补充容器/Pod 指标。
- Prometheus：暴露 `/metrics`，包含宿主机、工作负载、告警和发布计数。
- Docker：重启动作映射为 `docker restart`，发布动作映射为镜像 pull/run 版本切换。
- Kubernetes：重启动作为 `kubectl rollout restart`，发布为 `kubectl set image` + `rollout status`，扩缩容为 `kubectl scale deployment`。
- 数据库：MySQL 8 持久化告警、日志、发布记录、用户会话、CMDB 和指标历史。
- 登录与 RBAC：管理员、发布负责人、只读观察员三类角色。
- 通知渠道：支持 Webhook、企业微信、钉钉、邮件，未配置时会记录为跳过。
- AI 运维：支持 OpenAI 兼容接口生成故障诊断、操作日志和运维报告；无密钥时使用本地规则兜底。
- CI/CD：GitHub Actions 自动启动 MySQL、运行测试、构建镜像，并提供服务器部署模板。
- IaC/配置管理：提供 Terraform Docker + MySQL 资源示例和 Ansible 部署 playbook。

## 快速运行

推荐用 Docker Compose 一次性启动 MySQL 和应用：

```powershell
cd E:\program_file\Shell_project\gameops-center
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

打开：

```text
http://127.0.0.1:8018
```

如果要直接用 Python 运行，需要先准备 MySQL 并安装依赖：

```powershell
pip install -r requirements.txt
$env:GAMEOPS_MYSQL_HOST="127.0.0.1"
$env:GAMEOPS_MYSQL_PORT="3306"
$env:GAMEOPS_MYSQL_DATABASE="gameops"
$env:GAMEOPS_MYSQL_USER="gameops"
$env:GAMEOPS_MYSQL_PASSWORD="gameops-pass"
python app.py
```

默认演示账号：

| 账号 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `admin123` | 管理员 |
| `release` | `release123` | 发布负责人 |
| `viewer` | `viewer123` | 只读观察员 |

生产环境请更换默认账号，或把认证接入 SSO/OIDC。

## MySQL 配置

环境变量：

```powershell
$env:GAMEOPS_MYSQL_HOST="127.0.0.1"
$env:GAMEOPS_MYSQL_PORT="3306"
$env:GAMEOPS_MYSQL_DATABASE="gameops"
$env:GAMEOPS_MYSQL_USER="gameops"
$env:GAMEOPS_MYSQL_PASSWORD="gameops-pass"
```

应用首次启动会自动建表并导入种子 CMDB 数据。若数据库已存在但为空，会自动写入默认战区、工作负载和演示账号。

## 运行测试

普通单元测试不要求本机有 MySQL：

```powershell
python -m unittest discover -s tests
```

MySQL 集成测试需要安装依赖并设置 `GAMEOPS_TEST_MYSQL=1`，CI 已经自动启用：

```powershell
pip install -r requirements.txt
$env:GAMEOPS_TEST_MYSQL="1"
$env:GAMEOPS_MYSQL_HOST="127.0.0.1"
$env:GAMEOPS_MYSQL_PORT="3306"
$env:GAMEOPS_MYSQL_USER="gameops"
$env:GAMEOPS_MYSQL_PASSWORD="gameops-pass"
$env:GAMEOPS_MYSQL_ROOT_PASSWORD="root-pass"
python -m unittest tests.test_mysql_store
```

## Prometheus

直接访问：

```text
http://127.0.0.1:8018/metrics
```

Prometheus 配置示例见：

```text
deploy/prometheus/prometheus.yml
```

核心指标示例：

- `gameops_host_cpu_percent`
- `gameops_host_memory_percent`
- `gameops_workload_cpu_percent`
- `gameops_workload_latency_p95_ms`
- `gameops_workload_replicas`
- `gameops_alerts_active`
- `gameops_deployments_total`

## Prometheus / Grafana / Alertmanager

Docker Compose 会同时启动长期监控、仪表盘和告警路由：

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| GameOps Center | `http://127.0.0.1:8018` | 运维控制台与 `/metrics` |
| Prometheus | `http://127.0.0.1:9090` | 抓取指标、保留时序数据、执行告警规则 |
| Grafana | `http://127.0.0.1:3000` | 默认账号 `admin/admin`，自动加载 GameOps Overview 仪表盘 |
| Alertmanager | `http://127.0.0.1:9093` | 告警分组、抑制、重复发送和 Webhook 路由 |

Prometheus 配置位于 `deploy/prometheus/prometheus.yml`，告警规则位于 `deploy/prometheus/rules/gameops-alerts.yml`。默认保留 15 天指标数据，可通过环境变量调整：

```powershell
$env:GAMEOPS_PROMETHEUS_RETENTION="30d"
```

Alertmanager 配置位于 `deploy/alertmanager/alertmanager.yml`。它会把 firing/resolved 告警发送到 `gameops-center` 的 `/api/alertmanager`，由 GameOps 写入 MySQL 日志并复用 `GAMEOPS_WEBHOOK_URL`、`GAMEOPS_WECOM_WEBHOOK`、`GAMEOPS_DINGTALK_WEBHOOK`、`GAMEOPS_SMTP_*` 等通知渠道继续分发。

Grafana provisioning 位于 `deploy/grafana/provisioning`，仪表盘 JSON 位于 `deploy/grafana/dashboards/gameops-overview.json`。首次启动后无需手动创建数据源或导入仪表盘。

## Docker 部署

```powershell
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

Compose 会启动：

- `gameops-mysql`：MySQL 8，数据卷 `gameops-mysql-data`
- `gameops-center`：运维平台，连接 `mysql:3306`
- `gameops-prometheus`：长期指标、告警规则和 Alertmanager 对接
- `gameops-grafana`：自动装载 Prometheus 数据源和 GameOps Overview 仪表盘
- `gameops-alertmanager`：告警分组、抑制、重复通知和路由

容器 MySQL 默认映射到宿主机 `3307`，避免和本机 MySQL 的 `3306` 冲突。需要改宿主机端口时设置：

```powershell
$env:GAMEOPS_MYSQL_PUBLISHED_PORT="3308"
```

默认 `GAMEOPS_DRY_RUN=true`，不会真正执行危险操作。接入真实 Docker/Kubernetes 时设置：

```powershell
$env:GAMEOPS_DRY_RUN="false"
$env:GAMEOPS_RUNTIME="kubernetes"
```

可选运行模式：

- `GAMEOPS_RUNTIME=auto`
- `GAMEOPS_RUNTIME=docker`
- `GAMEOPS_RUNTIME=kubernetes`

## Kubernetes 部署

```powershell
kubectl apply -f deploy/kubernetes/gameops-center.yaml
kubectl apply -f deploy/kubernetes/sample-game-workloads.yaml
```

`gameops-center.yaml` 包含：

- Namespace
- MySQL Secret、PVC、Deployment、Service
- GameOps ConfigMap、ServiceAccount、ClusterRole、ClusterRoleBinding
- GameOps Deployment、Service、ServiceMonitor

`sample-game-workloads.yaml` 展示一个真实区服工作负载：`arena-east` Deployment、Service 和 HPA。

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/login` | 登录并获取 Bearer Token |
| `GET` | `/api/overview` | 总览、战区、趋势、宿主机指标 |
| `GET` | `/api/cmdb` | CMDB 资产与关系 |
| `GET` | `/api/workloads` | 工作负载列表 |
| `GET` | `/api/alerts` | 活跃告警 |
| `GET` | `/api/logs` | 操作和系统日志 |
| `GET` | `/api/deployments` | 发布记录 |
| `POST` | `/api/deploy` | 镜像版本切换 |
| `POST` | `/api/workloads/{id}/restart` | 容器/Deployment 重启 |
| `POST` | `/api/workloads/{id}/scale` | Deployment 扩缩容 |
| `POST` | `/api/traffic` | 战区流量权重调整 |
| `POST` | `/api/notify/alerts` | 推送告警汇总 |
| `GET` | `/api/ai/diagnosis` | AI 故障诊断 |
| `GET` | `/api/ai/report` | AI 运维报告 |
| `GET` | `/metrics` | Prometheus 指标 |

## 通知配置

```powershell
$env:GAMEOPS_WEBHOOK_URL="https://example.com/webhook"
$env:GAMEOPS_WECOM_WEBHOOK="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
$env:GAMEOPS_DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=..."
$env:GAMEOPS_SMTP_HOST="smtp.example.com"
$env:GAMEOPS_SMTP_PORT="587"
$env:GAMEOPS_SMTP_USER="ops@example.com"
$env:GAMEOPS_SMTP_PASSWORD="..."
$env:GAMEOPS_MAIL_FROM="ops@example.com"
$env:GAMEOPS_MAIL_TO="sre@example.com,release@example.com"
```

## AI 大模型配置

```powershell
$env:GAMEOPS_LLM_API_KEY="sk-..."
$env:GAMEOPS_LLM_API_BASE="https://api.openai.com/v1"
$env:GAMEOPS_LLM_MODEL="gpt-4.1-mini"
$env:GAMEOPS_LLM_USER_AGENT="GameOps-Center/1.0"
```

没有密钥也可以运行，系统会用内置规则生成诊断和报告。

## IaC 与配置管理

Terraform 示例会创建 Docker 网络、MySQL 容器和 GameOps 容器：

```powershell
cd infrastructure/terraform
terraform init
terraform apply
```

Ansible 示例：

```powershell
ansible-playbook -i ops/ansible/inventory.ini ops/ansible/deploy-gameops.yml
```

## CI/CD

GitHub Actions 工作流在：

```text
.github/workflows/ci-cd.yml
```

流程：

1. 提交代码。
2. 自动启动 MySQL 8 服务。
3. 安装 `requirements.txt`。
4. 自动运行 `python -m unittest discover -s tests`，包含 MySQL 集成测试。
5. Push 到主分支后构建 Docker 镜像。
6. 设置 `ENABLE_GAMEOPS_DEPLOY=true` 和服务器 Secrets 后，通过 SSH 部署到服务器。

## 项目结构

```text
gameops-center/
  app.py
  requirements.txt
  gameops/
    adapters.py
    ai_ops.py
    collectors.py
    data.py
    engine.py
    notifications.py
    store.py
  web/
    index.html
    styles.css
    app.js
  deploy/
    docker/docker-compose.yml
    kubernetes/*.yaml
    alertmanager/alertmanager.yml
    grafana/dashboards/*.json
    grafana/provisioning/**/*.yml
    prometheus/prometheus.yml
    prometheus/rules/*.yml
  infrastructure/terraform/main.tf
  ops/ansible/*.yml
  tests/
    test_engine.py
    test_mysql_store.py
  .github/workflows/ci-cd.yml
```

## 生产落地建议

- 使用托管 MySQL 或高可用 MySQL，并配合备份、慢查询和连接池监控。
- 引入正式 migration 工具，例如 Alembic 或 Flyway。
- 把演示账号替换为 SSO/OIDC，并启用更细粒度的审批流。
- 将 `GAMEOPS_DRY_RUN=false` 仅用于可信环境，并为 kubectl ServiceAccount 设置最小权限。
- 给发布动作增加人工审批、回滚记录和变更窗口校验。
- 让 Prometheus/Grafana/Alertmanager 接管长期指标、仪表盘和告警路由。
