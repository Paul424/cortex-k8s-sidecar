

[![GitHub release (latest SemVer)](https://img.shields.io/github/v/release/Paul424/cortex-k8s-sidecar?style=flat)](https://github.com/Paul424/cortex-k8s-sidecar/releases)
[![Release](https://github.com/Paul424/cortex-k8s-sidecar/actions/workflows/release.yaml/badge.svg)](https://github.com/Paul424/cortex-k8s-sidecar/actions/workflows/release.yaml)
[![Docker Pulls](https://img.shields.io/docker/pulls/Paul424/cortex-k8s-sidecar.svg?style=flat)](https://hub.docker.com/r/paul424/cortex-k8s-sidecar/)
![Docker Image Size (latest semver)](https://img.shields.io/docker/image-size/paul424/cortex-k8s-sidecar)
# What?

Cortex-k8s-sidecar is based on [kiwigrid/k8s-sidecar](https://github.com/kiwigrid/k8s-sidecar) (a sidecar to mount configmap/secret fields into a pod). This sidecar implementation however doesn't make the fields available over the filesystem, but posts the content to the Cortex API directly.

# Why?

This sidecar improves the original [kiwigrid/k8s-sidecar](https://github.com/kiwigrid/k8s-sidecar) on following aspects:
1. [kiwigrid/k8s-sidecar](https://github.com/kiwigrid/k8s-sidecar) only works with the `local` storage backend while this project allows to use the s3 storage backend for the ruler and alertmanager. This also enables the use of sharding for the ruler.
2. [kiwigrid/k8s-sidecar](https://github.com/kiwigrid/k8s-sidecar) requires rules configmaps to be tagged with a label (for instance `cortex_rules: "1"`). That is difficult to integrate with the [prometheus-operator](https://github.com/prometheus-operator/prometheus-operator) which watches PrometheusRule resources and writes the rules to configmaps that don't support custom labels (as per operator configuration). This project however applies an additional filter based on the resource naming (`prometheus-<name>-rulefiles-<postfix>`) so label filtering can take place simply on the hardcoded label (`managed-by: prometheus-operator`).
3. [kiwigrid/k8s-sidecar](https://github.com/kiwigrid/k8s-sidecar) required the x-scope-orgid to be specified (implicitly) in the annotation `k8s-sidecar-target-directory` (where the `x-scope-orgid` is the name of the directory). This project however takes the `x-scope-orgid` from a configurable namespace label; as organizations/tenants are typically assigned a namespace in which rules and alerts are created this is a much simpler setup to integrate.

# Images

Images are available at:

- [docker.io/paul424/cortex-k8s-sidecar](https://hub.docker.com/r/paul424/cortex-k8s-sidecar)

All are identical multi-arch images built for `amd64`, `arm64`, `arm/v7`, `ppc64le` and `s390x`

# Features

- Support for configmaps only
- Filter based on label
- Update/Delete on change of configmap

# Build

```shell
docker build --network=host -t cortex-k8s-sidecar:0.1 .
```

## Configuration Environment Variables

| name                       | description                                                                                                                                                                                                                                                                                                                         | required | default                                   | type    |
|----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|-------------------------------------------|---------|
| `FUNCTION`                   | Specifies the Cortex function to push configuration for; either `rules` or `alerts`. | false    | `rules`                                         | string  |
| `LABEL`                      | Label that should be used for filtering                                                                                                                                                                                                                                                                                             | true     | -                                         | string  |
| `LABEL_VALUE`                | The value for the label you want to filter your resources on. Don't set a value to filter by any value                                                                                                                                                                                                                              | false    | -                                         | string  |
| `X_SCOPE_ORGID_DEFAULT`    | The default x-scope-orgid to use                                                                                                                                                                                                                                | false    | `system`                                  | string  |
| `X_SCOPE_ORGID_NAMESPACE_LABEL`              | The namespace label that contains the x-scope-orgid. Notice when the label isn't found on the namespace, the value of `X_SCOPE_ORGID_DEFAULT` is used.                                                                                  | false    | -                                         | string  |
| `RULES_URL`              | The Cortex ruler endpoint , for instance `http://cortex-ruler.cortex.svc.cluster.local:8080/api/v1/rules`                                                                                                                                   | true    | -                                         | string  |
| `ALERTS_URL`              | The Cortex alertmanager endpoint , for instance `http://cortex-alertmanager.cortex.svc.cluster.local:8080/api/v1/alerts`                                                                                                                                  | true    | -                                         | string  |
| `NAMESPACE`                | Comma separated list of namespaces. If specified, the sidecar will search for config-maps inside these namespaces. It's also possible to specify `ALL` to search in all namespaces.                                                                                                                                                 | false    | namespace in which the sidecar is running | string  |
| `KUBECONFIG`               | if this is given and points to a file or `~/.kube/config` is mounted k8s config will be loaded from this file, otherwise "incluster" k8s configuration is tried.                                                                                                                                                                    | false    | -                                         | string  |
| `LOG_LEVEL`                | Set the logging level. (DEBUG, INFO, WARN, ERROR, CRITICAL)                                                                                                                                                                                                                                                                         | false    | `INFO`                                    | string  |
| `LOG_FORMAT`               | Set a log format. (JSON or LOGFMT)                                                                                                                                                                                                                                                                                                  | false    | `JSON`                                    | string  |
| `LOG_TZ`                   | Set the log timezone. (LOCAL or UTC)
