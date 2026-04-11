import structlog

from mcp_template_py.api.models import HelloRequest, HelloResponse


class Tools:
    def __init__(self):
        self._logger: structlog.BoundLogger = structlog.get_logger()

    async def hello(self, request: HelloRequest) -> HelloResponse:
        """Say hello to the user."""
        self._logger.info("hello tool called", name=request.name)
        return HelloResponse(result=f"Hello, {request.name}!")
