"""Derrière nginx (lot 17) : préfixe public et en-têtes de sécurité.

nginx sert le coffre sous https://agenc-ai.com/jeff/espace/… et le transmet à l'application
sans le préfixe, avec l'en-tête X-Forwarded-Prefix: /jeff. L'application reprend ce préfixe
pour ses liens, redirections et cookies. Par le tunnel SSH (sans en-tête), rien ne change.
L'application n'écoute que sur 127.0.0.1 : seul nginx (ou le tunnel) peut lui parler.
"""
import re

from starlette._utils import get_route_path

PREFIXE_VALIDE = re.compile(r"^/[A-Za-z0-9_-]{1,30}$")
ENTETES_ESPACE = (
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"permissions-policy", b"geolocation=(), microphone=(), payment=()"),
)
SANS_CACHE = (b"cache-control", b"private, no-store")


class PrefixeEtSecurite:
    """Middleware ASGI : préfixe X-Forwarded-Prefix, et en-têtes de sécurité sur les pages du coffre."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        entetes = dict(scope.get("headers", []))
        prefixe = entetes.get(b"x-forwarded-prefix", b"").decode("latin-1")
        if prefixe and PREFIXE_VALIDE.match(prefixe):
            scope = {**scope, "root_path": prefixe}
        coffre = get_route_path(scope).startswith("/espace")

        async def envoyer(message):
            if coffre and message["type"] == "http.response.start":
                presents = {nom.lower() for nom, _ in message.get("headers", [])}
                ajouts = [e for e in ENTETES_ESPACE if e[0] not in presents]
                if SANS_CACHE[0] not in presents:
                    ajouts.append(SANS_CACHE)
                message = {**message, "headers": list(message.get("headers", [])) + ajouts}
            await send(message)

        await self.app(scope, receive, envoyer)
