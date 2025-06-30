#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests that istio-beacon creates AuthorizationPolicies that enable traffic for charms related cross-model."""

from dataclasses import asdict

import pytest
from helpers import (
    APP_NAME,
    RECEIVER,
    RESOURCES,
    SENDER,
    assert_request_returns_http_code,
    istio_k8s,
)
from pytest_operator.plugin import ModelState, OpsTest


@pytest.fixture(scope="module")
async def istio_system_model(ops_test: OpsTest) -> ModelState:
    """Create and return a model for istio_system."""
    assert ops_test.model
    await ops_test.track_model("istio-system", model_name=f"{ops_test.model.name}-istio-system")
    istio_system_model = ops_test.models.get("istio-system")
    assert istio_system_model
    return istio_system_model


@pytest.fixture(scope="module")
async def sender_model(ops_test: OpsTest) -> ModelState:
    """Create and return a model for the sender application."""
    assert ops_test.model
    await ops_test.track_model(SENDER, model_name=f"{ops_test.model.name}-{SENDER}")
    istio_system_model = ops_test.models.get(SENDER)
    assert istio_system_model
    return istio_system_model


@pytest.fixture(scope="module")
async def receiver_model(ops_test: OpsTest) -> ModelState:
    """Create and return a model for the receiver application."""
    assert ops_test.model
    await ops_test.track_model(RECEIVER, model_name=f"{ops_test.model.name}-{RECEIVER}")
    istio_system_model = ops_test.models.get(RECEIVER)
    assert istio_system_model
    return istio_system_model


@pytest.mark.abort_on_fail
async def test_deploy_environment(
    ops_test: OpsTest,
    sender_model: ModelState,
    receiver_model: ModelState,
    istio_system_model: ModelState,
    istio_beacon_charm,
    service_mesh_tester,
):
    """Deploy the istio-k8s, two models for sender and receiver, and the istio-beacon charm in each model.

    Asserts that these come to active, but does not assert that policies are created correctly.
    """
    # Deploy the istio-k8s charm in the istio-system model
    await istio_system_model.model.deploy(**asdict(istio_k8s))
    await istio_system_model.model.wait_for_idle(
        [istio_k8s.application_name], status="active", timeout=1000
    )

    # Deploy the istio-beacon and sender in the sender models
    await sender_model.model.deploy(
        istio_beacon_charm, resources=RESOURCES, application_name=APP_NAME, trust=True, config={"model-on-mesh": "true"}
    )
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}
    await sender_model.model.deploy(
        service_mesh_tester, application_name=SENDER, resources=resources, trust=True
    )

    # Deploy the istio-beacon and receiver in the receiver models
    await receiver_model.model.deploy(
        istio_beacon_charm, resources=RESOURCES, application_name=APP_NAME, trust=True, config={"model-on-mesh": "true"}
    )
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}
    await receiver_model.model.deploy(
        service_mesh_tester, application_name=RECEIVER, resources=resources, trust=True
    )

    # Establish the cross-model relations
    outbound = "outbound"
    cmr = "require-cmr-mesh"
    # For some reason, using model.create_offer is flaky.  We observe in beacon logs:
    # "ops.model.ModelError: ERROR read tcp 10.1.253.231:37698->10.152.183.160:17070: read: connection reset by peer"
    # The beacon charm itself recovers correctly after this, but when this occurs it causes the model.create_offer()
    # call to fail.  If we use the juju CLI instead, we don't get this premature failure.
    # await sender_modelstate.model.create_offer(
    #     endpoint=relation,
    #     offer_name=relation,
    #     application_name=SENDER,
    # )
    # Offer everything that the receiver needs to consume in a single offer
    await ops_test.juju(
        "offer",
        f"{sender_model.model.name}.{SENDER}:{outbound},{cmr}",
    )
    await ops_test.juju(
        "consume",
        "--model", receiver_model.model.name,
        f"admin/{sender_model.model.name}.{SENDER}"
    )
    await receiver_model.model.add_relation(
        f"{SENDER}:{outbound}", f"{RECEIVER}:inbound"
    )
    await receiver_model.model.add_relation(
        f"{SENDER}:{cmr}", f"{RECEIVER}:provide-cmr-mesh"
    )

    # Establish the relation between the istio-beacon and the receiver
    await receiver_model.model.add_relation(
        APP_NAME, RECEIVER,
    )

    # Wait for everything to settle
    await sender_model.model.wait_for_idle(
        [APP_NAME, SENDER], status="active", timeout=1000, raise_on_error=False
    )
    await receiver_model.model.wait_for_idle(
        [APP_NAME, RECEIVER], status="active", timeout=1000, raise_on_error=False
    )


@pytest.mark.parametrize(
    "path, code",
    [
        # GET request to /foo and /bar/ should succeed because the receiver requests they're open
        ("/foo", 200),
        ("/bar/", 200),
        # GET request to /baz should fail because the receiver does not request it
        ("/nonexistent", 403),  # GET request to a non-existent path should fail
    ]
)
def test_sender_can_talk_to_receiver(
    sender_model: ModelState,
    receiver_model: ModelState,
    path: str,
    code: int,
):
    """Test that the single related sender can talk to the receiver at the expected paths."""
    assert_request_returns_http_code(
        sender_model.model.name, f"{SENDER}/0", f"http://{RECEIVER}.{receiver_model.model.name}:8080{path}", code=code
    )
