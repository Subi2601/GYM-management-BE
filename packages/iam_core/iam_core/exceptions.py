from fastapi import HTTPException, status


class AuthenticationError(HTTPException):
    def __init__(self, detail: str = "Authentication required"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


class PermissionDeniedError(HTTPException):
    def __init__(self, detail: str = "Permission denied"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class TokenExpiredError(AuthenticationError):
    def __init__(self):
        super().__init__(detail="Token has expired")


class TokenBlacklistedError(AuthenticationError):
    def __init__(self):
        super().__init__(detail="Token has been revoked")


class InvalidTokenError(AuthenticationError):
    def __init__(self):
        super().__init__(detail="Invalid token")
