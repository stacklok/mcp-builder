from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    debug: bool = False
    mcp_host: str = "0.0.0.0"  # nosec B104
    mcp_port: int = 8100
