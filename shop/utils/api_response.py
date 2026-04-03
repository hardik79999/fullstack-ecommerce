from flask import jsonify


def success_response(message=None, status_code=200, **payload):
    body = {"success": True}
    if message is not None:
        body["message"] = message
    body.update(payload)
    return jsonify(body), status_code


def error_response(message, status_code=400, **payload):
    body = {
        "success": False,
        "message": message,
    }
    body.update(payload)
    return jsonify(body), status_code
