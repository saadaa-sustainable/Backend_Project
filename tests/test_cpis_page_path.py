"""An ad's landing URL and an order's Shopify full_url must land on the
same page key, or the order never shares that page's spend."""
from app.services.gold.cpis import page_path


def test_ad_url_and_order_url_meet():
    ad = "https://saadaa.in/collections/diwali-special/men/?utm_source=meta"
    order = "https://saadaa-design.myshopify.com/collections/diwali-special/men?utm_content=1202&fbclid=x#top"
    assert page_path(ad) == page_path(order) == "/collections/diwali-special/men"


def test_product_inside_collection_is_the_product():
    assert page_path("https://www.saadaa.in/collections/men/products/cotton-pant") == "/products/cotton-pant"


def test_homepage_offsite_and_missing():
    assert page_path("https://saadaa.in/?fbclid=1") == page_path("https://saadaa.in") == "/"
    assert page_path("https://wa.me/91999") == "OFFSITE"
    assert page_path(None) is None and page_path("") is None
