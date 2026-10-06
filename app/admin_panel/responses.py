from __future__ import annotations

from fastapi.responses import JSONResponse


def success(message: str = "Request completed successfully", data=None) -> dict:
    return {"success": True, "message": message, "data": {} if data is None else data}


def failure(status_code: int, message: str, error_code: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "message": message, "error_code": error_code, "details": details},
    )


class AdminHTTPError(Exception):
    """Raised by dependencies; main.py turns it into the standard error envelope."""

    def __init__(self, status_code: int, message: str, error_code: str):
        self.status_code = status_code
        self.message = message
        self.error_code = error_code
        super().__init__(message)


async def admin_http_error_handler(_request, exc: AdminHTTPError) -> JSONResponse:
    return failure(exc.status_code, exc.message, exc.error_code)
