#!/usr/bin/env python

import errno
import hashlib
import os
import stat
import subprocess
import backoff
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from requests.packages.urllib3.util.retry import Retry

from logger import get_logger

REQ_RETRY_TOTAL = 5 if os.getenv("REQ_RETRY_TOTAL") is None else int(os.getenv("REQ_RETRY_TOTAL"))
REQ_RETRY_CONNECT = 10 if os.getenv("REQ_RETRY_CONNECT") is None else int(os.getenv("REQ_RETRY_CONNECT"))
REQ_RETRY_READ = 5 if os.getenv("REQ_RETRY_READ") is None else int(os.getenv("REQ_RETRY_READ"))
REQ_RETRY_BACKOFF_FACTOR = 1.1 if os.getenv("REQ_RETRY_BACKOFF_FACTOR") is None else float(
    os.getenv("REQ_RETRY_BACKOFF_FACTOR"))
REQ_TIMEOUT = 10 if os.getenv("REQ_TIMEOUT") is None else float(os.getenv("REQ_TIMEOUT"))

# Allows to suppress TLS verification for all HTTPs requests (except to the API server, which are controller by SKIP_TLS_VERIFY)
# This is particularly useful when the connection to the main container happens as "localhost"
# and most likely the TLS cert offered by that will have an external URL in it.
# Note that the latest 'requests' library no longer offer a way to disable this via
# env vars; however a custom truststore can be set via REQUESTS_CA_BUNDLE
REQ_TLS_VERIFY = False if os.getenv("REQ_SKIP_TLS_VERIFY") == "true" else None

# Tune default timeouts as outlined in
# https://github.com/kubernetes-client/python/issues/1148#issuecomment-626184613
# https://github.com/kubernetes-client/python/blob/master/examples/watch/timeout-settings.md
# I picked 60 and 66 due to https://github.com/nolar/kopf/issues/847#issuecomment-971651446

# 60 is a polite request to the server, asking it to cleanly close the connection after that.
# If you have a network outage, this does nothing.
# You can set this number much higher, maybe to 3600 seconds (1h).
WATCH_SERVER_TIMEOUT = os.environ.get("WATCH_SERVER_TIMEOUT", 60)

# 66 is a client-side timeout, configuring your local socket.
# If you have a network outage dropping all packets with no RST/FIN,
# this is how long your client waits before realizing & dropping the connection.
# You can keep this number low, maybe 60 seconds.
WATCH_CLIENT_TIMEOUT = os.environ.get("WATCH_CLIENT_TIMEOUT", 66)

# Get logger
logger = get_logger()


@backoff.on_exception(
    wait_gen=backoff.expo,
    exception=(
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    ),
    max_time=60,
    on_backoff=lambda details: logger.warning(f"backoff try {details['tries']} waiting {details['wait']:.1f}s"),
    giveup=lambda e: e.response.status_code == 404  # 404 isn't a error but just means no records found
)
def request_get(url, headers):
    response = requests.get(
        url,
        auth=None,
        headers=headers,
    )
    response.raise_for_status()
    logger.info(f'get request {url} with headers {headers} giving response {response.status_code}')
    return response

@backoff.on_exception(
    wait_gen=backoff.expo,
    exception=(
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    ),
    max_time=120,
    on_backoff=lambda details: logger.warning(f"backoff try {details['tries']} waiting {details['wait']:.1f}s")
)
def request_post(url, headers, data):
    response = requests.post(
        url,
        auth=None,
        data=data,
        headers=headers,
    )
    logger.info(f'post request {url} with headers {headers} giving response {response.status_code}')
    response.raise_for_status()


@backoff.on_exception(
    wait_gen=backoff.expo,
    exception=(
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    ),
    max_time=120,
    on_backoff=lambda details: logger.warning(f"backoff try {details['tries']} waiting {details['wait']:.1f}s")
)
def request_delete(url, headers):
    response = requests.delete(
        url,
        auth=None,
        headers=headers,
    )
    logger.info(f'delete request {url} with headers {headers} giving response {response.status_code}')
    response.raise_for_status()
    return response
