from app.pricing import display_price


class Row(dict):
    def __getitem__(self, key):
        return self.get(key)


def test_display_price_prefers_market_price():
    row = Row(market_price=3.5, trend_price=3.0, mid_price=2.5, low_price=2.0)

    assert display_price(row) == 3.5


def test_display_price_falls_back_to_trend_then_mid_then_low():
    row = Row(market_price=None, trend_price=None, mid_price=2.5, low_price=2.0)

    assert display_price(row) == 2.5
