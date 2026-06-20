import base64
import binascii
import csv
import io
import tempfile
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Form, HTTPException, Request
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import repository
from app.chart import build_price_chart
from app.config import settings
from app.db import backup_database, get_db, init_db
from app.pricing import (
    display_price,
    run_sync_all_blocking,
    sync_all_subscriptions,
    sync_subscription,
)
from app.tcgdex import search_cards
from app.updater import apply_update, read_build_info, update_status

scheduler = BackgroundScheduler()
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

VARIANT_LABELS = {
    "holo": "闪卡",
    "normal": "普通",
    "reverse": "反闪",
    "standard": "标准",
}

PROVIDER_LABELS = {
    "tcgplayer": "TCGplayer",
    "cardmarket": "Cardmarket",
}

RARITY_LABELS = {
    "common": "普通",
    "uncommon": "非普通",
    "rare": "稀有",
    "rare holo": "闪稀有",
    "rare holo vmax": "闪稀有 VMAX",
    "rare holo v": "闪稀有 V",
    "rare ultra": "超稀有",
    "rare secret": "秘密稀有",
    "promo": "宣传卡",
}

UPDATE_MODE_LABELS = {
    "source": "源码更新",
    "disabled": "已禁用",
}


def variant_label(value: str | None) -> str:
    if not value:
        return "未选择"
    return VARIANT_LABELS.get(value, value)


def provider_label(value: str | None) -> str:
    if not value:
        return "待同步"
    return PROVIDER_LABELS.get(value, value)


def rarity_label(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    return RARITY_LABELS.get(normalized, value)


def update_mode_label(value: str | None) -> str:
    if not value:
        return "未知"
    return UPDATE_MODE_LABELS.get(value, value)


def parse_optional_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def flash_redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def csv_response(filename: str, rows) -> StreamingResponse:
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(dict(row) for row in rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(
        run_sync_all_blocking,
        "interval",
        minutes=settings.sync_interval_minutes,
        id="sync_all_subscriptions",
        replace_existing=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _unauthorized() -> Response:
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="YKS"'},
    )


def _valid_basic_auth(header: str | None) -> bool:
    if settings.auth_password.strip() == "":
        return True
    if header is None or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.removeprefix("Basic ").strip()).decode()
        username, password = decoded.split(":", 1)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    return secrets.compare_digest(username, settings.auth_username) and secrets.compare_digest(
        password,
        settings.auth_password,
    )


@app.middleware("http")
async def require_basic_auth(request: Request, call_next):
    if request.url.path == "/healthz" or _valid_basic_auth(request.headers.get("authorization")):
        return await call_next(request)
    return _unauthorized()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, q: str = ""):
    search_results = await search_cards(q) if q.strip() else []
    with get_db() as db:
        subscriptions = repository.list_subscriptions(db)
        alerts = repository.list_alerts(db)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "settings": settings,
            "subscriptions": subscriptions,
            "alerts": alerts,
            "query": q.strip(),
            "search_results": search_results,
            "display_price": display_price,
            "variant_label": variant_label,
            "provider_label": provider_label,
            "rarity_label": rarity_label,
        },
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/api/version")
async def api_version():
    info = read_build_info()
    return {
        "version": info.version,
        "commit": info.commit,
        "builtAt": info.built_at,
    }


@app.get("/api/admin/update/status")
async def api_update_status():
    return await update_status()


@app.post("/api/admin/update/apply")
async def api_update_apply():
    return await apply_update()


@app.get("/update", response_class=HTMLResponse)
async def update_page(request: Request):
    try:
        status = await update_status()
        error = ""
    except Exception as exc:
        status = None
        error = str(exc)
    return templates.TemplateResponse(
        request,
        "update.html",
        {
            "settings": settings,
            "status": status,
            "error": error,
            "message": "",
            "update_mode_label": update_mode_label,
        },
    )


@app.post("/update/apply", response_class=HTMLResponse)
async def update_apply_page(request: Request):
    try:
        result = await apply_update()
        status = await update_status()
        error = ""
        message = result.get("detail", "Update started.")
    except Exception as exc:
        status = None
        error = str(exc)
        message = ""
    return templates.TemplateResponse(
        request,
        "update.html",
        {
            "settings": settings,
            "status": status,
            "error": error,
            "message": message,
            "update_mode_label": update_mode_label,
        },
    )


@app.get("/export/subscriptions.csv")
async def export_subscriptions_csv():
    with get_db() as db:
        rows = repository.export_subscriptions(db)
    return csv_response("subscriptions.csv", rows)


@app.get("/export/prices.csv")
async def export_prices_csv():
    with get_db() as db:
        rows = repository.export_price_snapshots(db)
    return csv_response("price-snapshots.csv", rows)


@app.get("/export/database.sqlite")
async def export_database_sqlite():
    handle = tempfile.NamedTemporaryFile(
        prefix="pokemon-price-watch-",
        suffix=".sqlite",
        delete=False,
    )
    backup_path = Path(handle.name)
    handle.close()
    backup_database(backup_path)
    return FileResponse(
        backup_path,
        media_type="application/vnd.sqlite3",
        filename="pokemon-price-watch.sqlite",
        background=BackgroundTask(lambda: backup_path.unlink(missing_ok=True)),
    )


@app.post("/subscriptions")
async def add_subscription(
    card_id: str = Form(...),
    nickname: str = Form(""),
    variant: str = Form("holo"),
    target_price: str = Form(""),
    alert_percent: str = Form(""),
):
    card_id = card_id.strip()
    if not card_id:
        raise HTTPException(status_code=400, detail="Card ID is required")

    with get_db() as db:
        subscription_id = repository.create_subscription(
            db,
            card_id=card_id,
            nickname=nickname.strip(),
            variant=variant,
            target_price=parse_optional_float(target_price),
            alert_percent=parse_optional_float(alert_percent),
        )

    await sync_subscription(subscription_id)
    return flash_redirect("/")


@app.post("/subscriptions/{subscription_id}/edit")
async def edit_subscription(
    subscription_id: int,
    nickname: str = Form(""),
    variant: str = Form("holo"),
    target_price: str = Form(""),
    alert_percent: str = Form(""),
    active: str | None = Form(None),
):
    with get_db() as db:
        if repository.get_subscription(db, subscription_id) is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        repository.update_subscription(
            db,
            subscription_id,
            nickname.strip(),
            variant,
            parse_optional_float(target_price),
            parse_optional_float(alert_percent),
            active == "on",
        )
    return flash_redirect("/")


@app.post("/subscriptions/{subscription_id}/sync")
async def sync_one(subscription_id: int):
    await sync_subscription(subscription_id)
    return flash_redirect("/")


@app.post("/subscriptions/{subscription_id}/delete")
async def delete_one(subscription_id: int):
    with get_db() as db:
        repository.delete_subscription(db, subscription_id)
    return flash_redirect("/")


@app.get("/subscriptions/{subscription_id}", response_class=HTMLResponse)
async def subscription_detail(request: Request, subscription_id: int):
    with get_db() as db:
        subscription = repository.get_subscription(db, subscription_id)
        if subscription is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        history = repository.recent_prices(db, subscription_id, limit=80)
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "settings": settings,
            "subscription": subscription,
            "history": history,
            "chart": build_price_chart(history, subscription["variant"]),
            "display_price": display_price,
            "variant_label": variant_label,
            "provider_label": provider_label,
            "rarity_label": rarity_label,
        },
    )


@app.post("/sync")
async def sync_all():
    await sync_all_subscriptions()
    return flash_redirect("/")
