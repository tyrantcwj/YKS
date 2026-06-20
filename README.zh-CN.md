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
- 导出订阅 CSV
- 导出价格历史 CSV
- 下载 SQLite 数据库备份
- Docker healthcheck
- Docker smoke test 脚本
- 在线源码更新：不需要重新构建或更新容器，也能直接把容器内代码更新到 GitHub main 分支

## 文件说明

- `docker-compose.yml`: NAS / 本地 Docker 免构建编排文件
- `Dockerfile`: 本地手动构建镜像时使用
- `.env.example`: 配置示例
- `app/`: FastAPI 应用
- `scripts/smoke-docker.ps1`: Docker 部署自检脚本
- `docker/yks-entrypoint.sh`: 容器内循环启动脚本，用于在线更新后自动重启服务
- `tests/`: 单元和路由测试

## 完整 Docker 编排文件

下面这份是给群晖、威联通、1Panel、CasaOS、Docker Compose 项目等图形界面用的免构建版本。它不使用 `build: .`，所以不会要求面板上传源码构建上下文。

保存为 `docker-compose.yml`，或者直接粘贴到容器管理器的项目编排里：

```yaml
services:
  pokemon-price-watch:
    image: python:3.12-slim
    container_name: pokemon-price-watch
    restart: unless-stopped
    working_dir: /app/source
    ports:
      - "8000:8000"
    environment:
      APP_NAME: "宝可梦卡价格订阅"
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
      - pokemon-price-code:/app/source
    command:
      - /bin/sh
      - -lc
      - |
        set -eu
        mkdir -p /app/source /data
        cd /app/source
        while [ ! -f pyproject.toml ]; do
          find . -mindepth 1 -maxdepth 1 -exec rm -rf {} +
          if python - <<'PY'
        import os
        import shutil
        import tarfile
        import tempfile
        import urllib.request
        from pathlib import Path

        repo = os.environ.get("YKS_UPDATE_REPO", "tyrantcwj/YKS")
        branch = os.environ.get("YKS_UPDATE_BRANCH", "main")
        mirror = os.environ.get("YKS_GITHUB_MIRROR_PREFIX", "").strip().rstrip("/")
        url = f"https://codeload.github.com/{repo}/tar.gz/refs/heads/{branch}"
        urls = [url]
        if mirror:
            urls.insert(0, f"{mirror}/{url}")

        last_error = None
        with tempfile.TemporaryDirectory(prefix="yks-bootstrap-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "source.tar.gz"
            for candidate in urls:
                try:
                    request = urllib.request.Request(candidate, headers={"User-Agent": "YKS"})
                    with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
                        shutil.copyfileobj(response, output)
                    break
                except Exception as exc:
                    last_error = exc
            else:
                raise RuntimeError(f"Could not download source archive: {last_error}")

            extract_to = tmp_path / "extract"
            extract_to.mkdir()
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(extract_to, filter="data")
            roots = [path for path in extract_to.iterdir() if path.is_dir()]
            if not roots:
                raise RuntimeError("Source archive did not contain a root directory.")
            source_root = roots[0]
            destination = Path.cwd()
            for item in source_root.iterdir():
                target = destination / item.name
                if item.is_dir():
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
        PY
          then
            break
          fi
          echo "YKS bootstrap failed; retrying in 60 seconds..."
          sleep 60
        done
        until python -m pip install --no-cache-dir -e .; do
          echo "YKS dependency install failed; retrying in 60 seconds..."
          sleep 60
        done
        exec /bin/sh docker/yks-entrypoint.sh
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
      start_period: 1m

volumes:
  pokemon-price-data:
  pokemon-price-code:
```

这份编排第一次启动时会：

- 拉取 `python:3.12-slim`
- 用 Python 标准库从 GitHub 下载源码压缩包到 `pokemon-price-code` volume
- 安装 Python 依赖
- 启动网站

第一次启动会比普通镜像慢一点，后面重启会复用已经克隆好的代码 volume。

如果日志里还出现 `apt-get` 或 `git clone`，说明项目仍在使用旧编排。需要删除旧项目/容器后，用本节最新编排重新创建。

如果只想允许本机访问，可以把端口改成：

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

如果你在 NAS 上部署，通常保持默认的 `8000:8000` 更方便在局域网访问。

## 部署到本地 Docker

启动：

```powershell
docker compose up -d
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

如果你的 Docker 面板不支持 `${AUTH_USERNAME:-admin}` 这种默认值写法，就把环境变量改成固定值，例如：

```yaml
AUTH_USERNAME: "admin"
AUTH_PASSWORD: ""
YKS_UPDATE_MODE: "auto"
YKS_UPDATE_REPO: "tyrantcwj/YKS"
YKS_UPDATE_BRANCH: "main"
YKS_GITHUB_MIRROR_PREFIX: ""
```

## 一键验收 Docker 部署

安装 Docker 后，在项目目录运行：

```powershell
.\scripts\smoke-docker.ps1
```

脚本会执行：

- `docker compose up -d`
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
APP_NAME=宝可梦卡价格订阅
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

要启用登录，在 compose 环境变量里设置：

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
  "source": "宝可梦卡价格订阅",
  "alerts": [
    {
      "kind": "target",
      "message": "Furret 达到目标价：4.00 <= 5.00",
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

- `数据库备份`: 下载 SQLite 数据库快照
- `订阅导出`: 导出订阅配置
- `价格导出`: 导出价格历史

完整迁移推荐用 `数据库备份`。CSV 主要用于查看、分析或表格处理。

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
