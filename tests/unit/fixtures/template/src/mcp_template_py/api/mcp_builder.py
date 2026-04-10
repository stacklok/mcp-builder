import structlog
from mcp.server.fastmcp import FastMCP

from mcp_template_py.api.tools import Tools
from mcp_template_py.settings import Settings


class MCPBuilder:
    logger = structlog.get_logger()

    @staticmethod
    def build_mcp(
        settings: Settings | None = None,
    ) -> FastMCP:
        settings = settings or Settings()

        mcp = FastMCP("mcp-template-py", host=settings.mcp_host, port=settings.mcp_port)

        tools = Tools()
        mcp.add_tool(tools.hello)

        return mcp
