#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest
import yaml
from helpers import (
    assert_request_returns_http_code,
    istio_k8s,
    validate_labels,
    validate_policy_exists,
)
from lightkube.core.client import Client
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {
    "metrics-proxy-image": METADATA["resources"]["metrics-proxy-image"]["upstream-source"],
}


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
    )
    await ops_test.model.deploy(
        service_mesh_tester,
        application_name="sender2",
        resources=resources,
        trust=True,
    )

    await ops_test.model.add_relation("receiver1:service-mesh", APP_NAME)
    await ops_test.model.add_relation("sender1:service-mesh", APP_NAME)
    await ops_test.model.add_relation("receiver1:inbound", "sender1:outbound")
    await ops_test.model.wait_for_idle(
        [
            APP_NAME,
            "receiver1",
            "sender1",
            "sender2",
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
    # Do not set auto-join for sender2, as it is not part of the mesh anyway
    # await ops_test.model.applications["sender2"].set_config({"auto-join-mesh": str(not model_on_mesh).lower()})
    await ops_test.model.wait_for_idle(
        [
            APP_NAME,
            "receiver1",
            "sender1",
            "sender2",
        ],
        raise_on_error=False,
    )

    # Assert that communication is correctly controlled
    # sender/0 can talk to receiver on any combination of:
    # * port: [8080, 8081]
    # * path: [/foo, /bar/]
    # * method: [GET, POST]
    # but not others
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

    # other service accounts should get a 403 error if model on mesh else should raise an exit code 1 as connection will be refused
    assert_request_returns_http_code(
        ops_test.model.name,
        "sender2/0",
        "http://receiver1:8080/foo",
        code=403 if model_on_mesh else 1,
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
    # Return code is 400 because I do not know how to properly format an api call to the modeloperator. But we only
    # care that the request reached its destination.
    assert_request_returns_http_code(
        omm.model.name, "sender/0", f"http://modeloperator.{ops_test.model.name}:17071", code=400
    )
