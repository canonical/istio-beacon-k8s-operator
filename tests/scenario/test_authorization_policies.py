# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import json

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
                                methods=["GET"],
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
                                methods=["GET"],
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
        charm: istio_beacon_charm = manager.charm
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
        charm: istio_beacon_charm = manager.charm
        authorization_policies = charm._build_authorization_policies(charm._mesh.mesh_info())

        # Spot check the outputs
        assert authorization_policies[0]["metadata"].namespace == model_name
        assert authorization_policies[0]["spec"]["targetRefs"][0]["name"] == "my-service1"
        assert authorization_policies[1]["spec"]["rules"][0]["to"][0]["operation"]["paths"] == [
            "/path2"
        ]
        assert authorization_policies[1]["spec"]["targetRefs"][0]["name"] == "target-app2"
