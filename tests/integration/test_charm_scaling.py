# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from dataclasses import asdict

import pytest
from charmed_service_mesh_helpers import charm_kubernetes_label
from helpers import (
    APP_NAME,
    RESOURCES,
    get_hpa,
    istio_k8s,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

TESTER_APP_NAME = "tester"


@pytest.mark.abort_on_fail
async def test_deploy_dependencies(ops_test: OpsTest):
    assert ops_test.model
    # Not the model name just an alias
    await ops_test.track_model(
        "istio-system",
        model_name=f"{ops_test.model.name}-istio-system"
    )
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
        istio_beacon_charm,
        resources=RESOURCES,
        application_name=APP_NAME,
        trust=True,
    )
    await ops_test.model.wait_for_idle(
        [APP_NAME],
        status="active",
        timeout=1000,
        raise_on_error=False,
    )


@pytest.mark.abort_on_fail
async def test_service_mesh_relation(ops_test: OpsTest, service_mesh_tester):
    """Adds a tester charm and creates a service mesh relation between beacon and the tester charm.

    The subsequent scaling test makes sure that the scaling up/down happens successfully with the service mesh relation in place.
    """
    assert ops_test.model
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}
    await ops_test.model.deploy(
        service_mesh_tester,
        application_name=TESTER_APP_NAME,
        resources=resources,
        trust=True,
    )
    await ops_test.model.wait_for_idle(
        ["tester"],
        status="active",
        timeout=1000,
    )
    await ops_test.model.add_relation("tester:service-mesh", APP_NAME)


@pytest.mark.abort_on_fail
@pytest.mark.parametrize(
    "n_units",
    (
        # Scale up from 1 to 3
        3,
        # Scale down to 2
        2,
    ),
)
async def test_waypoint_scaling(ops_test: OpsTest, n_units):
    """Tests that, when the application is scaled, the HPA managing replicas on the Waypoint is scaled too.

    This test also makes sure that the scaling does not affect any existing service mesh relation.s
    Note: This test is stateful and will leave the deployment at a scale of 2.
    """
    assert ops_test.model
    await ops_test.model.applications[APP_NAME].scale(n_units)
    await ops_test.model.wait_for_idle(
        [APP_NAME],
        status="active",
        timeout=2000,
        raise_on_error=False,
    )

    waypoint_name = charm_kubernetes_label(
        model_name=ops_test.model.name,
        app_name=APP_NAME,
        suffix="-waypoint",
        separator="-",
        max_length=63
    )
    waypoint_hpa = await get_hpa(ops_test.model.name, waypoint_name)
    assert waypoint_hpa is not None
    assert waypoint_hpa.spec.minReplicas == n_units  # pyright: ignore[reportOptionalMemberAccess]
    assert waypoint_hpa.spec.maxReplicas == n_units  # pyright: ignore[reportOptionalMemberAccess]

    assert await wait_for_hpa_current_replicas(
        ops_test.model.name, waypoint_name, n_units
    ), f"Expected currentReplicas to be {n_units}, got {waypoint_hpa.status.currentReplicas}"  # pyright: ignore[reportOptionalMemberAccess]


@pytest.mark.abort_on_fail
async def wait_for_hpa_current_replicas(
    namespace, hpa_name, expected_replicas, retries=10, delay=10
):
    for _ in range(retries):
        # freshly grab the hpa, but no need to assert its existence as that should be checked by the caller of this method
        waypoint_hpa = await get_hpa(namespace, hpa_name)
        if waypoint_hpa.status.currentReplicas == expected_replicas:  # pyright: ignore[reportOptionalMemberAccess]
            return True
        await asyncio.sleep(delay)
    return False
