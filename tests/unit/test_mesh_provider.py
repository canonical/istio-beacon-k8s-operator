import json

import scenario
from charms.istio_beacon_k8s.v0.service_mesh import ServiceMeshProvider, ServiceMeshProviderAppData
from ops import CharmBase

MESH_LABELS = {
    "label1": "value1",
    "label2": "value2",
}
MESH_RELATION_NAME = "service-mesh-relation"
MESH_INTERFACE_NAME = "service_mesh_interface"


def provider_context() -> scenario.Context:
    meta = {
        "name": "provider-charm",
        "provides": {
            MESH_RELATION_NAME: {"interface": MESH_INTERFACE_NAME},
        },
    }


    class Charm(CharmBase):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.mesh = ServiceMeshProvider(self, labels=MESH_LABELS, mesh_relation_name=MESH_RELATION_NAME)

    return scenario.Context(Charm, meta)


def test_provider_sends_data():
    ctx = provider_context()
    mesh_relation = scenario.Relation(
        endpoint=MESH_RELATION_NAME,
        interface=MESH_INTERFACE_NAME,
    )
    state = scenario.State(
        relations=[mesh_relation],
        leader=True,
    )
    out = ctx.run(ctx.on.relation_created(mesh_relation), state)
    raw_data = {k: json.loads(v) for k, v in out.get_relation(mesh_relation.id).local_app_data.items()}
    actual = ServiceMeshProviderAppData.model_validate(raw_data)
    assert actual.labels == MESH_LABELS
