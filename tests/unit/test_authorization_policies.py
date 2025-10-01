# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import patch

import pytest
import scenario
from charms.istio_beacon_k8s.v0.service_mesh import (
    Endpoint,
    MeshPolicy,
    PolicyTargetType,
    _build_policy_resources_istio,
)


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
                        target_type=PolicyTargetType.app,
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
                        target_type=PolicyTargetType.app,
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


@pytest.mark.parametrize(
    "mesh_policies,expected",
    [
        (
            (
                MeshPolicy(
                    source_app_name="source-app0",
                    source_namespace="source-namespace0",
                    target_app_name="target-app0",
                    target_namespace="target-namespace0",
                    target_type=PolicyTargetType.app,
                    endpoints=[
                        Endpoint(
                            hosts=["host0"],
                            ports=[80],
                            methods=["GET"],  # type: ignore
                            paths=["/path0"],
                        )
                    ],
                ),
                MeshPolicy(
                    source_app_name="source-app1",
                    source_namespace="source-namespace1",
                    target_app_name="target-app1",
                    target_namespace="target-namespace1",
                    target_service="my-service1",
                    target_type=PolicyTargetType.app,
                    endpoints=[
                        Endpoint(
                            hosts=["host1"],
                            ports=[80],
                            methods=["GET"],  # type: ignore
                            paths=["/path1"],
                        )
                    ],
                ),
            ),
            "expected",
        )
    ]
)
@pytest.mark.disable_lightkube_client_autouse
def test_build_authorization_policies_app(
    istio_beacon_charm, istio_beacon_context, mesh_policies, expected
):
    model_name = "my-model"
    with istio_beacon_context(
        istio_beacon_context.on.update_status(),
        state=scenario.State(
            model=scenario.Model(name=model_name)
        ),
    ) as manager:
        charm: istio_beacon_charm = manager.charm  # type: ignore
        authorization_policies = _build_policy_resources_istio(charm.app.name, charm.model.name, mesh_policies)

        # Spot check the outputs
        for i_mesh_policy, mesh_policy in enumerate(mesh_policies):
            assert authorization_policies[i_mesh_policy]["metadata"].namespace == mesh_policy.target_namespace  # type: ignore
            assert authorization_policies[i_mesh_policy]["spec"]["targetRefs"][0]["name"] == mesh_policy.target_service or mesh_policy.target_app_name  # type: ignore
            for i_endpoint, endpoint in enumerate(mesh_policy.endpoints):
                assert authorization_policies[i_mesh_policy]["spec"]["rules"][0]["to"][i_endpoint]["operation"]["hosts"] == endpoint.hosts  # type: ignore
                assert authorization_policies[i_mesh_policy]["spec"]["rules"][0]["to"][i_endpoint]["operation"]["ports"] == [str(p) for p in endpoint.ports]  # type: ignore
                assert authorization_policies[i_mesh_policy]["spec"]["rules"][0]["to"][i_endpoint]["operation"]["methods"] == endpoint.methods  # type: ignore
                assert authorization_policies[i_mesh_policy]["spec"]["rules"][0]["to"][i_endpoint]["operation"]["paths"] == endpoint.paths  # type: ignore


@pytest.mark.parametrize(
    "mesh_policies,expected",
    [
        (
            (
                MeshPolicy(
                    source_app_name="source-app0",
                    source_namespace="source-namespace0",
                    target_app_name="target-app0",
                    target_namespace="target-namespace0",
                    target_type=PolicyTargetType.unit,
                    endpoints=[
                        Endpoint(
                            hosts=None,
                            ports=[80],
                            methods=None,  # type: ignore
                            paths=None,
                        )
                    ],
                ),
                MeshPolicy(
                    source_app_name="source-app1",
                    source_namespace="source-namespace1",
                    target_app_name="target-app1",
                    target_namespace="target-namespace1",
                    target_type=PolicyTargetType.unit,
                    endpoints=[
                        Endpoint(
                            hosts=["host1"],
                            ports=[80],
                            methods=["GET"],  # type: ignore
                            paths=["/path1"],
                        )
                    ],
                ),
                MeshPolicy(
                    source_app_name="source-app2",
                    source_namespace="source-namespace2",
                    target_namespace="target-namespace2",
                    target_workload_selector={"app": "my-app", "version": "v1"},
                    target_type=PolicyTargetType.unit,
                    endpoints=[
                        Endpoint(
                            hosts=None,
                            ports=[8080],
                            methods=None,  # type: ignore
                            paths=None,
                        )
                    ],
                ),
            ),
            "expected",
        )
    ]
)
@pytest.mark.disable_lightkube_client_autouse
def test_build_authorization_policies_unit(
    istio_beacon_charm, istio_beacon_context, mesh_policies, expected
):
    model_name = "my-model"
    with istio_beacon_context(
        istio_beacon_context.on.update_status(),
        state=scenario.State(
            model=scenario.Model(name=model_name)
        ),
    ) as manager:
        charm: istio_beacon_charm = manager.charm  # type: ignore
        authorization_policies = _build_policy_resources_istio(charm.app.name, charm.model.name, mesh_policies)

        # check if invalid authorization policies are not created
        assert authorization_policies[1] is None

        # Spot check the outputs
        for i_mesh_policy, mesh_policy in enumerate(mesh_policies):
            if authorization_policies[i_mesh_policy] is not None:
                assert authorization_policies[i_mesh_policy]["metadata"].namespace == mesh_policy.target_namespace  # type: ignore

                # Check selector - should use workload selector if provided, otherwise use app name
                if mesh_policy.target_workload_selector:
                    assert authorization_policies[i_mesh_policy]["spec"]["selector"]["matchLabels"] == mesh_policy.target_workload_selector  # type: ignore
                else:
                    assert authorization_policies[i_mesh_policy]["spec"]["selector"]["matchLabels"] == {"app.kubernetes.io/name": mesh_policy.target_app_name}  # type: ignore

                for i_endpoint, endpoint in enumerate(mesh_policy.endpoints):
                    operation = authorization_policies[i_mesh_policy]["spec"]["rules"][0]["to"][i_endpoint]["operation"]  # type: ignore
                    forbidden_attributes = ["hosts", "paths", "methods"]  # L7 attributes are forbidden in UnitPolicy
                    existing_forbidden = [key for key in forbidden_attributes if key in operation]
                    assert not existing_forbidden, f"Expected attributes {forbidden_attributes} to not exist, but found: {existing_forbidden}"
                    assert operation["ports"] == [str(p) for p in endpoint.ports]


@pytest.mark.parametrize("create_authorization_policies", [True, False])
@patch("charm.IstioBeaconCharm._put_charm_on_mesh")
@patch("charm.IstioBeaconCharm._setup_proxy_pebble_service")
@patch("charm.IstioBeaconCharm._is_waypoint_deployment_ready", return_value=True)
@patch("charm.IstioBeaconCharm._get_waypoint_resource_manager")
@patch("charm.IstioBeaconCharm._get_authorization_policy_resource_manager")
def test_charm_creates_authorization_policies_on_relation_changed(
    mock_get_authorization_policy_resource_manager,
    _mock_get_waypoint_resource_manager,
    _mock_is_waypoint_deployment_ready,
    _mock_setup_proxy_pebble_service,
    _mock_put_charm_on_mesh,
    create_authorization_policies,
    istio_beacon_charm,
    istio_beacon_context,
    service_mesh_relation,
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
