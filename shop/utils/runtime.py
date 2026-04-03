import logging
from logging.config import dictConfig

from flask import request
from flask_jwt_extended.exceptions import JWTExtendedException
from werkzeug.exceptions import HTTPException

from shop.utils.api_response import error_response


def configure_logging(app):
    level = str(app.config.get("LOG_LEVEL", "INFO")).upper()

    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://flask.logging.wsgi_errors_stream",
            }
        },
        "root": {
            "level": level,
            "handlers": ["wsgi"],
        },
    })

    app.logger.setLevel(level)


def register_api_error_handlers(app, jwt):
    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        if not request.path.startswith("/api/"):
            return error

        message = error.description or "Request failed."
        return error_response(message, status_code=error.code or 500)

    @app.errorhandler(JWTExtendedException)
    def handle_jwt_exception(error):
        if not request.path.startswith("/api/"):
            return error

        app.logger.warning("JWT error on %s %s: %s", request.method, request.path, error)
        return error_response(str(error), status_code=401)

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error):
        if not request.path.startswith("/api/"):
            raise error

        app.logger.exception("Unhandled API error on %s %s", request.method, request.path)
        return error_response("Internal server error", status_code=500)

    @jwt.unauthorized_loader
    def handle_missing_jwt(reason):
        return error_response(reason or "Authentication required.", status_code=401)

    @jwt.invalid_token_loader
    def handle_invalid_jwt(reason):
        return error_response(reason or "Invalid token.", status_code=401)

    @jwt.expired_token_loader
    def handle_expired_jwt(jwt_header, jwt_payload):
        return error_response("Session expired. Please login again.", status_code=401)

    @jwt.revoked_token_loader
    def handle_revoked_jwt(jwt_header, jwt_payload):
        return error_response("Session is no longer valid.", status_code=401)
