from fastapi import Request


def set_flash(request: Request, message: str):
    request.session["flash"] = message


def pop_flash(request: Request) -> str | None:
    return request.session.pop("flash", None)
