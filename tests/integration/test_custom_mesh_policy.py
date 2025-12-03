#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for custom mesh policies using MeshPolicy and PRM."""

import logging

import pytest
from helpers import (
    APP_NAME,
    assert_request_returns_http_code,
    istio_k8s,
)
from jubilant import Juju, all_active
from lightkube.core.client import Client
from lightkube.generic_resource import create_namespaced_resource

logger = logging.getLogger(__name__)

# Create AuthorizationPolicy resource type
AuthPolicy = create_namespaced_resource(
    "security.istio.io", "v1", "AuthorizationPolicy", "authorizationpolicies"
)


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_dependencies(istio_juju: Juju):
    """Deploy istio-k8s in istio-system model."""
    status = istio_juju.status()
    assert istio_k8s.application_name in status.apps
    assert status.apps[istio_k8s.application_name].is_active


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deployment(juju: Juju, istio_beacon_charm, istio_beacon_resources):
    """Deploy istio-beacon-k8s charm."""
    juju.deploy(
        istio_beacon_charm,
        app=APP_NAME,
        resources=istio_beacon_resources,
        trust=True,
        config={"model-on-mesh": "true"},
    )
    juju.wait(
        lambda s: all_active(s, APP_NAME),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_wildcard_receiver(juju: Juju, service_mesh_tester):
    """Deploy a receiver with wildcard policy enabled.

    This receiver will use the PolicyResourceManager to create a wildcard MeshPolicy
    that allows traffic from any source.
    """
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}

    juju.deploy(
        service_mesh_tester,
        app="wildcard-receiver",
        resources=resources,
        trust=True,
        config={
            "auto-join-mesh": "true",
            "use-wildcard-policy": "true",
        },
    )

    juju.integrate("wildcard-receiver:service-mesh", APP_NAME)

    juju.wait(
        lambda s: all_active(s, APP_NAME, "wildcard-receiver"),
        timeout=600,
        delay=5,
        successes=3,
    )


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_senders(juju: Juju, service_mesh_tester):
    """Deploy authorized and unauthorized senders."""
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}

    # Deploy authorized sender with relation to wildcard-receiver
    juju.deploy(
        service_mesh_tester,
        app="authorized-sender",
        resources=resources,
        trust=True,
        config={
            "auto-join-mesh": "true",
        },
    )

    # Deploy unauthorized sender without relation to wildcard-receiver
    juju.deploy(
        service_mesh_tester,
        app="unauthorized-sender",
        resources=resources,
        trust=True,
        config={
            "auto-join-mesh": "true",
        },
    )

    juju.integrate("authorized-sender:service-mesh", APP_NAME)
    juju.integrate("unauthorized-sender:service-mesh", APP_NAME)
    juju.integrate("wildcard-receiver:inbound", "authorized-sender:outbound")

    juju.wait(
        lambda s: all_active(s, APP_NAME, "authorized-sender", "unauthorized-sender", "wildcard-receiver"),
        timeout=600,
        delay=5,
        successes=3,
    )


@pytest.mark.abort_on_fail
def test_wildcard_policy_exists(juju: Juju):
    """Verify that the wildcard authorization policy was created.

    The wildcard policy should:
    - Have "any-source" and "any-namespace" in its name
    - Target the wildcard-receiver application
    - Be present in the model namespace
    """
    model_name = juju.model
    assert model_name is not None

    client = Client()
    policies = list(client.list(AuthPolicy, namespace=model_name))

    # Find wildcard policy for wildcard-receiver
    # Policy name format: {app_name}-{model_name}-policy-any-source-any-namespace-{target}-{hash}
    wildcard_policies = [
        p
        for p in policies
        if p.metadata
        and p.metadata.name
        and "wildcard-receiver" in p.metadata.name
        and "any-source" in p.metadata.name
        and "any-namespace" in p.metadata.name
    ]

    assert len(wildcard_policies) > 0, (
        f"Expected to find at least one wildcard policy for wildcard-receiver "
        f"in namespace {model_name}, but found none. "
        f"Available policies: {[p.metadata.name for p in policies if p.metadata]}"
    )

    policy = wildcard_policies[0]
    logger.info(f"Found wildcard policy: {policy.metadata.name}")  # type: ignore[union-attr]

    # Verify the policy has no 'from' clause
    spec = policy.spec  # type: ignore[attr-defined]
    rules = spec.get("rules", [])  # type: ignore
    assert len(rules) > 0, "Expected at least one rule in the authorization policy"

    from_clause = rules[0].get("from")
    assert from_clause is None, (
        f"Expected wildcard policy to have no 'from' clause (any source allowed), "
        f"but found: {from_clause}"
    )

    logger.info("Verified wildcard policy has no 'from' clause (allows any source)")


@pytest.mark.abort_on_fail
def test_wildcard_policy_allows_both_authorized_and_unauthorized_access(juju: Juju):
    """Test that the wildcard policy allows access from both authorized and unauthorized sources.

    This validates that:
    - authorized-sender (with explicit relation) can access wildcard-receiver
    - unauthorized-sender (no explicit relation) can also access wildcard-receiver
    """
    # Test authorized sender can access wildcard-receiver
    assert_request_returns_http_code(
        juju,
        "authorized-sender/0",
        "http://wildcard-receiver:8080/",
        code=200,
    )
    logger.info("Verified authorized sender can access wildcard-receiver")

    # Test unauthorized sender can also access wildcard-receiver
    assert_request_returns_http_code(
        juju,
        "unauthorized-sender/0",
        "http://wildcard-receiver:8080/",
        code=200,
    )
    logger.info("Verified unauthorized sender can access wildcard-receiver")

