#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import sh
from lightkube.core.client import Client
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.core_v1 import Namespace
from pytest_operator.plugin import OpsTest
from tenacity import (
    retry,
    stop_after_delay,
    wait_exponential,
)

logger = logging.getLogger(__name__)

AuthPolicy = create_namespaced_resource(
    "security.istio.io", "v1", "AuthorizationPolicy", "authorizationpolicies"
)


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
            f'python3 -c "import requests; resp = requests.{method}(\\"{target_url}\\"); print(resp.status_code)"',
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
