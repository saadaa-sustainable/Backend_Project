"""Campaign analysis: Meta, last-click and first-click rows fold into one
campaign's totals, days and ad sets without mixing campaigns."""
from datetime import date

import pytest
from fastapi import HTTPException

from app.api.routers import analytics

D1, D2 = date(2026, 11, 1), date(2026, 11, 2)
ROWS = {
    "insights_daily_by_ad": [
        {"campaign_id": "1", "adset_id": "a", "day": D1, "spend": 100.0, "impressions": 1000.0,
         "clicks": 10.0, "purchases": 2.0, "conv_value": 300.0, "ncp": 1.0},
        {"campaign_id": "1", "adset_id": "b", "day": D2, "spend": 50.0, "impressions": 500.0,
         "clicks": 5.0, "purchases": 1.0, "conv_value": 100.0, "ncp": 0.0},
        {"campaign_id": "2", "adset_id": "c", "day": D1, "spend": 70.0, "impressions": 0.0,
         "clicks": 0.0, "purchases": 0.0, "conv_value": 0.0, "ncp": 0.0},
    ],
    "ga4_order_attribution": [
        {"campaign_id": "1", "adset_id": "a", "day": D2, "fc_orders": 2.0, "fc_revenue": 500.0},
    ],
    "shopify_order_attribution": [
        {"campaign_id": "1", "adset_id": "a", "day": D1, "lc_orders": 3.0, "lc_revenue": 900.0,
         "lc_new_orders": 1.0, "lc_new_revenue": 300.0},
        {"campaign_id": "1", "adset_id": None, "day": D2, "lc_orders": 1.0, "lc_revenue": 200.0,
         "lc_new_orders": 0.0, "lc_new_revenue": 0.0},
    ],
}


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self.rows


class _Session:
    async def execute(self, sql, params=None):
        q = str(sql)
        if "meta_campaigns" in q:
            return _Result([{"campaign_id": "1", "campaign_name": "One", "status": "ACTIVE"},
                            {"campaign_id": "2", "campaign_name": "Two", "status": "PAUSED"}])
        if "FROM public.meta_adsets" in q:
            return _Result([{"adset_id": "a", "adset_name": "A", "status": "ACTIVE"}])
        # The first-click query also names shopify_order_attribution, so GA4 is tried first.
        for table, rows in ROWS.items():
            if table in q:
                return _Result(rows)
        raise AssertionError(q)


async def test_rows_fold_into_totals_days_and_adsets():
    r = await analytics.get_campaign_analysis.__wrapped__(
        _Session(), campaign_ids="1,2", from_date=D1, to_date=D2)
    one, two = r.campaigns
    assert (one.campaign_name, two.campaign_name) == ("One", "Two")
    t = one.totals
    assert (t.spend, t.lc_orders, t.lc_revenue, t.fc_revenue, t.ncp) == (150, 4, 1100, 500, 1)
    assert [(d.day, d.spend, d.lc_revenue, d.fc_revenue) for d in one.daily] == [
        (D1, 100, 900, 0), (D2, 50, 200, 500)]
    # Largest spend first; the order tied to no ad set keeps its own row.
    assert [(s.adset_id, s.adset_name, s.spend, s.lc_revenue) for s in one.adsets] == [
        ("a", "A", 100, 900), ("b", None, 50, 0), (None, None, 0, 200)]
    assert two.totals.spend == 70 and two.totals.lc_revenue == 0


@pytest.mark.parametrize("ids", ["", "x", "1,2,3,4,5,6"])
async def test_bad_id_lists_are_refused(ids):
    with pytest.raises(HTTPException) as e:
        await analytics.get_campaign_analysis.__wrapped__(_Session(), campaign_ids=ids)
    assert e.value.status_code == 400
