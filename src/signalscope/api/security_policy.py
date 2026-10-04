from signalscope.core.settings import Environment, Settings

# Production policy for the same-origin React app and JSON API. Scripts load
# only from this origin; there is no unsafe-eval and no unsafe-inline for
# scripts. 'unsafe-inline' is allowed for style only, because the React app sets
# inline style attributes on elements; styles cannot run code. No third-party
# origins are allowed.
PRODUCTION_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# Development adds what the Vite dev server and tooling need: eval for the dev
# runtime and a websocket for hot reload. It is never used in production.
DEVELOPMENT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def content_security_policy(settings: Settings) -> str:
    """The content security policy for the current environment."""
    if settings.environment is Environment.PRODUCTION:
        return PRODUCTION_CSP
    return DEVELOPMENT_CSP
