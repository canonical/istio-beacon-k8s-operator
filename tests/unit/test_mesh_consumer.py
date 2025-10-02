# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import typing
from unittest.mock import MagicMock, patch

import pytest
import scenario
from charms.istio_beacon_k8s.v0.service_mesh import (
    AppPolicy,
    Endpoint,
    MeshType,
    Policy,
    ServiceMeshConsumer,
    ServiceMeshProviderAppData,
    UnitPolicy,
    reconcile_charm_labels,
)
from ops import CharmBase


def consumer_context(policies: typing.List[typing.Union[Policy, AppPolicy, UnitPolicy]]) -> scenario.Context:
    meta = {
        "name": "consumer-charm",
        "requires": {
            "service-mesh": {"interface": "service_mesh"},
            "require-cmr-mesh": {"interface": "cross_model_mesh"},
            "rela": {"interface": "foo"},
            "relb": {"interface": "foo"},
        },
        "provides": {
            "provide-cmr-mesh": {"interface": "cross_model_mesh"},
            "relc": {"interface": "foo"},
            "reld": {"interface": "foo"},
        },
    }

    class ConsumerCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.mesh = ServiceMeshConsumer(charm=self, policies=policies)

    return scenario.Context(ConsumerCharm, meta)


ENDPOINT_A = Endpoint(hosts=[], ports=[80], methods=[], paths=[])

WITH_COMPLEX_ENDPOINTS = (
    [
        AppPolicy(
            relation="rela",
            endpoints=[
                Endpoint(
                    hosts=["localhost"],
                    ports=[443, 9000],
                    methods=["GET", "POST"],  # type: ignore
                    paths=["/metrics", "/data"],
                ),
                Endpoint(
                    hosts=["example.com"],
                    ports=[3000],
                    methods=["DELETE"],  # type: ignore
                    paths=["/foobar"],
                ),
            ],
            service=None,
        )
    ],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "target_type": "app",
            "endpoints": [
                {
                    "hosts": ["localhost"],
                    "ports": [443, 9000],
                    "methods": ["GET", "POST"],
                    "paths": ["/metrics", "/data"],
                },
                {
                    "hosts": ["example.com"],
                    "ports": [3000],
                    "methods": ["DELETE"],
                    "paths": ["/foobar"],
                },
            ],
        }
    ],
)

MULTIPLE_POLICIES = (
    [
        AppPolicy(relation="rela", endpoints=[ENDPOINT_A], service=None),
        AppPolicy(relation="relc", endpoints=[ENDPOINT_A], service=None),
    ],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        },
        {
            "source_app_name": "remote_c",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        },
    ],
)

REQUIRER = (
    [AppPolicy(relation="rela", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

REQUIRER_CMR = (
    [AppPolicy(relation="relb", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_b",
            "source_namespace": "remote_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

PROVIDER = (
    [AppPolicy(relation="relc", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_c",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

PROVIDER_CMR = (
    [AppPolicy(relation="reld", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_d",
            "source_namespace": "remote_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

# Test case for deprecated Policy class (should work like AppPolicy)
POLICY_DEPRECATED = (
    [Policy(relation="rela", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

UNIT_POLICY = (
    [UnitPolicy(relation="rela", ports=[8080])],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "target_type": "unit",
            "endpoints": [{"hosts": None, "ports": [8080], "methods": None, "paths": None}],
        }
    ],
)

POLICY_DATA_PARAMS = [
    WITH_COMPLEX_ENDPOINTS,
    MULTIPLE_POLICIES,
    REQUIRER,
    REQUIRER_CMR,
    PROVIDER,
    PROVIDER_CMR,
    POLICY_DEPRECATED,
    UNIT_POLICY,
]


@pytest.mark.parametrize("policies,expected_data", POLICY_DATA_PARAMS)
def test_relation_data_policies(policies, expected_data):
    """Test that a given list of policies produces the expected output.

    This test sets up 4 relations; requirer, requirer_cmr, provider, and provider_cmr. The
    policies can be on any combination of these relations and should produce proper
    objects.
    """
    ctx = consumer_context(policies)
    mesh_relation = scenario.Relation(endpoint="service-mesh", interface="service_mesh")
    rela = scenario.Relation("rela", "foo", remote_app_name="remote_a")
    relb = scenario.Relation("relb", "foo", remote_app_name="masked_name_b")
    cmr_relb = scenario.Relation(
        "provide-cmr-mesh",
        "cross_model_mesh",
        remote_app_name="masked_name_b",
        remote_app_data={
            "cmr_data": json.dumps(
                {
                    "app_name": "remote_b",
                    "juju_model_name": "remote_model",
                }
            )
        },
    )
    relc = scenario.Relation("relc", "foo", remote_app_name="remote_c")
    reld = scenario.Relation("reld", "foo", remote_app_name="masked_name_d")
    cmr_reld = scenario.Relation(
        "provide-cmr-mesh",
        "cross_model_mesh",
        remote_app_name="masked_name_d",
        remote_app_data={
            "cmr_data": json.dumps(
                {
                    "app_name": "remote_d",
                    "juju_model_name": "remote_model",
                }
            )
        },
    )
    state = scenario.State(
        relations={
            mesh_relation,
            rela,
            relb,
            cmr_relb,
            relc,
            reld,
            cmr_reld,
        },
        leader=True,
        model=scenario.Model(name="my_model"),
    )
    out = ctx.run(ctx.on.relation_created(relation=mesh_relation), state)
    assert (
        json.loads(out.get_relation(mesh_relation.id).local_app_data["policies"]) == expected_data
    )


def lightkube_client_mock(unmanaged_labels: dict, managed_labels: dict) -> MagicMock:
    """Return a mock lightkube client that has a StatefulSet, Service, and ConfigMap, each with the given labels.

    This simulates the kubernetes resources that a charm would have and the service mesh library would interact with.
    All resources are mocked using a shallow copy of the input labels.

    The returned mock has a `.get()` that will return the StatefulSet, Service, or ConfigMap as required.  If called
    for anything else, it will raise a KeyError.

    Args:
        unmanaged_labels (dict): Labels that are currently on the objects and are not managed by reconcile_charm_labels.
                                 For example, a label an admin added to the Service manually.
        managed_labels (dict): Labels that are currently on the objects and are managed by reconcile_charm_labels.
    """
    client = MagicMock()

    obj_labels = unmanaged_labels.copy()
    obj_labels.update(managed_labels)

    # Mock StatefulSet that will create Pods with the labels
    # Pods and Service get both the managed and unmanaged labels
    stateful_set = MagicMock()
    # Use a copy here, otherwise all mocks point at a shared obj_labels
    stateful_set.spec.template.metadata.labels = obj_labels.copy()

    # Mock Service that has the labels
    service = MagicMock()
    service.metadata.labels = obj_labels.copy()

    # Mock ConfigMap with a labels field in data
    config_map = MagicMock()
    # ConfigMap is a memory of what labels are currently managed.
    config_map.data = {"labels": json.dumps(managed_labels)}

    client.get.side_effect = lambda res, name: {
        "StatefulSet": stateful_set,
        "Service": service,
        "ConfigMap": config_map,
    }[res.__name__]

    return client


def assert_charm_kubernetes_objects_have_labels(expected_patch, expected_in_configmap, mock_client: MagicMock):
    """Assert that the mock client has patched the StatefulSet, Service, and ConfigMap as expected.

    Args:
        expected_patch (dict): The labels that should be present on the StatefulSet and Service after patching.
        expected_in_configmap (dict): The labels that should be present in the ConfigMap's data field under "labels".
        mock_client (MagicMock): The mock lightkube client that was used to patch the resources.
    """
    # Ensure the patched resources have the expected labels
    patched_statefulset = [call_args.kwargs['obj'] for call_args in mock_client.patch.call_args_list if
                           call_args.kwargs['res'].__name__ == "StatefulSet"]
    assert len(patched_statefulset) == 1
    assert patched_statefulset[0].spec.template.metadata.labels == expected_patch
    patched_service = [call_args.kwargs['obj'] for call_args in mock_client.patch.call_args_list if
                       call_args.kwargs['res'].__name__ == "Service"]
    assert len(patched_service) == 1
    assert patched_service[0].metadata.labels == expected_patch
    patched_configmap = [call_args.kwargs['obj'] for call_args in mock_client.patch.call_args_list if
                         call_args.kwargs['res'].__name__ == "ConfigMap"]
    assert len(patched_configmap) == 1
    assert len(patched_configmap[0].data) == 1
    assert json.loads(patched_configmap[0].data["labels"]) == expected_in_configmap


@pytest.mark.parametrize(
    "initial_unmanaged_labels, initial_managed_labels, desired_managed_labels, expected_patch",
    [
        # Add label to objects, without disrupting existing labels
        (
            {"some-unmanaged-label": "some-value"},
            {},
            {"key-added": "value-added"},
            {"key-added": "value-added", "some-unmanaged-label": "some-value"},
        ),
        # Add one label, update one label, and remove one label without disrupting existing labels
        (
            {"some-unmanaged-label": "some-value"},
            {"key-to-be-removed": "value-to-be-removed", "key-to-be-updated": "value-to-be-updated"},
            {"key-to-be-updated": "value-updated", "key-added": "value-added"},
            {"key-to-be-removed": None, "key-to-be-updated": "value-updated", "key-added": "value-added", "some-unmanaged-label": "some-value"}
        ),
        # Remove labels
        (
            {"some-unmanaged-label": "some-value"},
            {"key-to-be-removed": "v", "key-to-be-removed2": "v"},
            {},
            {"key-to-be-removed": None, "key-to-be-removed2": None, "some-unmanaged-label": "some-value"},
        ),

    ]
)
def test_reconcile_charm_labels(
        initial_unmanaged_labels,
        initial_managed_labels,
        desired_managed_labels,
        expected_patch
):
    """Test that reconcile_charm_labels correctly patches the StatefulSet, Service, and ConfigMap with the labels.

    Args:
        initial_unmanaged_labels (dict): Labels that are currently on the objects and are not managed by
                                         reconcile_charm_labels.
        initial_managed_labels (dict): Labels on the kubernetes objects before execution
        desired_managed_labels (dict): The labels that should be present after execution.
        expected_patch (dict): The labels our client.patch() should send to Kubernetes
    """
    mock_client = lightkube_client_mock(unmanaged_labels=initial_unmanaged_labels, managed_labels=initial_managed_labels)

    reconcile_charm_labels(
        client=mock_client,
        app_name="my-app",
        namespace="test-ns",
        label_configmap_name="my-cm",
        labels=desired_managed_labels.copy(),
    )

    assert_charm_kubernetes_objects_have_labels(expected_patch=expected_patch, expected_in_configmap=desired_managed_labels, mock_client=mock_client)


def test_reconcile_charm_labels_configmap_created_on_404():
    """Test that reconcile_charm_labels creates its ConfigMap if it doesn't exist."""
    mocked_client = lightkube_client_mock(unmanaged_labels={}, managed_labels={})
    def side_effect(res, name):
        if res.__name__ == "ConfigMap":
            from httpx import HTTPStatusError, Request, Response
            raise HTTPStatusError("Not found", request=Request("GET", "url"), response=Response(404))
        else:
            return MagicMock()
    mocked_client.get.side_effect = side_effect

    # mock _init_label_configmap to return a mock ConfigMap with a data field that has no labels included, just so
    # reconcile_charm_labels doesn't fail
    with patch("charms.istio_beacon_k8s.v0.service_mesh._init_label_configmap") as mock_init:
        mock_init.return_value = MagicMock()
        mock_init.return_value.data = {"labels": "{}"}
        reconcile_charm_labels(
            client=mocked_client,
            app_name="my-app",
            namespace="test-ns",
            label_configmap_name="my-cm",
            labels={},
        )
        # Ensure the ConfigMap was created
        mock_init.assert_called_once()


# No need to actually reconcile anything in this test.
@patch("charms.istio_beacon_k8s.v0.service_mesh.reconcile_charm_labels")
def test_getting_relation_data(patched_reconcile: MagicMock):
    """Test that the consumer can read relation data set by a provider."""
    ctx = consumer_context([AppPolicy(relation="rela", endpoints=[ENDPOINT_A], service=None)])
    labels_actual = {"label1": "value1", "label2": "value2"}
    mesh_type_actual = MeshType.istio
    expected_data = ServiceMeshProviderAppData(
        labels=labels_actual,
        mesh_type=mesh_type_actual,
    )
    mesh_relation = scenario.Relation(
        endpoint="service-mesh",
        interface="service_mesh",
        remote_app_data={
            "labels": json.dumps(labels_actual),
            "mesh_type": json.dumps(mesh_type_actual)
        }
    )
    state = scenario.State(
        relations={
            mesh_relation,
        },
        leader=True,
    )
    with ctx(
        ctx.on.relation_changed(relation=mesh_relation),
        state,
    ) as manager:
        assert labels_actual == manager.charm.mesh.labels()
        assert mesh_type_actual == manager.charm.mesh.mesh_type()
        assert expected_data == manager.charm.mesh._get_app_data()
