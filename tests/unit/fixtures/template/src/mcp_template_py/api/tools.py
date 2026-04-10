from mcp_template_py.api.models import HelloRequest, HelloResponse


class Tools:
    async def hello(self, request: HelloRequest) -> HelloResponse:
        return HelloResponse(result=f"Hello, {request.name}!")
