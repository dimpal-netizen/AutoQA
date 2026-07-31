"""Service-layer errors.

Services raise these instead of fastapi.HTTPException so they stay independent
of the web framework and can be unit-tested on their own. A single exception
handler in app/main.py maps them to HTTP status codes.
"""


class ServiceError(Exception):
    """Base class. `status_code` is what the API layer will return."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    status_code = 404


class AlreadyExists(ServiceError):
    status_code = 409


class Unauthorized(ServiceError):
    """Not authenticated, or credentials are wrong."""

    status_code = 401


class Forbidden(ServiceError):
    """Authenticated, but not allowed to do this."""

    status_code = 403


class ValidationError(ServiceError):
    status_code = 422
