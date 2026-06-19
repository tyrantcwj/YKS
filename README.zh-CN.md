# 宝可梦卡价格订阅系统

这是一个只给自己用的宝可梦卡价格订阅网站。系统默认部署在本地 Docker 里，数据保存在 Docker volume 中的 SQLite 数据库，价格数据来自 TCGdex 公开接口。

## 已有功能

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

## 文件说明

- `docker-compose.yml`: 本地 Docker 编排文件
- `Dockerfile`: 应用镜像构建文件
- `.env.example`: 配置示例
- `app/`: FastAPI 应用
- `scripts/smoke-docker.ps1`: Docker 部署自检脚本
- `tests/`: 单元和路由测试

## 部署到本地 Docker

先复制配置：

```powershell
Copy-Item .env.example .env
```

如果只在本机访问，可以保持默认配置。默认端口映射是：

```yaml
ports:
  - "127.0.0.1:8000:8000"
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

`.env.example` 里已有完整示例：

```text
APP_NAME=Pokemon Price Watch
DATABASE_PATH=data/app.db
SYNC_INTERVAL_MINUTES=360
TCGDEX_LOCALE=en
AUTH_USERNAME=admin
AUTH_PASSWORD=
ALERT_WEBHOOK_URL=
ALERT_WEBHOOK_TIMEOUT_SECONDS=10
```

Docker Compose 中实际使用：

```yaml
environment:
  APP_NAME: "Pokemon Price Watch"
  DATABASE_PATH: "/data/app.db"
  SYNC_INTERVAL_MINUTES: "360"
  TCGDEX_LOCALE: "en"
  AUTH_USERNAME: "${AUTH_USERNAME:-admin}"
  AUTH_PASSWORD: "${AUTH_PASSWORD:-}"
  ALERT_WEBHOOK_URL: "${ALERT_WEBHOOK_URL:-}"
  ALERT_WEBHOOK_TIMEOUT_SECONDS: "${ALERT_WEBHOOK_TIMEOUT_SECONDS:-10}"
volumes:
  - pokemon-price-data:/data
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
