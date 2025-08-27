#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import asdict

import httpx
import pytest
from helpers import (
    APP_NAME,
    RESOURCES,
    assert_request_returns_http_code,
    assert_tcp_connectivity,
    istio_k8s,
    validate_labels,
    validate_policy_exists,
)
from lightkube.core.client import Client
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_deploy_dependencies(ops_test: OpsTest):
    assert ops_test.model
    # Not the model name just an alias
    await ops_test.track_model("istio-system", model_name=f"{ops_test.model.name}-istio-system")
    istio_system_model = ops_test.models.get("istio-system")
    assert istio_system_model

    await istio_system_model.model.deploy(**asdict(istio_k8s))
    await istio_system_model.model.wait_for_idle(
        [istio_k8s.application_name], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, istio_beacon_charm):
    assert ops_test.model
    await ops_test.model.deploy(
        istio_beacon_charm, resources=RESOURCES, application_name=APP_NAME, trust=True
    )
    await ops_test.model.wait_for_idle(
        [APP_NAME], status="active", timeout=1000, raise_on_error=False
    )


async def test_istio_beacon_is_on_the_mesh(ops_test: OpsTest):
    """Test that the istio-beacon is on the mesh."""
    assert ops_test.model
    c = Client()
    beacon_pod = c.get(Pod, name=f"{APP_NAME}-0", namespace=ops_test.model.name)

    # Istio adds the following annotation to and pods on the mesh
    assert beacon_pod.metadata is not None
    assert beacon_pod.metadata.annotations is not None
    assert beacon_pod.metadata.annotations.get("ambient.istio.io/redirection", None) == "enabled"


@pytest.mark.abort_on_fail
async def test_mesh_config(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.applications[APP_NAME].set_config({"model-on-mesh": "true"})
    await ops_test.model.wait_for_idle(
        [APP_NAME], status="active", timeout=1000, raise_on_error=False
    )
    await validate_labels(ops_test, APP_NAME, should_be_present=True)
    validate_policy_exists(
        ops_test, f"{APP_NAME}-{ops_test.model.name}-policy-all-sources-modeloperator"
    )

    await ops_test.model.applications[APP_NAME].set_config({"model-on-mesh": "false"})
    await ops_test.model.wait_for_idle(
        [APP_NAME], status="active", timeout=1000, raise_on_error=False
    )
    await validate_labels(ops_test, APP_NAME, should_be_present=False)
    with pytest.raises(httpx.HTTPStatusError):
        validate_policy_exists(
            ops_test, f"{APP_NAME}-{ops_test.model.name}-policy-all-sources-modeloperator"
        )


# TODO: use pytest-dependency instead of relying on test evaluation order
@pytest.mark.abort_on_fail
async def test_deploy_service_mesh_apps(ops_test: OpsTest, service_mesh_tester):
    """Deploy the required tester apps onto the test model required for testing service mesh relation.

    This step deploys the tester apps and adds required relation between the testers and the
    istio beacon. This step must run before testing the service mesh relation. This step is branched
    off as the service mesh relation test is a parametrized test that needs to run multiple times without
    having to redeploy the tester apps.
    """
    assert ops_test.model
    # Deploy tester charms
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}
    # Applications that will be given authorization policies
    # receiver1 require trust because the service-mesh library interacts with k8s objects.
    await ops_test.model.deploy(
        service_mesh_tester,
        application_name="receiver1",
        resources=resources,
        trust=True,
    )
    await ops_test.model.deploy(
        service_mesh_tester,
        application_name="sender1",
        resources=resources,
        trust=True,
        config={
            "restrict-cross-unit-communication": "true",
        },
    )
    await ops_test.model.deploy(
        service_mesh_tester,
        application_name="sender2",
        resources=resources,
        trust=True,
    )
    await ops_test.model.deploy(
        service_mesh_tester,
        application_name="sender3",
        resources=resources,
        trust=True,
    )

    await ops_test.model.add_relation("receiver1:service-mesh", APP_NAME)
    await ops_test.model.add_relation("sender1:service-mesh", APP_NAME)
    await ops_test.model.add_relation("sender2:service-mesh", APP_NAME)
    await ops_test.model.add_relation("receiver1:inbound", "sender1:outbound")
    await ops_test.model.add_relation("receiver1:inbound-unit", "sender2:outbound")
    await ops_test.model.wait_for_idle(
        [
            APP_NAME,
            "receiver1",
            "sender1",
            "sender2",
            "sender3"
        ],
        raise_on_error=False,
    )


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("model_on_mesh", [True, False])
async def test_service_mesh_relation(ops_test: OpsTest, model_on_mesh):
    """Test the if the service mesh relation correctly puts the tester applications on mesh and opens restricts traffic as expected.

    The test sets `auto-join-mesh` for the tester charm based on the `model_on_mesh` parameter.  So:
    * when `model_on_mesh=True` we set `auto-join-mesh=False` to test that the model has subscribed the apps
    * when `model_on_mesh=False` we set `auto-join-mesh=True` to test that the apps have subscribed themselves
    """
    assert ops_test.model
    # Configure model-on-mesh based on parameter
    await ops_test.model.applications[APP_NAME].set_config({"model-on-mesh": str(model_on_mesh).lower()})
    # Wait for the mesh configuration for this model to be applied
    await ops_test.model.wait_for_idle([APP_NAME], raise_on_error=False)

    # configure auto-join for the apps based on model_on_mesh
    await ops_test.model.applications["receiver1"].set_config({"auto-join-mesh": str(not model_on_mesh).lower()})
    await ops_test.model.applications["sender1"].set_config({"auto-join-mesh": str(not model_on_mesh).lower()})
    await ops_test.model.applications["sender2"].set_config({"auto-join-mesh": str(not model_on_mesh).lower()})
    await ops_test.model.wait_for_idle(
        [
            APP_NAME,
            "receiver1",
            "sender1",
            "sender2",
            "sender3",
        ],
        raise_on_error=False,
    )

    # Assert that communication is correctly controlled via AppPolicy
    # sender1/0 can talk to receiver service on any combination of:
    # * port: [8080, 8081]
    # * path: [/foo, /bar/]
    # * method: [GET, POST]
    # but not the receiver workload or others
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender1/0",
        "http://receiver1:8080/foo",
        code=200,
    )
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender1/0",
        "http://receiver1:8081/foo",
        code=200,
    )
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender1/0",
        "http://receiver1:8080/bar/",
        code=200,
    )
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender1/0",
        "http://receiver1:8080/foo",
        method="post",
        code=200,
    )
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender1/0",
        "http://receiver1:8080/foo",
        method="delete",
        code=403,
    )
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender1/0",
        f"http://receiver1-0.receiver1-endpoints.{ops_test.model.name}.svc.cluster.local:8080/foo",
        code=1, # connection to the workload will be refused
    )

    # Assert that communication is correctly controlled via UnitPolicy
    # sender2/0 can talk to receiver workload on any route and any method.
    # but not to the receiver service or others
    # Connection to the service is not denied by default in the current istio-beacon design. It is denied here
    # because of the existence of AppPolicy above.
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender2/0",
        "http://receiver1:8080/foo",
        code=403,
    )
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender2/0",
        f"http://receiver1-0.receiver1-endpoints.{ops_test.model.name}.svc.cluster.local:8080/foo",
        code=200,
    )
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender2/0",
        f"http://receiver1-0.receiver1-endpoints.{ops_test.model.name}.svc.cluster.local:8080/foo",
        method="delete",
        code=200,
    )
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender2/0",
        f"http://receiver1-0.receiver1-endpoints.{ops_test.model.name}.svc.cluster.local:8083/foo",
        method="delete",
        code=1,
    )


    # other service accounts should get a 403 error if model on mesh else should raise an exit code 1 as connection will be refused
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender3/0",
        "http://receiver1:8080/foo",
        code=403 if model_on_mesh else 1,
    )
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender3/0",
        f"http://receiver1-0.receiver1-endpoints.{ops_test.model.name}.svc.cluster.local:8080/foo",
        code=1, # connection to the workload will be refused
    )


@pytest.mark.abort_on_fail
async def test_service_mesh_consumer_scaling(ops_test: OpsTest):
    """Tests if the ServiceMeshConsumer class allows the consumer app to scale without errors.

    Note: This test is stateful and will leave the sender1 and sender2 deployment at a scale of 2.
    """
    assert ops_test.model
    await ops_test.model.applications["sender1"].scale(2)
    await ops_test.model.wait_for_idle(
        ["sender1"],
        status="active",
        timeout=200,
        raise_on_error=False,
    )

    await ops_test.model.applications["sender2"].scale(2)
    await ops_test.model.wait_for_idle(
        ["sender2"],
        status="active",
        timeout=200,
        raise_on_error=False,
    )


@pytest.mark.abort_on_fail
async def test_cross_unit_communication_in_scaled_service_mesh_consumer(ops_test: OpsTest):
    """Tests if the units in the scaled service mesh consumer is allowed to talk to each other based on the config."""
    assert ops_test.model

    # sender1 configured explicitly to restrict cross unit communication should not allow communication between units
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender1/0",
        f"http://sender1-1.sender1-endpoints.{ops_test.model.name}.svc.cluster.local:8080/foo",
        code=1,
    )

    # sender2 with default config should allow cross unit communication
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender2/0",
        f"http://sender2-1.sender2-endpoints.{ops_test.model.name}.svc.cluster.local:8080/foo",
        code=200,
    )


@pytest.mark.abort_on_fail
async def test_modeloperator_rule(ops_test: OpsTest, service_mesh_tester):
    """Test that we allow anything, even off-mesh workloads, to talk to the modeloperator in beacon's namespace."""
    assert ops_test.model
    # Ensure model is on mesh
    await ops_test.model.applications[APP_NAME].set_config({"model-on-mesh": "true"})
    await ops_test.track_model(
        "off-mesh-model", model_name=f"{ops_test.model.name}-off-mesh-model"
    )
    omm = ops_test.models.get("off-mesh-model")
    assert omm
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}
    await omm.model.deploy(
        service_mesh_tester, application_name="sender", resources=resources, trust=True
    )
    await omm.model.wait_for_idle(status="active")
    # Test TCP connectivity to modeloperator - we only care that the network connection can be established,
    # proving that the service mesh allows traffic from off-mesh workloads to the modeloperator
    assert_tcp_connectivity(
        omm.model.name, "sender/0", f"modeloperator.{ops_test.model.name}.svc.cluster.local", 17071
    )
