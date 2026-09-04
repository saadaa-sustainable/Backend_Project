"""Silver-layer flatten step for Shopify -- orders/customers/sessions, one
target table per object type, mirroring app/services/silver/
insights_flatten.py's shape (two-stage latest-per-entity query: find the
winning (source_id, extracted_at) pair via cheap indexed columns first,
THEN join back for the full payload -- see that module's docstring for why
a plain `DISTINCT ON ... ORDER BY extracted_at DESC` alone gets expensive
once the Bronze table grows).

Column names are hand-picked per table (not derived from a shared field
registry the way Meta's Insights flatten is) -- Shopify's GraphQL response
shapes for orders/customers are small and stable enough that a generic
system would be more machinery than the problem needs.

sessions is a special case: see scripts/ingest_shopify.py's module
docstring for why it's DAY x CHANNEL AGGREGATES (day, referrer_source,
utm_source, utm_campaign, utm_medium), not individual visits -- there's no
natural per-row entity id, so ingest_shopify.py generates a synthetic
`source_id` (a hash of those GROUP BY dimensions) that this module treats
as the primary key, same as any other object type.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

# Supports the two-stage query below the same way insights_flatten.py's
# partial index supports Meta's -- filter by object_type, order by
# (source_id, extracted_at) without a full sort of raw_dump_shopify.
_BRONZE_SHOPIFY_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_shopify_object_type_source_extracted "
    "ON raw_dump_shopify (object_type, source_id, extracted_at DESC)"
)

#: customAttributes is a `[{key, value}]` array (checkout-captured, from
#: this store's GoKwik checkout accelerator), NOT the same field as
#: customerJourneySummary -- confirmed live (2026-08-26) it carries real
#: UTM data for 64% of orders in a real sample, vs ~5% for
#: customerJourneySummary alone (which Shopify leaves null far more often
#: than "no attribution data exists" would suggest). This is now the
#: PRIMARY utm_* source; customer_journey stays as a raw jsonb column for
#: reference/fallback, not removed. See scripts/ingest_shopify.py's module
#: docstring "REAL BUG FOUND AND FIXED" note for the full story.
def _custom_attr(key: str) -> str:
    return (
        "(SELECT elem ->> 'value' FROM jsonb_array_elements("
        f"COALESCE(a.raw_payload -> 'customAttributes', '[]'::jsonb)) elem WHERE elem ->> 'key' = '{key}' LIMIT 1)"
    )


_ORDERS_DDL = """
CREATE TABLE IF NOT EXISTS shopify_orders (
    order_id text PRIMARY KEY,
    name text,
    email text,
    financial_status text,
    fulfillment_status text,
    subtotal_price numeric,
    total_price numeric,
    currency text,
    customer_id text,
    customer_email text,
    line_items jsonb,
    customer_journey jsonb,
    custom_attributes jsonb,
    utm_source text,
    utm_medium text,
    utm_campaign text,
    utm_content text,
    utm_term text,
    created_at timestamptz,
    updated_at timestamptz,
    processed_at timestamptz,
    extracted_at timestamptz,
    flattened_at timestamptz
)
"""

# shopify_orders predates custom_attributes/utm_* -- ALTER, not just
# CREATE IF NOT EXISTS, same migration idiom used elsewhere in this module.
_ORDERS_COLUMN_MIGRATIONS = [
    "ALTER TABLE IF EXISTS shopify_orders ADD COLUMN IF NOT EXISTS custom_attributes jsonb",
    "ALTER TABLE IF EXISTS shopify_orders ADD COLUMN IF NOT EXISTS utm_source text",
    "ALTER TABLE IF EXISTS shopify_orders ADD COLUMN IF NOT EXISTS utm_medium text",
    "ALTER TABLE IF EXISTS shopify_orders ADD COLUMN IF NOT EXISTS utm_campaign text",
    "ALTER TABLE IF EXISTS shopify_orders ADD COLUMN IF NOT EXISTS utm_content text",
    "ALTER TABLE IF EXISTS shopify_orders ADD COLUMN IF NOT EXISTS utm_term text",
]

_ORDERS_INSERT = f"""
WITH latest AS (
    -- DISTINCT ON, not MAX()+self-join: the old form joined back
    -- on (source_id, extracted_at), so two bronze rows sharing
    -- BOTH emitted BOTH -- a duplicate-key failure against this
    -- table's primary key. That tie is reachable: extracted_at is
    -- one datetime.now() per write batch, so every row in a batch
    -- carries the identical timestamp. DISTINCT ON picks exactly
    -- one row per source_id and cannot tie; id breaks any
    -- remaining ordering ambiguity deterministically.
    SELECT DISTINCT ON (source_id) source_id, id
    FROM raw_dump_shopify
    WHERE object_type = 'orders' AND source_id IS NOT NULL
    ORDER BY source_id, extracted_at DESC, id DESC
)
INSERT INTO shopify_orders (
    order_id, name, email, financial_status, fulfillment_status, subtotal_price, total_price,
    currency, customer_id, customer_email, line_items, customer_journey, custom_attributes,
    utm_source, utm_medium, utm_campaign, utm_content, utm_term,
    created_at, updated_at, processed_at, extracted_at, flattened_at
)
SELECT
    a.source_id AS order_id,
    a.raw_payload ->> 'name' AS name,
    a.raw_payload ->> 'email' AS email,
    a.raw_payload ->> 'displayFinancialStatus' AS financial_status,
    a.raw_payload ->> 'displayFulfillmentStatus' AS fulfillment_status,
    NULLIF(a.raw_payload -> 'subtotalPriceSet' -> 'shopMoney' ->> 'amount', '')::numeric AS subtotal_price,
    NULLIF(a.raw_payload -> 'totalPriceSet' -> 'shopMoney' ->> 'amount', '')::numeric AS total_price,
    a.raw_payload -> 'totalPriceSet' -> 'shopMoney' ->> 'currencyCode' AS currency,
    a.raw_payload -> 'customer' ->> 'id' AS customer_id,
    a.raw_payload -> 'customer' ->> 'email' AS customer_email,
    a.raw_payload -> 'lineItems' AS line_items,
    a.raw_payload -> 'customerJourneySummary' AS customer_journey,
    a.raw_payload -> 'customAttributes' AS custom_attributes,
    {_custom_attr('utm_source')} AS utm_source,
    {_custom_attr('utm_medium')} AS utm_medium,
    {_custom_attr('utm_campaign')} AS utm_campaign,
    {_custom_attr('utm_content')} AS utm_content,
    {_custom_attr('utm_term')} AS utm_term,
    NULLIF(a.raw_payload ->> 'createdAt', '')::timestamptz AS created_at,
    NULLIF(a.raw_payload ->> 'updatedAt', '')::timestamptz AS updated_at,
    NULLIF(a.raw_payload ->> 'processedAt', '')::timestamptz AS processed_at,
    a.extracted_at,
    now() AS flattened_at
FROM raw_dump_shopify a
JOIN latest ON latest.id = a.id
WHERE a.object_type = 'orders'
"""

_CUSTOMERS_DDL = """
CREATE TABLE IF NOT EXISTS shopify_customers (
    customer_id text PRIMARY KEY,
    first_name text,
    last_name text,
    email text,
    phone text,
    verified_email boolean,
    state text,
    number_of_orders numeric,
    amount_spent numeric,
    currency text,
    tax_exempt boolean,
    tags jsonb,
    created_at timestamptz,
    updated_at timestamptz,
    extracted_at timestamptz,
    flattened_at timestamptz
)
"""

_CUSTOMERS_INSERT = """
WITH latest AS (
    -- DISTINCT ON, not MAX()+self-join: the old form joined back
    -- on (source_id, extracted_at), so two bronze rows sharing
    -- BOTH emitted BOTH -- a duplicate-key failure against this
    -- table's primary key. That tie is reachable: extracted_at is
    -- one datetime.now() per write batch, so every row in a batch
    -- carries the identical timestamp. DISTINCT ON picks exactly
    -- one row per source_id and cannot tie; id breaks any
    -- remaining ordering ambiguity deterministically.
    SELECT DISTINCT ON (source_id) source_id, id
    FROM raw_dump_shopify
    WHERE object_type = 'customers' AND source_id IS NOT NULL
    ORDER BY source_id, extracted_at DESC, id DESC
)
INSERT INTO shopify_customers (
    customer_id, first_name, last_name, email, phone, verified_email, state, number_of_orders,
    amount_spent, currency, tax_exempt, tags, created_at, updated_at, extracted_at, flattened_at
)
SELECT
    a.source_id AS customer_id,
    a.raw_payload ->> 'firstName' AS first_name,
    a.raw_payload ->> 'lastName' AS last_name,
    a.raw_payload -> 'defaultEmailAddress' ->> 'emailAddress' AS email,
    a.raw_payload -> 'defaultPhoneNumber' ->> 'phoneNumber' AS phone,
    (a.raw_payload ->> 'verifiedEmail')::boolean AS verified_email,
    a.raw_payload ->> 'state' AS state,
    NULLIF(a.raw_payload ->> 'numberOfOrders', '')::numeric AS number_of_orders,
    NULLIF(a.raw_payload -> 'amountSpent' ->> 'amount', '')::numeric AS amount_spent,
    a.raw_payload -> 'amountSpent' ->> 'currencyCode' AS currency,
    (a.raw_payload ->> 'taxExempt')::boolean AS tax_exempt,
    a.raw_payload -> 'tags' AS tags,
    NULLIF(a.raw_payload ->> 'createdAt', '')::timestamptz AS created_at,
    NULLIF(a.raw_payload ->> 'updatedAt', '')::timestamptz AS updated_at,
    a.extracted_at,
    now() AS flattened_at
FROM raw_dump_shopify a
JOIN latest ON latest.id = a.id
WHERE a.object_type = 'customers'
"""

#: Matches scripts/ingest_shopify.py's SESSIONS_METRICS -- the full
#: documented metric set for ShopifyQL's `sessions` table (shopify.dev/
#: docs/api/shopifyql/2026-10/schemas/sessions_and_behavior/sessions,
#: fetched 2026-08-26), all confirmed live. Kept as a literal list here too
#: rather than imported (app/ never imports from scripts/, same boundary
#: rule as everywhere else in this project) -- if that list changes, this
#: one needs updating by hand.
_SESSIONS_METRIC_COLUMNS = [
    "sessions", "pageviews", "conversion_rate", "bounce_rate", "bounces",
    "average_session_duration", "pageviews_per_session", "online_store_visitors",
    "added_to_cart_rate", "sessions_with_cart_additions", "reached_checkout_rate",
    "sessions_that_reached_checkout", "checkout_conversion_rate", "completed_checkout_rate",
    "sessions_that_completed_checkout", "sessions_that_reached_and_completed_checkout",
]
#: Matches scripts/ingest_shopify.py's SESSIONS_GROUP_BY tail -- added
#: 2026-08-26 for per-page breakdown ("session per page, like
#: /men-cotton-pant"). This is the page a session LANDED on, not a full
#: per-pageview log (ShopifyQL's sessions table is session-level).
_SESSIONS_TEXT_DIM_COLUMNS = ["landing_page_path", "landing_page_type"]

_SESSIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS shopify_sessions (\n"
    "    session_key text PRIMARY KEY,\n"
    "    day date,\n"
    "    referrer_source text,\n"
    "    utm_source text,\n"
    "    utm_campaign text,\n"
    "    utm_medium text,\n"
    + "".join(f"    {c} text,\n" for c in _SESSIONS_TEXT_DIM_COLUMNS)
    + "".join(f"    {c} numeric,\n" for c in _SESSIONS_METRIC_COLUMNS)
    + "    extracted_at timestamptz,\n"
    "    flattened_at timestamptz\n"
    ")"
)

#: Explicit target column list, not a bare `INSERT INTO shopify_sessions
#: SELECT ...` -- a positional insert breaks the moment the table's
#: physical column order drifts from this SELECT's order, which it did:
#: shopify_sessions already existed with the original 4 metrics before
#: SESSIONS_METRICS grew to 16, so the 12 new ones landed via `ALTER TABLE
#: ADD COLUMN` at the END of the table (after extracted_at/flattened_at),
#: not where the DDL string above places them. Confirmed live -- a bare
#: positional INSERT here failed with "column extracted_at is of type
#: timestamptz but expression is of type numeric".
_SESSIONS_INSERT_COLUMNS = (
    ["session_key", "day", "referrer_source", "utm_source", "utm_campaign", "utm_medium"]
    + _SESSIONS_TEXT_DIM_COLUMNS
    + _SESSIONS_METRIC_COLUMNS
    + ["extracted_at", "flattened_at"]
)

_SESSIONS_INSERT = (
    "WITH latest AS (\n"
    "    -- DISTINCT ON, not MAX()+self-join -- see the orders\n"
    "    -- flatten for why: a (source_id, extracted_at) tie made\n"
    "    -- the old form emit BOTH rows, breaking this table's PK.\n"
    "    SELECT DISTINCT ON (source_id) source_id, id\n"
    "    FROM raw_dump_shopify\n"
    "    WHERE object_type = 'sessions' AND source_id IS NOT NULL\n"
    "    ORDER BY source_id, extracted_at DESC, id DESC\n"
    ")\n"
    f"INSERT INTO shopify_sessions ({', '.join(_SESSIONS_INSERT_COLUMNS)})\n"
    "SELECT\n"
    "    a.source_id AS session_key,\n"
    "    NULLIF(a.raw_payload ->> 'day', '')::date AS day,\n"
    "    a.raw_payload ->> 'referrer_source' AS referrer_source,\n"
    "    a.raw_payload ->> 'utm_source' AS utm_source,\n"
    "    a.raw_payload ->> 'utm_campaign' AS utm_campaign,\n"
    "    a.raw_payload ->> 'utm_medium' AS utm_medium,\n"
    + "".join(f"    a.raw_payload ->> '{c}' AS {c},\n" for c in _SESSIONS_TEXT_DIM_COLUMNS)
    + "".join(f"    NULLIF(a.raw_payload ->> '{c}', '')::numeric AS {c},\n" for c in _SESSIONS_METRIC_COLUMNS)
    + "    a.extracted_at,\n"
    "    now() AS flattened_at\n"
    "FROM raw_dump_shopify a\n"
    "JOIN latest ON latest.id = a.id\n"
    "WHERE a.object_type = 'sessions'"
)

#: ShopifyQL `fulfillments` table -- shopify.dev/docs/api/shopifyql/2026-10/
#: schemas/orders/fulfillments (fetched 2026-08-26, every field re-verified
#: live 2026-08-26 -- user explicitly asked for every metric in the doc,
#: not a curated sample; see scripts/ingest_shopify.py's
#: FULFILLMENTS_GROUP_BY docstring for exactly what's excluded and why: 6
#: "Attribution Syntax Required" fields, 5 array-typed fields, one
#: redundant id). One row per fulfillment event (fulfillment_id is a real
#: natural key -- unlike sessions, no synthetic hash needed, see
#: ingest_shopify.py's _build_rows). Gives this project real fulfillment/
#: shipping/delivery/referrer/risk/sales-channel visibility it had zero of
#: before -- was NOT built for UTM attribution (its own order_utm_*
#: dimensions were checked live and rejected for that: only ~4.8%
#: coverage, worse than customerJourneySummary).
#:
#: Column lists mirror scripts/ingest_shopify.py's FULFILLMENTS_GROUP_BY/
#: FULFILLMENTS_METRICS/FULFILLMENTS_BOOLEAN_COLUMNS/
#: FULFILLMENTS_TIMESTAMP_COLUMNS -- kept in sync by hand (app/ never
#: imports from scripts/, same boundary rule as everywhere else in this
#: project), split by SQL type here since the DDL/casts need that grouping.
_FULFILLMENTS_BOOLEAN_COLUMNS = [
    "is_b2b_order", "is_canceled_order", "order_includes_duties", "is_shop_referral_order",
    "order_is_shopify_protect_covered", "order_is_shopify_protect_eligible",
    "order_is_shopify_protect_protected",
]
_FULFILLMENTS_TIMESTAMP_COLUMNS = ["hour", "minute", "month", "quarter", "second", "week", "year"]
_FULFILLMENTS_TEXT_DIM_COLUMNS = [
    "order_id", "order_name", "order_fulfillment_status", "order_payment_status",
    "shipping_carrier", "fulfillment_provider", "shipping_city", "shipping_region", "shipping_country",
    "fulfillment_origin_country", "fulfillment_provider_id", "inventory_location_id",
    "inventory_location_name", "shop_id", "shop_name", "order_checkout_currency",
    "order_sales_channel", "order_sales_channel_id", "order_landing_page_path",
    "order_landing_page_url", "order_referrer_domain", "order_referrer_name",
    "order_referrer_source", "order_referrer_url", "order_utm_source", "order_utm_campaign",
    "order_utm_medium", "order_utm_content", "order_utm_term", "company_id", "company_name",
    "referring_channel", "referring_medium", "referring_platform", "traffic_type", "market",
    "order_cancellation_reason", "order_risk_level", "shipping_company", "shipping_postal_code",
    "hour_of_day", "month_of_year", "week_of_year", "shipping_address_id", "inventory_group_id",
    "order_marketing_event_target", "order_marketing_event_type",
]
_FULFILLMENTS_NUMERIC_DIM_COLUMNS = [
    "number_of_products_bought_together",
    "fulfillment_event_days", "fulfillment_event_hours",
    "fulfillment_to_shipping_days", "fulfillment_to_shipping_hours",
    "order_to_delivery_days", "order_to_delivery_hours",
    "order_to_fulfillment_days", "order_to_fulfillment_hours",
    "order_to_shipping_days", "order_to_shipping_hours",
    "shipping_to_delivery_days", "shipping_to_delivery_hours",
]
_FULFILLMENTS_METRIC_COLUMNS = [
    "orders_fulfilled", "orders_shipped", "orders_delivered",
    "orders_with_tracking_included_rate",
    "median_days_order_to_fulfillment", "median_days_order_to_shipping",
    "median_days_order_to_delivery", "median_days_fulfillment_to_shipping",
    "median_days_shipping_to_delivery",
    "median_hours_order_to_fulfillment", "median_hours_order_to_shipping",
    "median_hours_order_to_delivery", "median_hours_fulfillment_to_shipping",
    "median_hours_shipping_to_delivery",
]

_FULFILLMENTS_DDL = (
    "CREATE TABLE IF NOT EXISTS shopify_fulfillments (\n"
    "    fulfillment_id text PRIMARY KEY,\n"
    "    day date,\n"
    + "".join(f"    {c} text,\n" for c in _FULFILLMENTS_TEXT_DIM_COLUMNS)
    + "".join(f"    {c} boolean,\n" for c in _FULFILLMENTS_BOOLEAN_COLUMNS)
    + "".join(f"    {c} timestamptz,\n" for c in _FULFILLMENTS_TIMESTAMP_COLUMNS)
    + "".join(f"    {c} numeric,\n" for c in _FULFILLMENTS_NUMERIC_DIM_COLUMNS)
    + "".join(f"    {c} numeric,\n" for c in _FULFILLMENTS_METRIC_COLUMNS)
    + "    extracted_at timestamptz,\n"
    "    flattened_at timestamptz\n"
    ")"
)

_FULFILLMENTS_INSERT_COLUMNS = (
    ["fulfillment_id", "day"]
    + _FULFILLMENTS_TEXT_DIM_COLUMNS
    + _FULFILLMENTS_BOOLEAN_COLUMNS
    + _FULFILLMENTS_TIMESTAMP_COLUMNS
    + _FULFILLMENTS_NUMERIC_DIM_COLUMNS
    + _FULFILLMENTS_METRIC_COLUMNS
    + ["extracted_at", "flattened_at"]
)

_FULFILLMENTS_INSERT = (
    "WITH latest AS (\n"
    "    -- DISTINCT ON, not MAX()+self-join -- see the orders\n"
    "    -- flatten for why: a (source_id, extracted_at) tie made\n"
    "    -- the old form emit BOTH rows, breaking this table's PK.\n"
    "    SELECT DISTINCT ON (source_id) source_id, id\n"
    "    FROM raw_dump_shopify\n"
    "    WHERE object_type = 'fulfillments' AND source_id IS NOT NULL\n"
    "    ORDER BY source_id, extracted_at DESC, id DESC\n"
    ")\n"
    f"INSERT INTO shopify_fulfillments ({', '.join(_FULFILLMENTS_INSERT_COLUMNS)})\n"
    "SELECT\n"
    "    a.source_id AS fulfillment_id,\n"
    "    NULLIF(a.raw_payload ->> 'day', '')::date AS day,\n"
    + "".join(f"    a.raw_payload ->> '{c}' AS {c},\n" for c in _FULFILLMENTS_TEXT_DIM_COLUMNS)
    + "".join(f"    (a.raw_payload ->> '{c}')::boolean AS {c},\n" for c in _FULFILLMENTS_BOOLEAN_COLUMNS)
    + "".join(f"    NULLIF(a.raw_payload ->> '{c}', '')::timestamptz AS {c},\n" for c in _FULFILLMENTS_TIMESTAMP_COLUMNS)
    + "".join(f"    NULLIF(a.raw_payload ->> '{c}', '')::numeric AS {c},\n" for c in _FULFILLMENTS_NUMERIC_DIM_COLUMNS)
    + "".join(f"    NULLIF(a.raw_payload ->> '{c}', '')::numeric AS {c},\n" for c in _FULFILLMENTS_METRIC_COLUMNS)
    + "    a.extracted_at,\n"
    "    now() AS flattened_at\n"
    "FROM raw_dump_shopify a\n"
    "JOIN latest ON latest.id = a.id\n"
    "WHERE a.object_type = 'fulfillments'"
)

def _build_shopifyql_table_sql(
    *,
    table_name: str,
    object_type: str,
    pk_column: str,
    date_columns: list[str],
    text_columns: list[str],
    boolean_columns: list[str] | None = None,
    numeric_columns: list[str],
) -> tuple[str, str]:
    """DDL + INSERT for a simple ShopifyQL-sourced Silver table: one
    raw_payload key per output column, latest-by-extracted_at per
    source_id (same two-stage-free simpler form as the other tables here --
    these are all small enough not to need the two-stage optimization),
    explicit INSERT column list (never positional -- see shopify_sessions'
    own docstring for why that matters once a table's columns grow after
    it already exists). `a.source_id` is always the right PK value here --
    scripts/ingest_shopify.py's `_NATURAL_ID_FIELD_BY_TYPE`/
    `_GROUP_BY_ROW_KEY_FIELDS` already resolve it to the correct real or
    synthetic key per object type before it ever reaches Postgres."""
    boolean_columns = boolean_columns or []
    ddl = (
        f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
        f"    {pk_column} text PRIMARY KEY,\n"
        + "".join(f"    {c} date,\n" for c in date_columns)
        + "".join(f"    {c} text,\n" for c in text_columns)
        + "".join(f"    {c} boolean,\n" for c in boolean_columns)
        + "".join(f"    {c} numeric,\n" for c in numeric_columns)
        + "    extracted_at timestamptz,\n"
        "    flattened_at timestamptz\n"
        ")"
    )
    insert_columns = [pk_column] + date_columns + text_columns + boolean_columns + numeric_columns + ["extracted_at", "flattened_at"]
    select_lines = [f"    a.source_id AS {pk_column},"]
    select_lines += [f"    NULLIF(a.raw_payload ->> '{c}', '')::date AS {c}," for c in date_columns]
    select_lines += [f"    a.raw_payload ->> '{c}' AS {c}," for c in text_columns]
    select_lines += [f"    (a.raw_payload ->> '{c}')::boolean AS {c}," for c in boolean_columns]
    select_lines += [f"    NULLIF(a.raw_payload ->> '{c}', '')::numeric AS {c}," for c in numeric_columns]
    select_lines += ["    a.extracted_at,", "    now() AS flattened_at"]
    insert_sql = (
        "WITH latest AS (\n"
        "    -- DISTINCT ON, not MAX()+self-join -- see the orders\n"
        "    -- flatten for why: a (source_id, extracted_at) tie made\n"
        "    -- the old form emit BOTH rows, breaking this table's PK.\n"
        "    SELECT DISTINCT ON (source_id) source_id, id\n"
        "    FROM raw_dump_shopify\n"
        f"    WHERE object_type = '{object_type}' AND source_id IS NOT NULL\n"
        "    ORDER BY source_id, extracted_at DESC, id DESC\n"
        ")\n"
        f"INSERT INTO {table_name} ({', '.join(insert_columns)})\n"
        "SELECT\n" + "\n".join(select_lines) + "\n"
        "FROM raw_dump_shopify a\n"
        "JOIN latest ON latest.id = a.id\n"
        f"WHERE a.object_type = '{object_type}'"
    )
    return ddl, insert_sql


#: Mirrors scripts/ingest_shopify.py's CUSTOMER_ANALYTICS_GROUP_BY/METRICS
#: (kept in sync by hand, same app/ never-imports-scripts/ boundary as
#: everywhere else). Bronze object_type "customer_analytics", NOT
#: "customers" -- see that module's docstring for the naming-collision
#: reason. PK is customer_id (a real natural key here, unlike sessions).
_CUSTOMER_ANALYTICS_DDL, _CUSTOMER_ANALYTICS_INSERT = _build_shopifyql_table_sql(
    table_name="shopify_customer_analytics",
    object_type="customer_analytics",
    pk_column="customer_id",
    date_columns=["first_order_date", "last_order_date", "customer_cohort_month"],
    text_columns=[
        "customer_email", "customer_name", "customer_city", "customer_country", "customer_region",
        "rfm_group", "predicted_spend_tier", "customer_account_status",
        "customer_email_subscription_status", "customer_sms_subscription_status",
    ],
    numeric_columns=[
        "days_since_last_order", "new_customer_records", "total_amount_spent",
        "total_amount_spent_per_order", "total_number_of_orders",
    ],
)

#: Mirrors ingest_shopify.py's SALES_GROUP_BY/METRICS. PK is order_id.
#: cost_of_goods_sold/gross_profit/gross_margin come back 0 on every row
#: for this store (confirmed live 2026-08-26 -- no per-product cost data
#: entered in Shopify) -- fetched anyway in case that changes later, not
#: missing/broken, just genuinely zero today.
_SALES_DDL, _SALES_INSERT = _build_shopifyql_table_sql(
    table_name="shopify_sales",
    object_type="sales",
    pk_column="order_id",
    date_columns=["day"],
    text_columns=["new_or_returning_customer"],
    boolean_columns=["is_pos_sale", "cost_is_recorded"],
    numeric_columns=[
        "gross_sales", "net_sales", "total_sales", "discounts", "shipping_charges", "taxes", "duties",
        "cost_of_goods_sold", "gross_profit", "gross_margin", "orders", "quantity_ordered", "average_order_value",
    ],
)

#: Mirrors ingest_shopify.py's DISCOUNTS_GROUP_BY/METRICS. No single
#: natural key (an order can carry more than one discount line) -- PK is
#: the synthetic (day, order_id, discount_code, ...) hash ingest_shopify.py
#: generates, same pattern as shopify_sessions.
_DISCOUNTS_DDL, _DISCOUNTS_INSERT = _build_shopifyql_table_sql(
    table_name="shopify_discounts",
    object_type="discounts",
    pk_column="discount_key",
    date_columns=["day"],
    text_columns=["order_id", "discount_code", "discount_type", "discount_method", "discount_class"],
    numeric_columns=[
        "applied_discounts", "discounted_orders", "product_and_order_discounts", "shipping_discounts",
    ],
)

#: Mirrors ingest_shopify.py's INVENTORY_GROUP_BY/METRICS. No single
#: natural key (one SKU has a row per day) -- PK is the synthetic
#: (day, product_variant_sku) hash, same pattern as discounts/sessions.
_INVENTORY_DDL, _INVENTORY_INSERT = _build_shopifyql_table_sql(
    table_name="shopify_inventory",
    object_type="inventory",
    pk_column="inventory_key",
    date_columns=["day"],
    text_columns=["product_variant_sku", "product_title", "product_variant_title", "product_status", "product_type", "product_vendor"],
    numeric_columns=[
        "ending_inventory_units", "ending_inventory_value", "days_of_inventory_remaining",
        "sell_through_rate", "inventory_units_sold", "starting_inventory_units",
    ],
)

#: sales_revenue/returns was checked live (2026-08-26) over an 18-month
#: window and returned ZERO rows -- this store doesn't process returns
#: through Shopify. Deliberately not built, see ingest_shopify.py's
#: matching note.

_TABLES = [
    ("shopify_orders", _ORDERS_DDL, "TRUNCATE shopify_orders", _ORDERS_INSERT),
    ("shopify_customers", _CUSTOMERS_DDL, "TRUNCATE shopify_customers", _CUSTOMERS_INSERT),
    ("shopify_sessions", _SESSIONS_DDL, "TRUNCATE shopify_sessions", _SESSIONS_INSERT),
    ("shopify_fulfillments", _FULFILLMENTS_DDL, "TRUNCATE shopify_fulfillments", _FULFILLMENTS_INSERT),
    ("shopify_customer_analytics", _CUSTOMER_ANALYTICS_DDL, "TRUNCATE shopify_customer_analytics", _CUSTOMER_ANALYTICS_INSERT),
    ("shopify_sales", _SALES_DDL, "TRUNCATE shopify_sales", _SALES_INSERT),
    ("shopify_discounts", _DISCOUNTS_DDL, "TRUNCATE shopify_discounts", _DISCOUNTS_INSERT),
    ("shopify_inventory", _INVENTORY_DDL, "TRUNCATE shopify_inventory", _INVENTORY_INSERT),
]

_INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_shopify_orders_customer_id ON shopify_orders (customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_orders_created_at ON shopify_orders (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_orders_utm_campaign ON shopify_orders (utm_campaign)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_customers_email ON shopify_customers (email)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_sessions_day ON shopify_sessions (day)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_sessions_utm_campaign ON shopify_sessions (utm_campaign)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_sessions_landing_page_path ON shopify_sessions (landing_page_path)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_fulfillments_order_id ON shopify_fulfillments (order_id)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_fulfillments_day ON shopify_fulfillments (day)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_customer_analytics_rfm_group ON shopify_customer_analytics (rfm_group)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_sales_day ON shopify_sales (day)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_discounts_day ON shopify_discounts (day)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_discounts_order_id ON shopify_discounts (order_id)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_inventory_day ON shopify_inventory (day)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_inventory_sku ON shopify_inventory (product_variant_sku)",
]

#: `CREATE TABLE IF NOT EXISTS` only helps a genuinely fresh install --
#: shopify_sessions already existed (created 2026-08-25 with just the
#: original 4 metrics, then 2026-08-26 with 16 metrics but no page-path
#: dims) before this column set was finalized, so a plain no-op CREATE
#: would leave newly-added columns missing and the INSERT below would fail
#: with "column does not exist". Same "safe to call every time" migration
#: idiom as scripts/sql/raw_dump_shopify.sql's ALTER COLUMN for object_type.
_SESSIONS_COLUMN_MIGRATIONS = [
    f"ALTER TABLE IF EXISTS shopify_sessions ADD COLUMN IF NOT EXISTS {c} numeric"
    for c in _SESSIONS_METRIC_COLUMNS
] + [
    f"ALTER TABLE IF EXISTS shopify_sessions ADD COLUMN IF NOT EXISTS {c} text"
    for c in _SESSIONS_TEXT_DIM_COLUMNS
]

#: shopify_fulfillments already existed (created 2026-08-26 with only 9
#: metrics + 11 dimensions) before the full doc field set was added -- same
#: migration idiom as orders/sessions above.
_FULFILLMENTS_COLUMN_MIGRATIONS = (
    [f"ALTER TABLE IF EXISTS shopify_fulfillments ADD COLUMN IF NOT EXISTS {c} text" for c in _FULFILLMENTS_TEXT_DIM_COLUMNS]
    + [f"ALTER TABLE IF EXISTS shopify_fulfillments ADD COLUMN IF NOT EXISTS {c} boolean" for c in _FULFILLMENTS_BOOLEAN_COLUMNS]
    + [f"ALTER TABLE IF EXISTS shopify_fulfillments ADD COLUMN IF NOT EXISTS {c} timestamptz" for c in _FULFILLMENTS_TIMESTAMP_COLUMNS]
    + [f"ALTER TABLE IF EXISTS shopify_fulfillments ADD COLUMN IF NOT EXISTS {c} numeric" for c in _FULFILLMENTS_NUMERIC_DIM_COLUMNS]
    + [f"ALTER TABLE IF EXISTS shopify_fulfillments ADD COLUMN IF NOT EXISTS {c} numeric" for c in _FULFILLMENTS_METRIC_COLUMNS]
)


async def ensure_shopify_tables(session: AsyncSession) -> None:
    await session.execute(text(_BRONZE_SHOPIFY_INDEX))
    for _, ddl, _, _ in _TABLES:
        await session.execute(text(ddl))
    for statement in _ORDERS_COLUMN_MIGRATIONS + _SESSIONS_COLUMN_MIGRATIONS + _FULFILLMENTS_COLUMN_MIGRATIONS:
        await session.execute(text(statement))
    for statement in _INDEX_STATEMENTS:
        await session.execute(text(statement))
    await session.commit()


async def refresh_shopify_tables(session: AsyncSession) -> dict[str, int]:
    """Rebuild shopify_orders/shopify_customers/shopify_sessions from the
    latest raw_dump_shopify snapshot of each entity. No cross-table
    dependency, so order between them doesn't matter."""
    await ensure_shopify_tables(session)

    counts: dict[str, int] = {}
    for table, _, truncate_sql, insert_sql in _TABLES:
        await session.execute(text(truncate_sql))
        await session.execute(text(insert_sql))
        await session.commit()
        result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        counts[table] = result.scalar_one()

    logger.info("shopify_tables_refreshed", **counts)
    return counts
