#!/usr/bin/env python

import os
import re

from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.config.kube_config import KUBE_CONFIG_DEFAULT_LOCATION
from requests.packages.urllib3.util.retry import Retry

from helpers import REQ_RETRY_TOTAL, REQ_RETRY_CONNECT, REQ_RETRY_READ, REQ_RETRY_BACKOFF_FACTOR
from logger import get_logger
from resources import watch_for_changes, prepare_payload

METHOD = "METHOD"
SKIP_TLS_VERIFY = "SKIP_TLS_VERIFY"
LABEL = "LABEL"
LABEL_VALUE = "LABEL_VALUE"
RESOURCE = "RESOURCE"

# Cortex
FUNCTION = "FUNCTION"  # either rules or alerts
X_SCOPE_ORGID_DEFAULT = "X_SCOPE_ORGID_DEFAULT"
X_SCOPE_ORGID_NAMESPACE_LABEL = "X_SCOPE_ORGID_NAMESPACE_LABEL"

# Cortex ruler
RULES_URL = "RULES_URL"  # /api/v1/rules

# Cortex alertmanager
ALERTS_URL = "ALERTS_URL"  # /api/v1/alerts

# Get logger
logger = get_logger()


def main():
    logger.info("Starting collector")

    label = os.getenv(LABEL)
    if label is None:
        logger.fatal("Should have added {LABEL} as environment variable! Exit")
        return -1

    label_value = os.getenv(LABEL_VALUE)
    if label_value:
        logger.debug(f"Filter labels with value: {label_value}")

    resources = os.getenv(RESOURCE, "configmap")
    resources = ("secret", "configmap") if resources == "both" else (resources,)
    logger.debug(f"Selected resource type: {resources}")

    _initialize_kubeclient_configuration()

    function = os.getenv(FUNCTION, "rules")
    x_scope_orgid_default = os.getenv(X_SCOPE_ORGID_DEFAULT, 'system')
    x_scope_orgid_namespace_label = os.getenv(X_SCOPE_ORGID_NAMESPACE_LABEL, '')
    rules_url = os.getenv(RULES_URL, None)
    alerts_url = os.getenv(ALERTS_URL, None)

    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as f:
        namespace = os.getenv("NAMESPACE", f.read())

    watch_for_changes(function, label, label_value, rules_url, alerts_url, x_scope_orgid_default, 
                        x_scope_orgid_namespace_label,
                        namespace, resources)


def _initialize_kubeclient_configuration():
    """
    Updates the default configuration of the kubernetes client. This is
    picked up later on automatically then.
    """

    # this is where kube_config is going to look for a config file
    kube_config = os.path.expanduser(KUBE_CONFIG_DEFAULT_LOCATION)
    if os.path.exists(kube_config):
        logger.info(f"Loading config from '{kube_config}'...")
        config.load_kube_config(kube_config)
    else:
        logger.info("Loading incluster config ...")
        config.load_incluster_config()

    if os.getenv(SKIP_TLS_VERIFY) == "true":
        configuration = client.Configuration.get_default_copy()
        configuration.verify_ssl = False
        configuration.debug = False
        client.Configuration.set_default(configuration)

    # push urllib3 retries to k8s client config
    configuration = client.Configuration.get_default_copy()
    configuration.retries = Retry(total=REQ_RETRY_TOTAL,
                                  connect=REQ_RETRY_CONNECT,
                                  read=REQ_RETRY_READ,
                                  backoff_factor=REQ_RETRY_BACKOFF_FACTOR)
    client.Configuration.set_default(configuration)

    logger.info(f"Config for cluster api at '{configuration.host}' loaded...")


if __name__ == "__main__":
    main()
