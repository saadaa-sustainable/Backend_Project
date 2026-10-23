-- Separate allocation source: the Equal / Order tables remain unchanged.
CREATE TABLE IF NOT EXISTS public.cpis_value_weighted_daily (
    day date NOT NULL,
    entity_id text NOT NULL,
    master_sku text NOT NULL,
    attributed_orders integer NOT NULL,
    attributed_units integer NOT NULL,
    attributed_revenue numeric NOT NULL,
    order_revenue numeric NOT NULL,
    order_units integer NOT NULL,
    entity_orders integer NOT NULL,
    entity_spend numeric NOT NULL,
    ad_spend numeric NOT NULL,
    halo_orders integer NOT NULL,
    halo_units integer NOT NULL,
    halo_revenue numeric NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (day, entity_id, master_sku)
);
-- Backend-only reporting data. No anonymous/authenticated Data API policies.
ALTER TABLE public.cpis_value_weighted_daily ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.cpis_value_weighted_daily FROM anon, authenticated;
