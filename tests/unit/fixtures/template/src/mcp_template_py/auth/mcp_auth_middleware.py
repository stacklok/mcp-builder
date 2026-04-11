import contextvars
import os

_current_bearer_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_bearer_token", default=None
)


def get_bearer_token() -> str | None:
    token = _current_bearer_token.get()
    if token is not None:
        return token
    return os.environ.get("UPSTREAM_API_TOKEN")
