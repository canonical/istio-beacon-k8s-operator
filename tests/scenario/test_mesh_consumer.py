# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import typing

import pytest
import scenario
from charms.istio_beacon_k8s.v0.service_mesh import Endpoint, Policy, ServiceMeshConsumer
from ops import CharmBase


def consumer_context(policies: typing.List[Policy]):
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

REQUIRER = (
    [Policy(relation="rela", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

REQUIRER_CMR = (
    [Policy(relation="relb", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_b",
            "source_namespace": "remote_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

PROVIDER = (
    [Policy(relation="relc", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_c",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

PROVIDER_CMR = (
    [Policy(relation="reld", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_d",
            "source_namespace": "remote_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_service": None,
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

POLICY_DATA_PARAMS = [REQUIRER, REQUIRER_CMR, PROVIDER, PROVIDER_CMR]


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
