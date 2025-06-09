#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from lightkube.core.client import Client
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.core_v1 import Namespace
from pytest_operator.plugin import OpsTest

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
