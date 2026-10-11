"""One error type for the whole backend. `code` is stable and machine-readable (the UI switches on it)."""


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def invalid(msg): return ServiceError("INVALID_REQUEST", msg, 400)
def not_found(msg): return ServiceError("NOT_FOUND", msg, 404)
def conflict(code, msg): return ServiceError(code, msg, 409)
