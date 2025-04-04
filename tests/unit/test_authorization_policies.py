# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import patch

import pytest
import scenario
from charms.istio_beacon_k8s.v0.service_mesh import Endpoint, MeshPolicy


@pytest.fixture()
def service_mesh_relation():
    yield scenario.Relation(
        "service-mesh",
        "service_mesh",
        remote_app_data={
            "policies": json.dumps(
                [
                    MeshPolicy(
                        source_app_name="source-app1",
                        source_namespace="source-namespace1",
                        target_app_name="target-app1",
                        target_namespace="target-namespace1",
                        target_service="my-service1",
                        endpoints=[
                            Endpoint(
                                hosts=["host1"],
                                ports=[80],
                                methods=["GET"],  # type: ignore
                                paths=["/path1"],
                            )
                        ],
                    ).model_dump(),
                    MeshPolicy(
                        source_app_name="source-app2",
                        source_namespace="source-namespace2",
                        target_app_name="target-app2",
                        target_namespace="target-namespace2",
                        # target_service="my-service2",  # omit, which should get the default of target app name
                        endpoints=[
                            Endpoint(
                                hosts=["host2"],
                                ports=[80],
                                methods=["GET"],  # type: ignore
                                paths=["/path2"],
                            )
                        ],
                    ).model_dump(),
                ]
            )
        },
    )


def test_get_authorization_policies_from_related_apps(
    istio_beacon_charm, istio_beacon_context, service_mesh_relation
):
    with istio_beacon_context(
        istio_beacon_context.on.update_status(),
        state=scenario.State(relations=[service_mesh_relation]),
    ) as manager:
        charm: istio_beacon_charm = manager.charm  # type: ignore
        mesh_info = charm._mesh.mesh_info()
        assert mesh_info[0].endpoints[0].hosts == ["host1"]
        assert mesh_info[1].endpoints[0].paths == ["/path2"]


@pytest.mark.disable_lightkube_client_autouse
def test_build_authorization_policies(
    istio_beacon_charm, istio_beacon_context, service_mesh_relation
):
    model_name = "my-model"
    with istio_beacon_context(
        istio_beacon_context.on.update_status(),
        state=scenario.State(
            relations=[service_mesh_relation], model=scenario.Model(name=model_name)
        ),
    ) as manager:
        charm: istio_beacon_charm = manager.charm  # type: ignore
        authorization_policies = charm._build_authorization_policies(charm._mesh.mesh_info())

        # Spot check the outputs
        assert authorization_policies[0]["metadata"].namespace == model_name
        assert authorization_policies[0]["spec"]["targetRefs"][0]["name"] == "my-service1"
        assert authorization_policies[1]["spec"]["rules"][0]["to"][0]["operation"]["paths"] == [
            "/path2"
        ]
        assert authorization_policies[1]["spec"]["targetRefs"][0]["name"] == "target-app2"


@pytest.mark.parametrize("create_authorization_policies", [True, False])
@patch("charm.IstioBeaconCharm._setup_proxy_pebble_service")
@patch("charm.IstioBeaconCharm._is_waypoint_deployment_ready", return_value=True)
@patch("charm.IstioBeaconCharm._get_waypoint_resource_manager")
@patch("charm.IstioBeaconCharm._get_authorization_policy_resource_manager")
def test_charm_creates_authorization_policies_on_relation_changed(
    mock_get_authorization_policy_resource_manager,
    _mock_get_waypoint_resource_manager,
    _mock_is_waypoint_deployment_ready,
    _mock_setup_proxy_pebble_service,
    create_authorization_policies,
    istio_beacon_charm,
    istio_beacon_context,
    service_mesh_relation,
    mock_lightkube_client,
):
    """Test that the charm config create_authorization_policies controls whether AuthorizationPolicies are created."""
    istio_beacon_context.run(
        istio_beacon_context.on.config_changed(),
        state=scenario.State(
            relations=[service_mesh_relation],
            leader=True,
            config={"manage-authorization-policies": create_authorization_policies},
        ),
    )

    # Assert that we have/haven't created the AuthorizationPolicies as expected
    reconciler = mock_get_authorization_policy_resource_manager.return_value.reconcile
    reconciler.assert_called_once()
    # reconciler accepts a list of AuthorizationPolicies as the first positional argument.
    if create_authorization_policies:
        # Assert that we have passed more than 0 AuthorizationPolicies in that list
        assert len(reconciler.call_args.args[0]) > 0
    else:
        # Assert that we have passed exactly 0 AuthorizationPolicies in that list
        assert len(reconciler.call_args.args[0]) == 0
