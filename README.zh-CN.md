# 宝可梦卡价格订阅系统

这是一个只给自己用的宝可梦卡价格订阅网站。系统默认部署在本地 Docker 里，数据保存在 Docker volume 中的 SQLite 数据库，价格数据来自 TCGdex 公开接口。

## 功能

- 按卡名搜索 TCGdex 卡片
- 直接用 TCGdex card ID 添加订阅，例如 `swsh3-136`
- 自动同步 TCGplayer 美元价格和 Cardmarket 欧元价格
- 支持 normal / reverse / holo / standard 等版本
- 保存价格历史快照
- 单卡详情页显示 SVG 价格走势图
- 设置目标价提醒
- 设置涨跌百分比提醒
- 站内提醒列表
- 可选 webhook 通知
- 可选 HTTP Basic Auth
- 默认只绑定本机 `127.0.0.1:8000`
- 导出订阅 CSV
- 导出价格历史 CSV
- 下载 SQLite 数据库备份
- Docker healthcheck
- Docker smoke test 脚本
- 在线源码更新：不需要重新构建或更新容器，也能直接把容器内代码更新到 GitHub main 分支

## 文件说明

- `docker-compose.yml`: 本地 Docker 编排文件
- `Dockerfile`: 应用镜像构建文件
- `.env.example`: 配置示例
- `app/`: FastAPI 应用
- `scripts/smoke-docker.ps1`: Docker 部署自检脚本
- `docker/yks-entrypoint.sh`: 容器内循环启动脚本，用于在线更新后自动重启服务
- `tests/`: 单元和路由测试

## 完整 Docker 编排文件

如果你想直接复制编排代码，可以使用下面这一份。保存为 `docker-compose.yml`：

```yaml
services:
  pokemon-price-watch:
    build: .
    container_name: pokemon-price-watch
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      APP_NAME: "Pokemon Price Watch"
      DATABASE_PATH: "/data/app.db"
      SYNC_INTERVAL_MINUTES: "360"
      TCGDEX_LOCALE: "en"
      AUTH_USERNAME: "${AUTH_USERNAME:-admin}"
      AUTH_PASSWORD: "${AUTH_PASSWORD:-}"
      ALERT_WEBHOOK_URL: "${ALERT_WEBHOOK_URL:-}"
      ALERT_WEBHOOK_TIMEOUT_SECONDS: "${ALERT_WEBHOOK_TIMEOUT_SECONDS:-10}"
      YKS_UPDATE_MODE: "${YKS_UPDATE_MODE:-auto}"
      YKS_UPDATE_REPO: "${YKS_UPDATE_REPO:-tyrantcwj/YKS}"
      YKS_UPDATE_BRANCH: "${YKS_UPDATE_BRANCH:-main}"
      YKS_GITHUB_MIRROR_PREFIX: "${YKS_GITHUB_MIRROR_PREFIX:-}"
    volumes:
      - pokemon-price-data:/data
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5).read()",
        ]
      interval: 1m
      timeout: 10s
      retries: 3
      start_period: 20s

volumes:
  pokemon-price-data:
```

这份编排默认只允许本机访问：

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

如果你以后要让局域网其他设备访问，可以改成：

```yaml
ports:
  - "8000:8000"
```

## 部署到本地 Docker

先复制配置：

```powershell
Copy-Item .env.example .env
```

启动：

```powershell
docker compose up --build -d
```

打开：

```text
http://localhost:8000
```

查看状态：

```powershell
docker compose ps
docker compose logs -f
```

停止：

```powershell
docker compose down
```

## 一键验收 Docker 部署

安装 Docker 后，在项目目录运行：

```powershell
.\scripts\smoke-docker.ps1
```

脚本会执行：

- `docker compose up --build -d`
- 等待 `/healthz` 返回正常
- 检查首页是否能打开
- 如果设置了 `AUTH_PASSWORD`，检查未登录返回 401，正确账号密码返回 200
- 默认测试完成后 `docker compose down`

如果希望测试后保持服务运行：

```powershell
.\scripts\smoke-docker.ps1 -KeepRunning
```

## 配置项

`.env.example` 示例：

```text
APP_NAME=Pokemon Price Watch
DATABASE_PATH=data/app.db
SYNC_INTERVAL_MINUTES=360
TCGDEX_LOCALE=en
AUTH_USERNAME=admin
AUTH_PASSWORD=
ALERT_WEBHOOK_URL=
ALERT_WEBHOOK_TIMEOUT_SECONDS=10
YKS_UPDATE_MODE=auto
YKS_UPDATE_REPO=tyrantcwj/YKS
YKS_UPDATE_BRANCH=main
YKS_GITHUB_MIRROR_PREFIX=
```

### 登录保护

默认 `AUTH_PASSWORD` 为空，不启用登录保护。

要启用登录，在 `.env` 中设置：

```text
AUTH_USERNAME=admin
AUTH_PASSWORD=your-private-password
```

### Webhook 通知

要把提醒推送到 ntfy、Bark、企业微信机器人或自建中转服务，可以设置：

```text
ALERT_WEBHOOK_URL=https://your-webhook-endpoint.example/notify
ALERT_WEBHOOK_TIMEOUT_SECONDS=10
```

发送的 JSON 格式：

```json
{
  "source": "Pokemon Price Watch",
  "alerts": [
    {
      "kind": "target",
      "message": "Furret reached target price: 4.00 <= 5.00",
      "card_id": "swsh3-136",
      "title": "Furret"
    }
  ]
}
```

## 在线更新代码

这个功能按 `iTyc-Rss` 的源码更新模式做：不需要重新构建镜像，也不需要 `docker compose pull` 或重建容器。

容器启动时运行的是：

```text
docker/yks-entrypoint.sh
```

它会循环启动 FastAPI 服务。当网页里触发在线更新时，应用会：

1. 检查 `YKS_UPDATE_REPO` 的 `YKS_UPDATE_BRANCH`
2. 下载 GitHub main 分支源码压缩包
3. 在容器内覆盖 `app/`、`scripts/`、`pyproject.toml`、README、Docker 编排等文件
4. 执行 `python -m pip install --no-cache-dir .`
5. 写入 `app-version.json`
6. 退出当前服务进程
7. `docker/yks-entrypoint.sh` 自动重新拉起服务

网页入口：

```text
http://localhost:8000/update
```

也可以直接访问 API：

```text
GET  /api/admin/update/status
POST /api/admin/update/apply
```

如果要禁用在线更新：

```text
YKS_UPDATE_MODE=disabled
```

如果 GitHub 直连慢，可以设置镜像前缀，例如：

```text
YKS_GITHUB_MIRROR_PREFIX=https://ghfast.top/
```

## 数据备份

网页 header 中有三个下载入口：

- `Database Backup`: 下载 SQLite 数据库快照
- `Subscriptions CSV`: 导出订阅配置
- `Prices CSV`: 导出价格历史

完整迁移推荐用 `Database Backup`。CSV 主要用于查看、分析或表格处理。

## 卡片 ID

TCGdex 卡片 URL 示例：

```text
https://api.tcgdex.net/v2/en/cards/swsh3-136
```

订阅时填写的 card ID 是：

```text
swsh3-136
```

也可以直接在首页搜索卡名，例如：

```text
pikachu
charizard
furret
```

## 本地开发

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 当前限制

- 当前默认数据源是 TCGdex。某些卡片可能没有价格字段。
- 价格提醒以同步时拿到的数据为准，不是实时推送。
- 本项目只按个人本地使用设计，不建议直接公开到公网。
