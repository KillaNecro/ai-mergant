"""XML feed parsing tests (nested products, RSS, Google-like feed)."""
import io


def _upload(client, name, content):
    return client.post(
        "/api/import/preview",
        files={"file": (name, io.BytesIO(content), "application/xml")},
    )


def test_products_wrapper_xml(client):
    xml = ("<?xml version='1.0' encoding='UTF-8'?>\n"
           "<products>\n"
           "  <product><sku>X-1</sku><name>Ürün Bir</name><price>19,90</price></product>\n"
           "  <product><sku>X-2</sku><name>Ürün İki</name><price>29,90</price></product>\n"
           "</products>").encode("utf-8")
    r = _upload(client, "feed.xml", xml)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_rows"] == 2
    assert body["rows"][1]["name"] == "Ürün İki"


def test_items_wrapper_xml(client):
    xml = ("<?xml version='1.0'?>\n"
           "<items>\n"
           "  <item><sku>I-1</sku><name>Bir</name></item>\n"
           "  <item><sku>I-2</sku><name>İki</name></item>\n"
           "</items>").encode("utf-8")
    r = _upload(client, "items.xml", xml)
    assert r.status_code == 200
    assert r.json()["total_rows"] == 2


def test_rss_channel_item_xml(client):
    xml = ("<?xml version='1.0'?>\n"
           "<rss version=\"2.0\">\n"
           "  <channel>\n"
           "    <title>Feed</title>\n"
           "    <item><sku>R-1</sku><title>Ürün 1</title><price>9,90</price></item>\n"
           "    <item><sku>R-2</sku><title>Ürün 2</title><price>19,90</price></item>\n"
           "  </channel>\n"
           "</rss>").encode("utf-8")
    r = _upload(client, "rss.xml", xml)
    assert r.status_code == 200
    assert r.json()["total_rows"] == 2


def test_google_merchant_like_xml(client):
    xml = ("<?xml version='1.0'?>\n"
           "<rss xmlns:g=\"http://base.google.com/ns/1.0\" version=\"2.0\">\n"
           "  <channel>\n"
           "    <item>\n"
           "      <g:id>GM-1</g:id><title>Ürün A</title><g:price>99,90 TRY</g:price>\n"
           "    </item>\n"
           "    <item>\n"
           "      <g:id>GM-2</g:id><title>Ürün B</title><g:price>149,90 TRY</g:price>\n"
           "    </item>\n"
           "  </channel>\n"
           "</rss>").encode("utf-8")
    r = _upload(client, "gm.xml", xml)
    assert r.status_code == 200
    body = r.json()
    assert body["total_rows"] == 2
    cols = body["columns"]
    assert "title" in cols


def test_unrecognized_xml_structure_rejected(client):
    xml = b"<?xml version='1.0'?><root><meta><a>1</a></meta></root>"
    r = _upload(client, "flat.xml", xml)
    assert r.status_code == 400
    assert "XML" in r.json()["detail"]
