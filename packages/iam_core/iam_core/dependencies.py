from fastapi import Request

from iam_core.context import RequestContext
from iam_core.exceptions import AuthenticationError


def get_request_context(request: Request) -> RequestContext:
    ctx = getattr(request.state, "ctx", None)
    if ctx is None:
        raise AuthenticationError()
    return ctx
