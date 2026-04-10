from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import structlog
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount

from mcp_template_py.api.mcp_builder import MCPBuilder
from mcp_template_py.auth import TokenPassthroughMiddleware
from mcp_template_py.settings import Settings


class AppBuilder:
    logger = structlog.get_logger()

    @staticmethod
    def build_app(settings: Settings | None = None) -> Starlette:
        settings = settings or Settings()

        mcp = MCPBuilder.build_mcp(settings)
        mcp_http_app = mcp.streamable_http_app()

        @asynccontextmanager
        async def lifespan(_app: Starlette) -> AsyncIterator[None]:
            async with mcp.session_manager.run():
                AppBuilder.logger.info("MCP session manager started")
                yield
            AppBuilder.logger.info("MCP session manager stopped")

        middleware = [
            Middleware(
                cast(Any, TokenPassthroughMiddleware),
                require_bearer_token=settings.require_bearer_token,
            ),
        ]

        routes = [Mount("/", app=mcp_http_app, middleware=middleware)]

        return Starlette(
            routes=routes,
            lifespan=lifespan,
        )
