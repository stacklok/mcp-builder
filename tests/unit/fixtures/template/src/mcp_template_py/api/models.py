from pydantic import BaseModel, Field


class HelloRequest(BaseModel):
    name: str = Field(..., description="The name of the user.")


class HelloResponse(BaseModel):
    result: str = Field(..., description="The greeting message.")
