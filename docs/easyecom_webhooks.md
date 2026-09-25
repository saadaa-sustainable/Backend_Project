# EasyEcom webhooks — what actually arrives

Taken from EasyEcom's published Postman collection, which is the only
complete source for the OUTBOUND payloads (the support article and the
`api-docs.easyecom.io` page do not show them). The docs site is a
Postman documenter, so the collection is fetchable as JSON:

    https://documenter.gw.postman.com/api/collections/20795951/2s93ecupH6?segregateAuth=true&versionTag=latest

Re-fetch it rather than trusting this file if a payload stops matching.

## Three shapes, not one

| Event | Body shape | Keys |
|---|---|---|
| `create_order`, `confirm_order`, `rtd`, `manifested`, `cancel_order` | `[{...}]` | one shared ~95-field order schema |
| `mark_return` | `[[{...}]]` **double-nested** | order schema + `credit_note_id`, `credit_note_date`, `return_date` |
| `tracking` | `[{...}]` | a **completely different, camelCase** schema |

Every one is an ARRAY at the top level. The `webhook_events.payload`
column is `jsonb` and stores the body verbatim, so all three land
intact; the consumer is what has to branch.

## The shared order schema

Keyed on `invoice_id` (+ `order_id`, `reference_code`). Line items are
under **`order_items`**, and there is an `easyecom_order_history` array.

Field names DIFFER from `getAllOrders`, so the two cannot share a
mapper:

| webhook | getAllOrders |
|---|---|
| `warehouse_id` | `warehouseId` |
| `package_weight` | `"Package Weight"` (space, capitals) |
| `order_items` | `suborders` |

## The tracking schema

This is the delivery-status event, and the only one carrying an
expected delivery date — so it is the one the RTO correction depends
on. Entirely camelCase and keyed differently again:

    invoiceId, orderId, suborder_id, awbNumber, reference_code,
    currentShippingStatus, shipping_status_id, status_id,
    expectedDeliveryDate, expectedDeliveryDateStart/End,
    orderStatus, carrierName, carrier_id, invoiceAmount, tax,
    orderDate, invoiceDate, city, state, pin_code,
    items            <- array of "Name (SKU) X qty" STRINGS, not objects
    shippingHistory, last_status, last_status_update

`items` being pre-formatted strings means the tracking event cannot be
used for SKU-level analysis; join back to `easyecom_orders` on
`invoiceId` for that.

## Routing

The receiver takes the event from the LAST PATH SEGMENT of the URL:

    https://<project>.supabase.co/functions/v1/easyecom-webhook/tracking

so the segment configured in EasyEcom has to match the event chosen in
its dropdown. Nothing downstream can detect a mismatch — a Cancel Order
posted to `/tracking` is stored as a tracking event. Accepted segments
are the 12 in `EVENTS` in `supabase/functions/easyecom-webhook/index.ts`;
anything else is a 422 at setup time, which is the point.

## Auth, for the pull side

Both headers are mandatory on every API call:

    x-api-key       long lived, Settings -> API, primary account only
    Authorization   Bearer <jwt>, 90 days, POST /access/token with
                    {email, password, location_key}
                      -> data.token.jwt_token

The JWT is scoped to ONE `location_key`, and V2.1 `getAllOrders` has no
marketplace parameter — only `start_date`, `end_date`, `cursor`. So the
window and the location are the only things deciding which orders come
back, and a channel fulfilled from another warehouse is absent with no
error. `scripts/mint_easyecom_jwt.py` lists every location for this
reason.
