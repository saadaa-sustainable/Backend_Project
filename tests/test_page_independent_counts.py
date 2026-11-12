"""Totals are counted once per filter set, not once per page."""

from app.api.routers import analytics


class _Result(list):
    def scalar_one(self):
        return 7


class _Session:
    def __init__(self):
        self.sql = []

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))
        return _Result()


async def test_customer_journey_load_more_does_not_recount():
    session = _Session()
    for offset in (0, 50, 100):
        page = await analytics.get_customer_journey(
            session=session, search="count-once", offset=offset)
        assert page.total == 7
    counts = [s for s in session.sql if "COUNT(*)" in s]
    assert len(counts) == 2, "one total and one group count for three pages"
    assert len(session.sql) == 5


async def test_customer_journey_new_filter_recounts():
    session = _Session()
    await analytics.get_customer_journey(session=session, search="first")
    await analytics.get_customer_journey(session=session, search="second")
    assert len([s for s in session.sql if "COUNT(*)" in s]) == 4
