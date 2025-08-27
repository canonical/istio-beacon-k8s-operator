#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import sh
import yaml
from lightkube.core.client import Client
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.autoscaling_v2 import HorizontalPodAutoscaler
from lightkube.resources.core_v1 import Namespace
from pytest_operator.plugin import OpsTest
from tenacity import (
    retry,
    stop_after_delay,
    wait_exponential,
)

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
SENDER = "sender"
RECEIVER = "receiver"
RESOURCES = {
    "metrics-proxy-image": METADATA["resources"]["metrics-proxy-image"]["upstream-source"],
}



@dataclass
class CharmDeploymentConfiguration:
    entity_url: str  # aka charm name or local path to charm
    application_name: str
    channel: str
    trust: bool
    config: Optional[dict] = None


istio_k8s = CharmDeploymentConfiguration(
    entity_url="istio-k8s", application_name="istio-k8s", channel="2/edge", trust=True
)


AuthPolicy = create_namespaced_resource(
    "security.istio.io", "v1", "AuthorizationPolicy", "authorizationpolicies"
)


async def get_hpa(namespace: str, hpa_name: str) -> Optional[HorizontalPodAutoscaler]:
    """Retrieve the HPA resource so we can inspect .spec and .status directly.

    Args:
        namespace: Namespace of the HPA resource.
        hpa_name: Name of the HPA resource.

    Returns:
        The HorizontalPodAutoscaler object or None if not found / on error.
    """
    try:
        c = Client()
        return c.get(HorizontalPodAutoscaler, namespace=namespace, name=hpa_name)
    except Exception as e:
        logger.error("Error retrieving HPA %s: %s", hpa_name, e, exc_info=True)
        return None


async def validate_labels(ops_test: OpsTest, app_name: str, should_be_present: bool):
    """Validate the presence or absence of specific labels in the namespace."""
    assert ops_test.model_name
    client = Client()

    namespace_name = ops_test.model_name
    namespace = client.get(Namespace, namespace_name)

    expected_labels = {
        "istio.io/use-waypoint": f"{namespace_name}-{app_name}-waypoint",
        "istio.io/dataplane-mode": "ambient",
        "charms.canonical.com/istio.io.waypoint.managed-by": f"{namespace_name}.{app_name}",
    }

    for label, expected_value in expected_labels.items():
        assert namespace.metadata
        assert namespace.metadata.labels
        actual_value = namespace.metadata.labels.get(label)
        if should_be_present:
            assert actual_value == expected_value, f"Label {label} is missing or incorrect."
        else:
            assert actual_value is None, f"Label {label} should have been removed."


def validate_policy_exists(ops_test: OpsTest, policy_name: str):
    assert ops_test.model
    client = Client()
    client.get(AuthPolicy, policy_name, namespace=ops_test.model.name)


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(120), reraise=True
)
def assert_request_returns_http_code(
    model: str, source_unit: str, target_url: str, method: str = "get", code: int = 200
):
    """Get the status code for a request from a source unit to a target URL on a given method.

    Note that if the request fails (ex: python script raises an exception) the exit code will be returned.
    """
    logger.info(f"Checking {source_unit} -> {target_url} on {method}")
    try:
        resp = sh.juju.ssh(  # pyright: ignore
            "-m",
            model,
            source_unit,
            f'curl -X {method.upper()} -s -o /dev/null -w "%{{http_code}}" {target_url}',
            _return_cmd=True,
        )
        returned_code = int(str(resp).strip())
    except sh.ErrorReturnCode as e:
        logger.warning(f"Got exit code {e.exit_code} executing sh.juju.ssh")
        logger.warning(f"STDOUT: {e.stdout}")
        logger.warning(f"STDERR: {e.stderr}")
        returned_code = e.exit_code

    logger.info(
        f"Got {returned_code} for {source_unit} -> {target_url} on {method} - expected {code}"
    )

    assert (
        returned_code == code
    ), f"Expected {code} but got {returned_code} for {source_unit} -> {target_url} on {method}"


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(120), reraise=True
)
def assert_tcp_connectivity(
    model: str, source_unit: str, host: str, port: int, inverse_check: bool = False
):
    """Test TCP connectivity from source unit to target host:port using /dev/tcp.

    Args:
        model: Juju model name
        source_unit: Source unit name (e.g., "sender/0")
        host: Target hostname or IP
        port: Target port number
        inverse_check: Pass if the connection fails
    """
    cmd = f'timeout 5 bash -c "echo >/dev/tcp/{host}/{port}"'

    try:
        _ = sh.juju.ssh(  # pyright: ignore
            "-m",
            model,
            source_unit,
            cmd,
            _return_cmd=True,
        )
        exit_code = 0
        logger.info(f"TCP connectivity test succeeded: {source_unit} -> {host}:{port}")
    except sh.ErrorReturnCode as e:
        exit_code = e.exit_code
        logger.info(f"TCP connectivity test failed with exit code {exit_code}: {source_unit} -> {host}:{port}")

    if not inverse_check:
        assert exit_code == 0, f"Expected TCP connection to {host}:{port} to succeed, but got exit code {exit_code}"
    else:
        assert exit_code != 0, f"Expected TCP connection to {host}:{port} to fail, but it succeeded"
