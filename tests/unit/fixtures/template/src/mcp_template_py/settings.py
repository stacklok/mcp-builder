from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    debug: bool = Field(default=False)
    mcp_host: str = Field(default="0.0.0.0")
    mcp_port: int = Field(default=8100)
