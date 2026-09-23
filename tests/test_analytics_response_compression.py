"""Large analytics responses retain their full contents when compressed."""

import httpx


async def test_large_response_is_compressed_and_cors_headers_are_preserved():
    from app.main import create_app, settings

    app = create_app()
    payload = {"rows": [{"ad_id": str(i), "spend": 100, "ad_name": "Example ad"}
                        for i in range(100)], "total": 20271}

    @app.get("/admin/analytics/compression-probe")
    async def probe():
        return payload

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://test") as client:
        response = await client.get("/admin/analytics/compression-probe", headers={
            "Accept-Encoding": "gzip", "Origin": settings.admin_app_origin,
        })
        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip"
        assert response.headers["access-control-allow-origin"] == settings.admin_app_origin
        assert int(response.headers["content-length"]) < len(response.content) / 2
        assert response.json() == payload

        uncompressed = await client.get("/admin/analytics/compression-probe", headers={"Accept-Encoding": "identity"})
        assert "content-encoding" not in uncompressed.headers
        assert uncompressed.json() == payload


async def test_admin_event_stream_is_not_compressed():
    from fastapi.responses import StreamingResponse
    from app.main import create_app

    app = create_app()

    @app.get("/admin/events-probe")
    async def probe():
        async def events():
            yield "data: ready\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://test") as client:
        response = await client.get("/admin/events-probe", headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert "content-encoding" not in response.headers
        assert response.text == "data: ready\n\n"
