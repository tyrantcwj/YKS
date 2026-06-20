import base64
import binascii
import csv
import io
import tempfile
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote_plus

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Form, HTTPException, Request
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import repository
from app import settings_store
from app.chart import build_price_chart, build_trend_chart
from app.config import settings
from app.db import backup_database, get_db, init_db
from app.models import PricePoint
from app.pricing import (
    display_price,
    run_sync_all_blocking,
    sync_all_subscriptions,
    sync_subscription,
)
from app.tcgdex import search_cards
from app.tcgdex import LOCALE_LABELS
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
    "ebay": "eBay",
    "snkrdunk": "Snkrdunk",
    "jihuanshe": "集换社",
    "manual": "手动记录",
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

SEARCH_LOCALE_OPTIONS = [
    ("en", "英文"),
    ("ja", "日文"),
    ("zh-tw", "繁中"),
    ("zh-cn", "简中"),
]

SORT_OPTIONS = [
    ("updated_desc", "最近更新"),
    ("history_desc", "历史最高价：高→低"),
    ("history_asc", "历史最高价：低→高"),
    ("price_desc", "最新价格：高→低"),
    ("price_asc", "最新价格：低→高"),
    ("name_asc", "卡名：A→Z"),
    ("rarity_asc", "稀有度：低→高"),
    ("rarity_desc", "稀有度：高→低"),
]

POPULAR_QUERIES = [
    "皮卡丘",
    "喷火龙",
    "ミュウ",
    "リザードン",
    "Pikachu",
    "Charizard",
]


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


def locale_label(value: str | None) -> str:
    if not value:
        return LOCALE_LABELS.get(settings.tcgdex_locale, settings.tcgdex_locale)
    return LOCALE_LABELS.get(value, value)


def parse_optional_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def money_label(row) -> str:
    price = display_price(row)
    if price is None:
        return "暂无价格"
    currency = row["currency"] or ""
    return f"{currency} {price:.2f}".strip()


def market_links(subscription) -> list[dict[str, str]]:
    query = subscription["nickname"] or subscription["name"] or subscription["card_id"]
    encoded = quote_plus(f"{query} pokemon card")
    snkrdunk = quote_plus(query)
    return [
        {
            "label": "eBay 已售出",
            "url": f"https://www.ebay.com/sch/i.html?_nkw={encoded}&LH_Sold=1&LH_Complete=1",
        },
        {
            "label": "Snkrdunk",
            "url": f"https://snkrdunk.com/search/result?keyword={snkrdunk}",
        },
        {
            "label": "TCGplayer",
            "url": f"https://www.tcgplayer.com/search/pokemon/product?productLineName=pokemon&q={encoded}",
        },
        {
            "label": "Cardmarket",
            "url": f"https://www.cardmarket.com/en/Pokemon/Products/Search?searchString={encoded}",
        },
    ]


def _primary_stat(provider_stats, variant: str):
    if not provider_stats:
        return None
    for stat in provider_stats:
        if stat["variant"] == variant:
            return stat
    return provider_stats[0]


def _trend_windows(latest_prices, variant: str) -> dict | None:
    candidates = [row for row in latest_prices if row["provider"] == "cardmarket"]
    if not candidates:
        return None
    chosen = next((row for row in candidates if row["variant"] == variant), candidates[0])
    keys = chosen.keys()

    def _field(name: str):
        return chosen[name] if name in keys else None

    latest = display_price(chosen)
    avg30 = _field("avg30_price")
    change30 = None
    if latest is not None and avg30 not in (None, 0):
        change30 = ((latest - avg30) / avg30) * 100
    return {
        "currency": chosen["currency"],
        "variant": chosen["variant"],
        "latest": latest,
        "avg1": _field("avg1_price"),
        "avg7": _field("avg7_price"),
        "avg30": avg30,
        "trend": _field("trend_price"),
        "change30": change30,
    }


def _recent_trades(history, limit: int = 30) -> list[dict]:
    previous: dict[tuple, float] = {}
    built: list[dict] = []
    for row in reversed(history):
        price = display_price(row)
        key = (row["provider"], row["variant"], row["currency"])
        change = None
        if price is not None:
            base = previous.get(key)
            if base not in (None, 0):
                change = ((price - base) / base) * 100
            previous[key] = price
        built.append(
            {
                "snapshot_at": row["snapshot_at"],
                "provider": row["provider"],
                "variant": row["variant"],
                "currency": row["currency"],
                "price": price,
                "change": change,
            }
        )
    built.reverse()
    return built[:limit]


def build_detail_context(subscription, history, latest_prices, provider_stats) -> dict:
    variant = subscription["variant"]
    primary = _primary_stat(provider_stats, variant)
    windows = _trend_windows(latest_prices, variant)
    hero = {
        "price": primary["latest_price"] if primary else None,
        "currency": primary["currency"] if primary else "",
        "provider": primary["provider"] if primary else None,
        "variant": primary["variant"] if primary else variant,
        "change30": windows["change30"] if windows else None,
    }
    return {
        "hero": hero,
        "primary": primary,
        "windows": windows,
        "recent_trades": _recent_trades(history),
    }


def _row_price(row) -> float | None:
    return display_price(row)


def _row_historical_high(row) -> float | None:
    return row["historical_high"] if "historical_high" in row.keys() else None


def _sort_rows(rows, sort: str):
    if sort == "history_desc":
        return sorted(rows, key=lambda row: (_row_historical_high(row) is not None, _row_historical_high(row) or 0), reverse=True)
    if sort == "history_asc":
        return sorted(rows, key=lambda row: (_row_historical_high(row) is None, _row_historical_high(row) or 0))
    if sort == "price_desc":
        return sorted(rows, key=lambda row: (_row_price(row) is not None, _row_price(row) or 0), reverse=True)
    if sort == "price_asc":
        return sorted(rows, key=lambda row: (_row_price(row) is None, _row_price(row) or 0))
    if sort == "name_asc":
        return sorted(rows, key=lambda row: (row["nickname"] or row["name"] or row["card_id"]).lower())
    if sort == "rarity_asc":
        return sorted(rows, key=lambda row: (row["rarity"] or ""))
    if sort == "rarity_desc":
        return sorted(rows, key=lambda row: (row["rarity"] or ""), reverse=True)
    return rows


def _unique_options(rows, key: str) -> list[str]:
    values = {
        str(row[key]).strip()
        for row in rows
        if row[key] is not None and str(row[key]).strip()
    }
    return sorted(values)


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
async def dashboard(
    request: Request,
    q: str = "",
    sort: str = "updated_desc",
    rarity: str = "",
    series: str = "",
    code: str = "",
    show_name: str = "1",
    show_price: str = "1",
):
    search_results = await search_cards(q) if q.strip() else []
    with get_db() as db:
        all_subscriptions = repository.list_subscriptions(db)
        alerts = repository.list_alerts(db)
        market_summary = repository.market_summary(db)
        price_movements = repository.recent_price_movements(db)
        ranked_cards = repository.ranked_cards(db)
    rarity_options = _unique_options(all_subscriptions, "rarity")
    series_options = _unique_options(all_subscriptions, "set_name")
    code_options = _unique_options(all_subscriptions, "card_id")
    subscriptions = [
        row
        for row in all_subscriptions
        if (not rarity or row["rarity"] == rarity)
        and (not series or row["set_name"] == series)
        and (not code or code.lower() in row["card_id"].lower())
    ]
    subscriptions = _sort_rows(subscriptions, sort)
    sync_errors = [
        row
        for row in all_subscriptions
        if "last_sync_error" in row.keys() and (row["last_sync_error"] or "").strip()
    ]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "settings": settings,
            "subscriptions": subscriptions,
            "subscription_count": len(all_subscriptions),
            "sync_error_count": len(sync_errors),
            "alerts": alerts,
            "market_summary": market_summary,
            "price_movements": price_movements,
            "ranked_cards": ranked_cards,
            "query": q.strip(),
            "search_results": search_results,
            "sort": sort,
            "rarity": rarity,
            "series": series,
            "code": code,
            "show_name": show_name != "0",
            "show_price": show_price != "0",
            "sort_options": SORT_OPTIONS,
            "rarity_options": rarity_options,
            "series_options": series_options,
            "code_options": code_options,
            "popular_queries": POPULAR_QUERIES,
            "display_price": display_price,
            "variant_label": variant_label,
            "provider_label": provider_label,
            "rarity_label": rarity_label,
            "locale_label": locale_label,
            "search_locale_options": SEARCH_LOCALE_OPTIONS,
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


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: str = ""):
    fields = [
        {
            "key": key,
            "label": label,
            "kind": kind,
            "placeholder": placeholder,
            "value": settings_store.current_value(key),
        }
        for key, (label, kind, placeholder) in settings_store.EDITABLE_SETTINGS.items()
    ]
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings": settings,
            "fields": fields,
            "saved": saved == "1",
        },
    )


@app.post("/settings")
async def save_settings(request: Request):
    form = await request.form()
    values: dict[str, str] = {}
    for key, (_, kind, _) in settings_store.EDITABLE_SETTINGS.items():
        if kind == "bool":
            values[key] = "true" if form.get(key) else "false"
        else:
            values[key] = (form.get(key) or "").strip()
    settings_store.set_values(values)
    return flash_redirect("/settings?saved=1")


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
    tcgdex_locale: str = Form(""),
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
            tcgdex_locale=tcgdex_locale.strip() or settings.tcgdex_locale,
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


@app.post("/subscriptions/{subscription_id}/prices")
async def add_manual_price(
    subscription_id: int,
    provider: str = Form("manual"),
    currency: str = Form("JPY"),
    variant: str = Form("normal"),
    market_price: str = Form(...),
):
    price = parse_optional_float(market_price)
    if price is None:
        raise HTTPException(status_code=400, detail="Price is required")
    provider = provider.strip().lower() or "manual"
    currency = currency.strip().upper() or "JPY"
    variant = variant.strip() or "normal"
    with get_db() as db:
        subscription = repository.get_subscription(db, subscription_id)
        if subscription is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        repository.save_price_snapshot(
            db,
            subscription_id,
            subscription["card_id"],
            PricePoint(
                provider=provider,
                currency=currency,
                variant=variant,
                market_price=price,
            ),
        )
    return flash_redirect(f"/subscriptions/{subscription_id}")


@app.post("/subscriptions/{subscription_id}/psa")
async def set_psa_cert(subscription_id: int, cert_number: str = Form("")):
    cert_number = cert_number.strip()
    with get_db() as db:
        if repository.get_subscription(db, subscription_id) is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        repository.set_psa_cert_number(db, subscription_id, cert_number)
        if not cert_number:
            repository.delete_psa_cert(db, subscription_id)
    if cert_number:
        await sync_subscription(subscription_id)
    return flash_redirect(f"/subscriptions/{subscription_id}")


@app.post("/subscriptions/{subscription_id}/jhs")
async def set_jhs_card(subscription_id: int, jhs_card_id: str = Form("")):
    jhs_card_id = jhs_card_id.strip()
    with get_db() as db:
        if repository.get_subscription(db, subscription_id) is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        repository.set_jhs_card_id(db, subscription_id, jhs_card_id)
    if jhs_card_id:
        await sync_subscription(subscription_id)
    return flash_redirect(f"/subscriptions/{subscription_id}")


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
        latest_prices = repository.latest_prices_by_subscription(db, subscription_id)
        provider_stats = repository.provider_market_stats(db, subscription_id)
        psa_cert = repository.get_psa_cert(db, subscription_id)
    detail = build_detail_context(subscription, history, latest_prices, provider_stats)
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "settings": settings,
            "subscription": subscription,
            "history": history,
            "latest_prices": latest_prices,
            "provider_stats": provider_stats,
            "psa_cert": psa_cert,
            "jhs_enabled": settings.jhs_enabled,
            "market_links": market_links(subscription),
            "chart": build_price_chart(history, subscription["variant"]),
            "trend_chart": build_trend_chart(history),
            "hero": detail["hero"],
            "primary": detail["primary"],
            "windows": detail["windows"],
            "recent_trades": detail["recent_trades"],
            "display_price": display_price,
            "money_label": money_label,
            "variant_label": variant_label,
            "provider_label": provider_label,
            "rarity_label": rarity_label,
            "locale_label": locale_label,
        },
    )


@app.post("/sync")
async def sync_all():
    await sync_all_subscriptions()
    return flash_redirect("/")
