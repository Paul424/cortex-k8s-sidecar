#!/usr/bin/env python

import base64
import copy
import os
import signal
import sys
import traceback
import json
import yaml
import requests
import re
from collections import defaultdict
from multiprocessing import Process
from time import sleep

from kubernetes import client, watch
from kubernetes.client.rest import ApiException
from urllib3.exceptions import MaxRetryError, ProtocolError

from helpers import (WATCH_CLIENT_TIMEOUT, WATCH_SERVER_TIMEOUT)
from helpers import request_get, request_delete, request_post
from logger import get_logger

# Get logger
logger = get_logger()


def signal_handler(signum, frame):
    logger.info("Subprocess exiting gracefully")
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_handler)


def prepare_payload(payload):
    """Prepare payload as dict for request."""
    try:
       payload_dict = json.loads(payload)
       return payload_dict
    except ValueError as err:
        logger.warning(f"Payload will be posted as quoted json")
        return payload


def _get_namespace_label(v1, namespace, label, default):
    '''
    Fetch the value of a namespace label
    '''
    if not label:
        return default
    # prevent fetching all namespaces; so a filter on name is required
    ns = v1.list_namespace(field_selector=f'metadata.name={namespace}').items[0]
    value = ns.metadata.labels.get(label, default)
    logger.info(f'get label {label} for namespace {namespace}: {value}')
    return value


def _generate_namespace_labels(v1, namespace, label, default):
    '''
    Lists all the x-scope-orgid's currently on the environment
    '''
    if default:
        yield default
    for ns in v1.list_namespace(label_selector=label).items:
        if namespace == 'ALL' or namespace == ns.metadata.name:
            yield ns.metadata.labels[label]


def _watch_resource_iterator(function, label, label_value, rules_url, alerts_url, x_scope_orgid_default, 
                        x_scope_orgid_namespace_label, 
                             namespace, resource):
    v1 = client.CoreV1Api()

    # Filter resources based on label and value or just label
    label_selector = f"{label}={label_value}" if label_value else label

    additional_args = {
        'label_selector': label_selector,
        'timeout_seconds': WATCH_SERVER_TIMEOUT,
        '_request_timeout': WATCH_CLIENT_TIMEOUT,
    }
    if namespace == "ALL":
        list_cm_f = v1.list_config_map_for_all_namespaces
    else:
        additional_args['namespace'] = namespace
        list_cm_f = v1.list_namespaced_config_map

    logger.info(f"> Performing watch-based sync on {resource} resources: {additional_args}")

    stream = watch.Watch().stream(list_cm_f, **additional_args)

    # Process events
    for event in stream:
        item = event['object']
        metadata = item.metadata
        event_type = event['type']

        # rules
        if function == "rules":
            if not re.match(r'prometheus-.*-rulefiles.*', item.metadata.name):
                logger.info(f"rules resource {item.metadata.name} is not a rules config")
                continue
            if not item.data:
                logger.info(f"rules resource {item.metadata.name} has no data")
                continue
            logger.info(f"processing rules resource {item.metadata.name}")
            for key in item.data.keys():
                document = yaml.load(item.data[key], Loader=yaml.Loader)
                for group in document['groups']:
                    if event_type == "DELETED":
                        headers = {
                            'X-Scope-OrgID': _get_namespace_label(v1, metadata.namespace, x_scope_orgid_namespace_label, x_scope_orgid_default),
                        }
                        url = f'{rules_url}/{metadata.namespace}/{group["name"]}'
                        response = request_delete(url, headers)

                    else:  # ADDED / MODIFIED
                        headers = {
                            'Content-Type': 'application/yaml',
                            'X-Scope-OrgID': _get_namespace_label(v1, metadata.namespace, x_scope_orgid_namespace_label, x_scope_orgid_default),
                        }
                        payload = {
                            'name': group["name"],
                            'rules': group["rules"],
                        }
                        url = f'{rules_url}/{metadata.namespace}'
                        response = request_post(url, headers, yaml.dump(payload))
        else:  # alerts
            if not item.data:
                logger.info(f"alerts resource {item.metadata.name} has no data")
                continue
            if len(item.data.keys()) > 1:
                raise RuntimeError(f'Alert definitions should only have one entry (configmap {item.metadata.name} has {len(item.data.keys())} items)')
            logger.info(f"processing alerts resource {item.metadata.name}")
            (_, data) = next(iter(item.data.items()))
            if event_type == "DELETED":
                headers = {
                    'X-Scope-OrgID': _get_namespace_label(v1, metadata.namespace, x_scope_orgid_namespace_label, x_scope_orgid_default),
                }
                url = f'{alerts_url}'
                response = request_delete(url, headers)

            else:  # ADDED / MODIFIED
                headers = {
                    'Content-Type': 'application/yaml',
                    'X-Scope-OrgID': _get_namespace_label(v1, metadata.namespace, x_scope_orgid_namespace_label, x_scope_orgid_default),
                }
                payload = {
                    'alertmanager_config': data,
                }
                url = f'{alerts_url}'
                response = request_post(url, headers, yaml.dump(payload))

    logger.info(f"< Performing watch-based sync on {resource} resources")

def _watch_resource_loop(*args):
    while True:
        try:
            # Always wait to slow down the loop in case of exceptions
            sleep(int(os.getenv("ERROR_THROTTLE_SLEEP", 5)))
            _watch_resource_iterator(*args)
        except ApiException as e:
            if e.status != 500:
                logger.error(f"ApiException when calling kubernetes: {e}\n")
            else:
                raise
        except ProtocolError as e:
            logger.error(f"ProtocolError when calling kubernetes: {e}\n")
        except MaxRetryError as e:
            logger.error(f"MaxRetryError when calling kubernetes: {e}\n")
        except Exception as e:
            logger.error(f"Received unknown exception: {e}\n")
            traceback.print_exc()

def _get_rule_groups(rules_url, x_scope_orgid):
    headers = {
        'X-Scope-OrgID': x_scope_orgid
    }
    try:
        url = f"{rules_url}"
        response = request_get(url, headers=headers)
        return yaml.safe_load(response.content.decode("utf-8"))
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404 and "no rule groups found" in e.response.text:
            logger.info(f"No rule groups found for x-scope-orgid {x_scope_orgid}")
            return {}
        raise

def _delete_rule_group(rules_url, namespace, x_scope_orgid, name):
    headers = {
        'X-Scope-OrgID': x_scope_orgid,
    }
    url = f'{rules_url}/{namespace}/{name}'
    request_delete(url, headers)

def _sync(function, label, label_value, rules_url, alerts_url, x_scope_orgid_default, 
                        x_scope_orgid_namespace_label, namespace, resource):
    logger.info(f"> Sync {resource}")

    v1 = client.CoreV1Api()
        
    # Fetch all the configmaps
    label_selector = f"{label}={label_value}" if label_value else label

    additional_args = {
        'label_selector': label_selector,
    }
    if namespace == "ALL":
        list_cm_f = v1.list_config_map_for_all_namespaces
    else:
        additional_args['namespace'] = namespace
        list_cm_f = v1.list_namespaced_config_map

    # Create/Update all items based on resources
    logger.info(f"Listing {resource} with {additional_args}")
    rgs = []
    for item in list_cm_f(**additional_args).items:
        metadata = item.metadata
        if function == "rules":
            if not re.match(r'prometheus-.*-rulefiles.*', item.metadata.name):
                logger.info(f"rules resource {item.metadata.name} is not a rules config")
                continue
            if not item.data:
                logger.info(f"rules resource {item.metadata.name} has no data")
                continue
            logger.info(f"processing rules resource {item.metadata.name}")
            for key in item.data.keys():
                document = yaml.load(item.data[key], Loader=yaml.Loader)
                for group in document['groups']:
                    x_scope_orgid = _get_namespace_label(v1, metadata.namespace, x_scope_orgid_namespace_label, x_scope_orgid_default)
                    rgs.append({
                        'x_scope_orgid': x_scope_orgid,
                        'namespace': metadata.namespace,
                        'name': group["name"],
                    })
                    headers = {
                        'Content-Type': 'application/yaml',
                        'X-Scope-OrgID': x_scope_orgid,
                    }
                    payload = {
                        'name': group["name"],
                        'rules': group["rules"],
                    }
                    url = f'{rules_url}/{metadata.namespace}'
                    response = request_post(url, headers, yaml.dump(payload))
        else:  # alerts
            if not item.data:
                logger.info(f"alerts resource {item.metadata.name} has no data")
                continue
            if len(item.data.keys()) > 1:
                raise RuntimeError(f'Alert definitions should only have one entry (configmap {item.metadata.name} has {len(item.data.keys())} items)')
            logger.info(f"processing alerts resource {item.metadata.name}")
            (_, data) = next(iter(item.data.items()))
            headers = {
                'Content-Type': 'application/yaml',
                'X-Scope-OrgID': _get_namespace_label(v1, metadata.namespace, x_scope_orgid_namespace_label, x_scope_orgid_default),
            }
            payload = {
                'alertmanager_config': data,
            }
            url = f'{alerts_url}'
            response = request_post(url, headers, yaml.dump(payload))

    # Remove items that no longer have the resource 

    # For each x-scope-orgid
    for x_scope_orgid in _generate_namespace_labels(v1, namespace, x_scope_orgid_namespace_label, x_scope_orgid_default):
        logger.info(f"Cleanup for x-scope-orgid {x_scope_orgid}")
        
        if function == "rules":
            # Fetch the active rule groups for given x-scope-orgid (tenant)
            namespace_rule_groups = _get_rule_groups(
                rules_url,
                x_scope_orgid,
            )
            for rule_group_namespace, rule_groups in namespace_rule_groups.items():
                if namespace != "ALL" and namespace != rule_group_namespace:
                    logger.info(f"Skip rule groups in namespace {rule_group_namespace} because filtering for only namespace {namespace}")
                    continue

                logger.info(f"processing {len(rule_groups)} rule groups in namespace {rule_group_namespace}")
                for rule_group in rule_groups:
                    if next((rg for rg in rgs if rg['x_scope_orgid'] == x_scope_orgid and rg['namespace'] == rule_group_namespace and rg['name'] == rule_group['name']), None):
                        logger.info(f"rule group {rule_group['name']} in namespace {rule_group_namespace} for x-scope-orgid {x_scope_orgid} is found")
                    else:
                        logger.info(f"rule group {rule_group['name']} in namespace {rule_group_namespace} for x-scope-orgid {x_scope_orgid} is not found; deleting rule-group")
                        _delete_rule_group(rules_url, rule_group_namespace, x_scope_orgid, rule_group['name'])
        else:  # alerts
            # An x-scope-orgid only has one config, nothing to delete
            pass

    logger.info(f"< Sync {resource}")


def _sync_loop(function, *args):
    while True:
        try:
            logger.info(f"Sync Cortex backend ({function}) with kubernetes resources")
            _sync(function, *args)
            sleep(int(os.getenv("SYNC_SLEEP", 60)))
        except Exception as e:
            logger.exception(f"Exception caught: {e}\n")
            traceback.print_exc()
            raise


def watch_for_changes(function, label, label_value, rules_url, alerts_url, x_scope_orgid_default, 
                      x_scope_orgid_namespace_label, 
                      current_namespace, resources):
    processes = _start_watcher_processes(function, current_namespace, label,
                                         label_value, resources,
                                         rules_url, alerts_url, x_scope_orgid_default, 
                        x_scope_orgid_namespace_label)

    while True:
        died = False
        for proc, ns, resource in processes:
            if not proc.is_alive():
                logger.fatal(f"Process for {ns}/{resource} died")
                died = True
        if died:
            logger.fatal("At least one process died. Stopping and exiting")
            for proc, ns, resource in processes:
                if proc.is_alive():
                    proc.terminate()
            raise Exception("Loop died")

        sleep(5)


def _start_watcher_processes(function, namespace, label, label_value, resources, 
            rules_url, alerts_url, x_scope_orgid_default, 
            x_scope_orgid_namespace_label):
    """
    Watch configmap resources for changes and update accordingly
    -and-
    Run a full one-way sync every n seconds (to catch missed events for instance after upgrading)
    """
    processes = []
    for resource in resources:
        for ns in namespace.split(','):
            proc = Process(target=_watch_resource_loop,
                           args=(function, label, label_value, rules_url, alerts_url, x_scope_orgid_default, 
                        x_scope_orgid_namespace_label, 
                                 ns, resource)
                           )
            proc.daemon = True
            proc.start()
            processes.append((proc, ns, resource))
            proc_sync = Process(target=_sync_loop,
                           args=(function, label, label_value, rules_url, alerts_url, x_scope_orgid_default, 
                        x_scope_orgid_namespace_label, 
                                 ns, resource)
                           )
            proc_sync.daemon = True
            proc_sync.start()
            processes.append((proc_sync, ns, resource))

    return processes
