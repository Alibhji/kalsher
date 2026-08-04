from __future__ import annotations

from aiohttp import ClientSession, web

from common.logging import get_logger
from common.settings import UiSettings

log = get_logger(__name__)


async def proxy_trading(request: web.Request) -> web.Response:
    settings: UiSettings = request.app["settings"]
    session: ClientSession = request.app["http"]
    tail = request.match_info.get("tail", "")
    target = f"{settings.trader_url.rstrip('/')}/api/{tail}"
    if request.query_string:
        target = f"{target}?{request.query_string}"

    headers: dict[str, str] = {}
    confirm = request.headers.get("X-Confirm-Live")
    if confirm:
        headers["X-Confirm-Live"] = confirm
    ct = request.headers.get("Content-Type")
    if ct:
        headers["Content-Type"] = ct

    body = await request.read() if request.can_read_body else None

    try:
        async with session.request(request.method, target, headers=headers, data=body) as resp:
            payload = await resp.read()
            return web.Response(
                body=payload,
                status=resp.status,
                content_type=resp.content_type or "application/json",
            )
    except Exception as exc:
        log.error("trading_proxy_failed", target=target, error=str(exc))
        return web.json_response({"error": "trader unavailable", "detail": str(exc)}, status=502)
