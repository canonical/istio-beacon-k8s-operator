#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.testing import Harness

from charm import IstioBeaconCharm
from lib.charms.istio_beacon_k8s.v0.service_mesh import (
    Endpoint,
    MeshPolicy,
    PolicyTargetType,
    _generate_network_policy_name,
)


@pytest.fixture()
def harness():
    harness = Harness(IstioBeaconCharm)
    harness.set_model_name("istio-system")
    yield harness
    harness.cleanup()


@pytest.mark.parametrize(
    "beacon_name, beacon_namespace, mesh_policy, expected_name",
    [
        # basic working case
        (
            "beaconApp",
            "beaconNamespace",
            MeshPolicy(
                source_app_name="senderApp",
                source_namespace="senderNamespace",
                target_app_name="targetApp",
                target_namespace="targetNamespace",
                target_service=None,
                target_type=PolicyTargetType.app,
                endpoints=[
                    Endpoint(hosts=["host1"], ports=[80], methods=["GET"], paths=["/path1"])  # type: ignore
                ],
            ),
            # Note: if this test fails because the hash has changed, that means upgrading from a previous version to
            # this one will result in a delete/recreate of all policies.  Decide if that is acceptable.
            "beaconApp-beaconNamespace-policy-senderApp-senderNamespace-targetApp-994417d1",
        ),
        # case with target service, multiple endpoints
        (
            "beaconApp",
            "beaconNamespace",
            MeshPolicy(
                source_app_name="senderApp",
                source_namespace="senderNamespace",
                target_app_name="targetApp",
                target_namespace="targetNamespace",
                target_service="my-service",
                target_type=PolicyTargetType.app,
                endpoints=[
                    Endpoint(hosts=["host1"], ports=[80], methods=["GET"], paths=["/path1"]),  # type: ignore
                    Endpoint(hosts=["host2"], ports=[80], methods=["GET"], paths=["/path1"]),  # type: ignore
                ],
            ),
            # Note: if this test fails because the hash has changed, that means upgrading from a previous version to
            # this one will result in a delete/recreate of all policies.  Decide if that is acceptable.
            "beaconApp-beaconNamespace-policy-senderApp-senderNamespace-targetApp-2840f76e",
        ),
        # case with truncation
        (
            "beaconApp012345678901234567890123456789012345678901234567890123",
            "beaconNamespace678901234567890123456789012345678901234567890123",
            MeshPolicy(
                source_app_name="senderApp012345678901234567890123456789012345678901234567890123",
                source_namespace="senderNamespace678901234567890123456789012345678901234567890123",
                target_app_name="targetApp012345678901234567890123456789012345678901234567890123",
                target_namespace="targetNamespace678901234567890123456789012345678901234567890123",
                target_service="my-service",
                target_type=PolicyTargetType.app,
                endpoints=[
                    Endpoint(hosts=["host1"], ports=[80], methods=["GET"], paths=["/path1"]),  # type: ignore
                    Endpoint(hosts=["host2"], ports=[80], methods=["GET"], paths=["/path1"]),  # type: ignore
                ],
            ),
            # Note: if this test fails because the hash has changed, that means upgrading from a previous version to
            # this one will result in a delete/recreate of all policies.  Decide if that is acceptable.
            "beaconApp012345678901234567890123456789012345678901234567890123-beaconNamespace678901234567890123456789012345678901234567890123-policy-senderApp012345678901234567890-senderNamespace678901234567890-targetApp012345678901234567890-ff03bbae",
        ),
    ],
)
def test_generate_authorization_policy_name(
    beacon_name, beacon_namespace, mesh_policy, expected_name, harness: Harness[IstioBeaconCharm]
):
    """Test the _generate_authorization_policy_name() method."""
    harness.set_model_name(beacon_namespace)
    harness.begin()
    charm = harness.charm
    charm.model.app.name = beacon_name

    name = _generate_network_policy_name(charm.app.name, charm.model.name, mesh_policy)
    assert name == expected_name
    assert len(name) <= 253  # 253 is the max length for a k8s resource name
