from dataclasses import dataclass


@dataclass(frozen=True)
class PricePoint:
    provider: str
    currency: str
    variant: str
    market_price: float | None = None
    low_price: float | None = None
    mid_price: float | None = None
    high_price: float | None = None
    direct_price: float | None = None
    trend_price: float | None = None
    avg1_price: float | None = None
    avg7_price: float | None = None
    avg30_price: float | None = None

    @property
    def display_price(self) -> float | None:
        return self.market_price or self.trend_price or self.mid_price or self.low_price


@dataclass(frozen=True)
class CardPayload:
    card_id: str
    name: str
    image_url: str | None
    set_name: str | None
    rarity: str | None
    raw_json: str
    prices: list[PricePoint]


@dataclass(frozen=True)
class CardSearchResult:
    card_id: str
    name: str
    image_url: str | None
    tcgdex_locale: str
    local_id: str | None = None
