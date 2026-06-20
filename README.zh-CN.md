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

- `docker-compose.yml`: 拉取 GHCR 预构建镜像直接运行（下载就能用，推荐）
- `docker-compose.build.yml`: 本地源码构建用的编排文件
- `Dockerfile`: 构建镜像用，依赖在构建时安装
- `.github/workflows/docker-image.yml`: 自动构建并推送镜像到 GHCR 的 CI
- `.env.example`: 配置示例
- `app/`: FastAPI 应用
- `scripts/smoke-docker.ps1`: Docker 部署自检脚本
- `docker/yks-entrypoint.sh`: 容器内循环启动脚本，用于在线更新后自动重启服务
- `tests/`: 单元和路由测试

## 部署方式一：下载预构建镜像直接用（推荐，和 iTyc-Rss 一样）

和 iTyc-Rss 一样：GitHub Actions 会把镜像构建好推到 GitHub Container Registry（GHCR），你**直接拉镜像就能跑，不需要本地构建，也不会在启动时下载依赖**。

镜像地址：

```text
ghcr.io/tyrantcwj/yks:latest
```

> 第一次需要等 GitHub Actions 跑完一次（push 到 main 后约 3–5 分钟），并确保该 package 已设为 Public。之后就能匿名拉取。

最简单的做法（不需要克隆源码）：

```bash
curl -fsSLO https://raw.githubusercontent.com/tyrantcwj/YKS/main/docker-compose.yml
docker compose up -d
```

打开 `http://<主机IP>:8000` 即可。仓库里的 `docker-compose.yml` 就是这份（核心就是 `image:` 指向 GHCR，没有 `build:`）：

```yaml
services:
  yks:
    image: ghcr.io/tyrantcwj/yks:latest
    container_name: yks
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      APP_NAME: "宝可梦卡价格订阅"
      DATABASE_PATH: "/data/app.db"
      TCGDEX_LOCALE: "en"
      TCGDEX_API_BASE: "${TCGDEX_API_BASE:-https://api.tcgdex.net/v2}"
      AUTH_USERNAME: "${AUTH_USERNAME:-admin}"
      AUTH_PASSWORD: "${AUTH_PASSWORD:-}"
    volumes:
      - yks-data:/data

volumes:
  yks-data:
```

群晖 / 威联通 / 1Panel / CasaOS 等图形界面：新建容器时**镜像填 `ghcr.io/tyrantcwj/yks:latest`**，端口 `8000`，挂载一个卷到 `/data`，即可。镜像支持 `linux/amd64` 和 `linux/arm64`。

要升级到最新镜像：

```bash
docker compose pull && docker compose up -d
```

## 部署方式二：爱快 / 群晖等面板的编排（命名卷被禁用时）

有些面板（如爱快 4.0）**禁止使用命名卷（named volume）**，只允许主机路径挂载，而且挂载路径必须落在项目目录内。这时把 `image` 仍然指向 GHCR 镜像，只改 `volumes` 用**相对路径**即可。

### 爱快 4.0 编排代码

先在爱快里建好项目目录（例如 `/data/Docker/yks`），然后用下面这份编排（注意 `volumes` 用相对路径 `./data`，并且**没有**顶级 `volumes:` 声明）：

```yaml
services:
  yks:
    image: ghcr.io/tyrantcwj/yks:latest
    container_name: yks
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      APP_NAME: "宝可梦卡价格订阅"
      DATABASE_PATH: "/data/app.db"
      TCGDEX_LOCALE: "en"
      TCGDEX_API_BASE: "https://api.tcgdex.net/v2"
      AUTH_USERNAME: "admin"
      AUTH_PASSWORD: ""
      YKS_UPDATE_MODE: "auto"
      YKS_UPDATE_REPO: "tyrantcwj/YKS"
      YKS_UPDATE_BRANCH: "main"
    volumes:
      - ./data:/data
```

要点：

- `volumes` 左边用相对路径 `./data`（会落到项目目录里，例如 `/data/Docker/yks/data`）；右边必须保持 `/data`，因为 `DATABASE_PATH=/data/app.db`。
- 全文不要出现命名卷 `yks-data`，也不要再有顶级 `volumes:` 块，否则会报 `NAMED_VOLUME_FORBIDDEN`。
- 用绝对路径（如 `/iKuai/...`）会报 `OUTSIDE_BASE_DIR`，所以这里用相对路径。

### 群晖（Container Manager）

群晖支持命名卷，可直接用方式一那份。若想改成主机路径挂载，把 `volumes` 换成共享文件夹下的路径即可：

```yaml
    volumes:
      - /volume1/docker/yks/data:/data
```

> 如果你不想用 GHCR、想本地源码构建，仓库里还有 `docker-compose.build.yml`，执行 `docker compose -f docker-compose.build.yml up -d --build` 即可。

## 部署方式三：免构建 bootstrap（最后的备选）

仅当上面两种都不可用（面板既不能填镜像、也不能 build）时再用这份。它用 `python:3.12-slim` 基础镜像，第一次启动会下载源码并安装依赖（所以慢、镜像名显示成 `python`）。**能用方式一/二就别用这份。**

把下面内容存成 `docker-compose.yml`，或粘贴到容器管理器的项目编排里：

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

第一次启动会比普通镜像慢一点，后面重启会复用已经克隆好的代码 volume。这也是为什么这种方式镜像名会显示成 `python`、并且首次启动会“下载一大堆环境”。要避免这点，请改用上面的方式一。

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
TCGDEX_API_BASE=https://api.tcgdex.net/v2
POKEMONTCG_API_KEY=
PSA_API_TOKEN=
JHS_ENABLED=false
JHS_API_BASE=
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

### 在网页「设置」页直接改（推荐）

顶栏点「设置」（`/settings`）即可在网页里直接填写 **PSA Token、pokemontcg.io Key、TCGdex API 地址、集换社开关/地址、提醒 Webhook** 等。保存后写入数据库、**立即生效、无需重启容器**，也不必改 compose。这些值会覆盖环境变量；输入框留空则回退到环境变量/默认值。下面这些环境变量仍然可用，只是“设置”页更方便。

### 卡图回退（缺图时）

部分卡片（促销卡、麦当劳系列、部分日文/中文卡）在 TCGdex 上**根本没有图**，这时列表/详情会显示文字占位。系统会自动回退到 [pokemontcg.io](https://pokemontcg.io) 按卡名+编号找图并缓存，无需配置即可工作；填上免费的 `POKEMONTCG_API_KEY`（或在“设置”页填）会更稳定、更不容易超额。

### PSA 评级（评级 + 族群，无价格）

PSA 官方免费 API 只支持**按证书号查单张**，返回评级分数与族群数量（不含价格）。到 [psacard.com/publicapi](https://www.psacard.com/publicapi) 注册拿到 token 后填入 `PSA_API_TOKEN`，再在某张卡的详情页填入 PSA 证书号即可。详情页会显示评级、同级/更高分族群，首页卡片会出现 `PSA xx` 角标。

### 集换社 / 中国行情（实验性）

集换社没有公开 API、App 有加密与反爬，**自动抓取多半拿不到数据**，所以默认关闭（`JHS_ENABLED=false`）。可靠做法是在卡片详情页用“手动记录”按**人民币(CNY)**录入集换价，会和其它来源一起入库展示。若你确实有一个能返回价格 JSON 的中转地址，可设 `JHS_ENABLED=true` 与 `JHS_API_BASE`，并在详情页填集换社卡片 ID 尝试自动抓取（失败会静默跳过，不影响其它同步）。

## 网页没有数据怎么办

如果订阅了卡片但页面一直显示“暂无价格”，多半是 **Docker 主机访问不了 `api.tcgdex.net`**（局域网/被墙/代理问题）。现在系统会把同步失败的原因直接显示在首页顶部横幅和对应卡片上，照着排查即可：

1. 先在主机上测试连通性：能打开 `https://api.tcgdex.net/v2/en/cards/swsh3-136` 才能同步到价格。
2. 如果直连不通，在 compose 里把 `TCGDEX_API_BASE` 指向一个可用的反代/镜像（保持 `/v2` 结尾），例如自建的反向代理：

```yaml
TCGDEX_API_BASE: "https://your-proxy.example/tcgdex/v2"
```

3. 改完 `docker compose up -d` 重启，再点卡片上的“立即同步”。

另外，TCGdex 的价格主要覆盖 `normal` / `reverse`（TCGplayer）和 `standard` / `holo`（Cardmarket）。即使你订阅时选的版本和数据对不上，页面也会自动回退显示该卡任意可用版本的价格，不会再出现“明明有价格却显示暂无”的情况。

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
