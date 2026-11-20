"""Same-origin static web interface and browser response headers."""

from pathlib import Path
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles


def instalar(app):
    @app.middleware("http")
    async def cabeceras_web(request, call_next):
        respuesta = await call_next(request)
        es_web = request.url.path.startswith("/interfaz") or request.url.path == "/"
        if es_web or request.headers.get("x-interfaz-web") == "1":
            respuesta.headers["Cache-Control"] = "no-store"

            if request.headers.get("x-interfaz-web") == "1":
                if "www-authenticate" in respuesta.headers:
                    del respuesta.headers["www-authenticate"]
            respuesta.headers["X-Content-Type-Options"] = "nosniff"
            respuesta.headers["Referrer-Policy"] = "no-referrer"
        if es_web:
            respuesta.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
        return respuesta

    @app.get("/", include_in_schema=False)
    def inicio_web():
        return RedirectResponse("/interfaz/")

    app.mount(
        "/interfaz",
        StaticFiles(directory=Path(__file__).resolve().parent / "interfaz", html=True),
        name="interfaz",
    )
