from mcp_template_py.api.mcp_builder import MCPBuilder


class AppBuilder:
    @staticmethod
    def build_app():
        return MCPBuilder.build_mcp()
