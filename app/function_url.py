"""Validate Lambda targets and send signed HTTPS requests without redirects."""

import http.client
import json
import re
from urllib.parse import urlsplit

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def validate_url(url, region):
    """Accept only the HTTPS root of a Function URL in the configured region."""

    if not isinstance(url, str) or not re.fullmatch(
        rf"https://[a-z0-9]{{32}}\.lambda-url\.{re.escape(region)}\.on\.aws/", url
    ):
        raise ValueError("Provide the complete Function URL for the team's agent.")

    return url


def post_signed(url, message, session, region, timeout, max_bytes):
    """Sign the request with temporary credentials and limit the response size without retrying."""

    validate_url(url, region)

    payload = json.dumps({"message": message}).encode("utf-8")
    credentials = session.get_credentials().get_frozen_credentials()
    request = AWSRequest(
        method="POST",
        url=url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    SigV4Auth(credentials, "lambda", region).add_auth(request)

    connection = http.client.HTTPSConnection(urlsplit(url).hostname, timeout=3)

    try:
        connection.connect()
        connection.sock.settimeout(timeout)
        connection.request(
            "POST", "/", body=payload, headers=dict(request.headers.items())
        )

        response = connection.getresponse()
        body = response.read(max_bytes + 1)

        if response.status != 200 or len(body) > max_bytes:
            raise ValueError(
                "The outcome is unconfirmed, so inspect state before repeating care."
            )

        return body
    finally:
        connection.close()
