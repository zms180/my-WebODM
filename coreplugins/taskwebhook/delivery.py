def deliver_webhook(webhook_url, webhook_secret, payload, connect_timeout,
                    read_timeout, max_attempts, retry_base_seconds):
    import hashlib
    import hmac
    import json
    import logging
    import time

    import requests

    logger = logging.getLogger("app.logger")
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "WebODM-TaskWebhook/1.0",
        "X-WebODM-Event": payload["event"],
        "X-WebODM-Event-Id": payload["event_id"],
        "X-WebODM-Timestamp": timestamp,
    }

    if webhook_secret:
        signed_data = timestamp.encode("utf-8") + b"." + body
        signature = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_data,
            hashlib.sha256,
        ).hexdigest()
        headers["X-WebODM-Signature"] = "sha256={}".format(signature)

    max_attempts = max(1, int(max_attempts))
    last_error = "unknown error"

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                webhook_url,
                data=body,
                headers=headers,
                timeout=(connect_timeout, read_timeout),
                allow_redirects=False,
            )

            if 200 <= response.status_code < 300:
                logger.info(
                    "TaskWebhook: delivered event %s with status %s",
                    payload["event_id"],
                    response.status_code,
                )
                return {
                    "delivered": True,
                    "event_id": payload["event_id"],
                    "status_code": response.status_code,
                }

            last_error = "HTTP {}: {}".format(
                response.status_code,
                response.text[:500],
            )
            retryable = (
                response.status_code in (408, 429)
                or response.status_code >= 500
            )
            if not retryable:
                raise RuntimeError(
                    "TaskWebhook: receiver rejected event {} ({})".format(
                        payload["event_id"],
                        last_error,
                    )
                )
        except requests.RequestException as error:
            last_error = str(error)

        if attempt < max_attempts:
            delay = retry_base_seconds * (2 ** (attempt - 1))
            logger.warning(
                "TaskWebhook: delivery attempt %s/%s failed for event %s: %s; retrying in %ss",
                attempt,
                max_attempts,
                payload["event_id"],
                last_error,
                delay,
            )
            time.sleep(delay)

    raise RuntimeError(
        "TaskWebhook: failed to deliver event {} after {} attempts: {}".format(
            payload["event_id"],
            max_attempts,
            last_error,
        )
    )
