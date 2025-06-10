# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""#Service Mesh Library.

The service mesh library is used to facilitate adding your charmed application to a service mesh.
The library leverages the `service_mesh` and `cross_model_mesh` interfaces.

##Consumer

Service meshes provide a range of capabilities for routing, controlling, and monitoring traffic.  A key feature of many service meshes is the ability to restrict traffic between Pods based on L4 and L7 criteria.  For example, defining that a Pod MetricsScraper can `GET` from Pod MetricsProducer at `/metrics` on port `9090`, but SomeOtherPod cannot.

The ServiceMeshConsumer object is used to subscribe a charm and its workloads to a related service mesh.  Since it is common for a relation between applications to indicate traffic flow (ex: if DbConsumer Requires a DbProducer), the ServiceMeshConsumer provides an optional way to automate creation of traffic rules based on app relations.

To add service mesh support to your charm, you must add 3 relations in your charmcraft.yaml.

```
requires:
  service-mesh:
    limit: 1
    interface: service_mesh
  require-cmr-mesh:
    interface: cross_model_mesh
provides:
  provide-cmr-mesh:
    interface: cross_model_mesh
```

Then instantiate a ServiceMeshConsumer object in the
`__init__` method of your charm:

```
from charms.istio_beacon_k8s.v0.service_mesh import Policy, ServiceMeshConsumer

...
self._mesh = ServiceMeshConsumer(
    self,
    policies=[
        Policy(
            relation="metrics",
            endpoints=[
                Endpoint(
                    hosts=[self._my_host_name],
                    ports=[HTTP_LISTEN_PORT],
                    methods=["GET"],
                    paths=["/metrics"],
                ),
            ],
        ),
        Policy(
            relation="data",
            endpoint=[
                Endpoint(
                    hosts=[self._my_host_name],
                    ports[HTTP_LISTEN_PORT],
                    methods=["GET"]
                    paths=["/data"],
                ),
            ],
        ),
    ],
)
```

The example above specifies two policies. The resulting behaviour would be that when related over the `metrics` relation, the service mesh will allow traffic to the `/metrics` endpoint for the remote application and when related over the `data` endpoint, the service mesh will allow traffic to the `/data` endpoint.

By using the above method, you can specify exactly which endpoints can be reached over which relations.

###Cross Model relations

If a ServiceMeshConsumer is creating a Policy for a relation that is cross model, additional information is required to construct the policy. To facilitate this, the charms can also be related over the cross_model_mesh interface. When that relation is established, traffic will be allowed from the requirer to the provider.

###Joining the Mesh

For most charms, simply instantiating ServiceMeshConsumer should automatically configure the charm to be on the mesh. If your charm is the one of the old "podspec" style charms or your charm deploys custom k8s resources there is an addition step. You must apply the labels returned by `ServiceMeshConsumer.labels()` to your pods.

##Provider

To provide a service mesh, instantiate the ServiceMeshProvider object in the __init__ method
of your charm:
```
from charms.istio_beacon_k8s.v0.service_mesh import ServiceMeshProvider

...
self._mesh = ServiceMeshProvider(
    charm = self,
    labels = {"my_service_mesh": "enable"},
    mesh_relation_name = "service-mesh",
)
```

The labels argument is the dict of labels that indicate to the service mesh that a Pod should be subscribed to the mesh.
These will be sent to each related ServiceMeshConsumer to be used by the charm for per-Pod subscription.  These labels
are service-mesh dependent - for example, for an Istio ambient mesh this should be
{"istio.io/dataplane-mode": "ambient"}.

The provider also exposes the method `mesh_info` that returns a list of MeshPolicy objects. These MeshPolicy objects can be used to configure the service mesh.

```
for policy in self._mesh.mesh_info():
    set_up_my_mesh(policy)
```
"""

import enum
import json
import logging
from typing import Dict, List, Optional

import httpx
import pydantic
from lightkube.core.client import Client
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import ConfigMap
from ops import CharmBase, Object, RelationMapping

LIBID = "3f40cb7e3569454a92ac2541c5ca0a0c"  # Never change this
LIBAPI = 0
LIBPATCH = 3

PYDEPS = ["lightkube", "pydantic"]

logger = logging.getLogger(__name__)


class Method(str, enum.Enum):
    """HTTP method."""

    connect = "CONNECT"
    delete = "DELETE"
    get = "GET"
    head = "HEAD"
    options = "OPTIONS"
    patch = "PATCH"
    post = "POST"
    put = "PUT"
    trace = "TRACE"


class Endpoint(pydantic.BaseModel):
    """Data type for a policy endpoint."""

    hosts: Optional[List[str]] = None
    ports: Optional[List[int]] = None
    methods: Optional[List[Method]] = None
    paths: Optional[List[str]] = None


class Policy(pydantic.BaseModel):
    """Data type for defining a policy for your charm."""

    relation: str
    endpoints: List[Endpoint]
    service: Optional[str] = None


class MeshPolicy(pydantic.BaseModel):
    """Data type for storage service mesh policy information."""

    source_app_name: str
    source_namespace: str
    target_app_name: str
    target_namespace: str
    target_service: Optional[str] = None
    endpoints: List[Endpoint]


class CMRData(pydantic.BaseModel):
    """Data type containing the info required for cross-model relations."""

    app_name: str
    juju_model_name: str


class ServiceMeshConsumer(Object):
    """Class used for joining a service mesh."""

    def __init__(
        self,
        charm: CharmBase,
        mesh_relation_name: str = "service-mesh",
        cross_model_mesh_requires_name: str = "require-cmr-mesh",
        cross_model_mesh_provides_name: str = "provide-cmr-mesh",
        policies: Optional[List[Policy]] = None,
        auto_join: bool = True,
    ):
        """Class used for joining a service mesh.

        Args:
            charm: The charm instantiating this object.
            mesh_relation_name: The relation name as defined in metadata.yaml or charmcraft.yaml
                for the relation which uses the service_mesh interface.
            cross_model_mesh_requires_name: The relation name as defined in metadata.yaml or
                charmcraft.yaml for the relation which requires the cross_model_mesh interface.
            cross_model_mesh_provides_name: The relation name as defined in metadata.yaml or
                charmcraft.yaml for the relation which provides the cross_model_mesh interface.
            policies: List of access policies this charm supports.
            auto_join: Automatically join the mesh by applying labels to charm pods.
        """
        super().__init__(charm, mesh_relation_name)
        self._charm = charm
        self._relation = self._charm.model.get_relation(mesh_relation_name)
        self._cmr_relations = self._charm.model.relations[cross_model_mesh_provides_name]
        self._policies = policies or []
        self._label_configmap_name = f"juju-service-mesh-{self._charm.app.name}-labels"
        if auto_join:
            self.framework.observe(
                self._charm.on[mesh_relation_name].relation_changed, self._update_labels
            )
            self.framework.observe(
                self._charm.on[mesh_relation_name].relation_broken, self._on_mesh_broken
            )
        self.framework.observe(
            self._charm.on[mesh_relation_name].relation_created, self._relations_changed
        )
        self.framework.observe(
            self._charm.on[cross_model_mesh_requires_name].relation_created, self._send_cmr_data
        )
        self.framework.observe(
            self._charm.on[cross_model_mesh_provides_name].relation_changed,
            self._relations_changed,
        )
        self.framework.observe(self._charm.on.upgrade_charm, self._relations_changed)
        relations = {policy.relation for policy in self._policies}
        for relation in relations:
            self.framework.observe(
                self._charm.on[relation].relation_created, self._relations_changed
            )
            self.framework.observe(
                self._charm.on[relation].relation_broken, self._relations_changed
            )

    def _send_cmr_data(self, event):
        """Send app and model information for CMR."""
        data = CMRData(
            app_name=self._charm.app.name, juju_model_name=self._charm.model.name
        ).model_dump()
        event.relation.data[self._charm.app]["cmr_data"] = json.dumps(data)

    def _relations_changed(self, _event):
        self.update_service_mesh()

    def update_service_mesh(self):
        """Update the service mesh.

        Gathers information from all relations of the charm and updates the mesh appropriately to
        allow communication.
        """
        if self._relation is None:
            return
        logger.debug("Updating service mesh policies.")

        # Collect the remote data from any fully established cross_model_relation integrations
        # {remote application name: cmr relation data}
        cmr_application_data = {
            cmr.app.name: CMRData.model_validate(json.loads(cmr.data[cmr.app]["cmr_data"]))
            for cmr in self._cmr_relations if "cmr_data" in cmr.data[cmr.app]
        }

        mesh_policies = build_mesh_policies(
            relation_mapping=self._charm.model.relations,
            target_app_name=self._charm.app.name,
            target_namespace=self._my_namespace(),
            policies=self._policies,
            cmr_application_data=cmr_application_data
        )
        self._relation.data[self._charm.app]["policies"] = json.dumps(mesh_policies)

    def _my_namespace(self):
        """Return the namespace of the running charm."""
        # This method currently assumes the namespace is the same as the model name. We
        # should consider if there is a better way to do this.
        return self._charm.model.name

    def labels(self) -> dict:
        """Labels required for a pod to join the mesh."""
        if self._relation is None or "labels" not in self._relation.data[self._relation.app]:
            return {}
        return json.loads(self._relation.data[self._relation.app]["labels"])

    def _on_mesh_broken(self, _event):
        self._set_labels({})
        self._delete_label_configmap()

    def _update_labels(self, _event):
        self._set_labels(self.labels())

    def _set_labels(self, labels: dict) -> None:
        client = Client(namespace=self._charm.model.name, field_manager=self._charm.app.name)
        stateful_set = client.get(res=StatefulSet, name=self._charm.app.name)
        try:
            config_map = client.get(ConfigMap, self._label_configmap_name)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                config_map = self._create_label_configmap(client)
            else:
                raise
        if config_map.data:
            config_map_labels = json.loads(config_map.data["labels"])
            for label in config_map_labels:
                if label not in labels:
                    # The label was previously set. Setting it to None will delete it.
                    labels[label] = None
        if stateful_set.spec:
            stateful_set.spec.template.metadata.labels.update(labels)  # type: ignore
        config_map.data = {"labels": json.dumps(labels)}
        client.patch(res=ConfigMap, name=self._label_configmap_name, obj=config_map)
        client.patch(res=StatefulSet, name=self._charm.app.name, obj=stateful_set)

    def _create_label_configmap(self, client) -> ConfigMap:
        """Create an empty ConfigMap unique to this charm."""
        obj = ConfigMap(
            data={"labels": "{}"},
            metadata=ObjectMeta(
                name=self._label_configmap_name,
                namespace=self._charm.model.name,
            ),
        )
        client.create(obj=obj)
        return obj

    def _delete_label_configmap(self) -> None:
        client = Client(namespace=self._charm.model.name, field_manager=self._charm.app.name)
        client.delete(res=ConfigMap, name=self._label_configmap_name)


class ServiceMeshProvider(Object):
    """Provide a service mesh to applications."""

    def __init__(
        self, charm: CharmBase, labels: Dict[str, str], mesh_relation_name: str = "service-mesh"
    ):
        """Class used to provide information needed to join the service mesh.

        Args:
            charm: The charm instantiating this object.
            mesh_relation_name: The relation name as defined in metadata.yaml or charmcraft.yaml
                for the relation which uses the service_mesh interface.
            labels: The labels which related applications need to apply to use the mesh.
        """
        super().__init__(charm, mesh_relation_name)
        self._charm = charm
        self._relation_name = mesh_relation_name
        self._labels = labels
        self.framework.observe(
            self._charm.on[mesh_relation_name].relation_created, self._relation_created
        )

    def _relation_created(self, _event):
        self.update_relations()

    def update_relations(self):
        """Update all relations with the labels needed to use the mesh."""
        rel_data = json.dumps(self._labels)
        for relation in self._charm.model.relations[self._relation_name]:
            relation.data[self._charm.app]["labels"] = rel_data

    def mesh_info(self) -> List[MeshPolicy]:
        """Return the relation data that defines Policies requested by the related applications."""
        mesh_info = []
        for relation in self._charm.model.relations[self._relation_name]:
            policies_data = json.loads(relation.data[relation.app]["policies"])
            policies = [MeshPolicy.model_validate(policy) for policy in policies_data]
            mesh_info.extend(policies)
        return mesh_info


def build_mesh_policies(
        relation_mapping: RelationMapping,
        target_app_name: str,
        target_namespace: str,
        policies: List[Policy],
        cmr_application_data: Dict[str, CMRData]
) -> List[MeshPolicy]:
    """Generate MeshPolicy that implement the given policies for the currently related applications.

    Args:
        relation_mapping: Charm's RelatioMapping object, for example self.model.relations.
        target_app_name: The name of the target application, for example self.app.name.
        target_namespace: The namespace of the target application, for example self.model.name.
        policies: List of Policy objects defining the access rules.
        cmr_application_data: Data for cross-model relations, mapping app names to CMRData.
    """
    mesh_policies = []
    for policy in policies:
        for relation in relation_mapping[policy.relation]:
            if relation.app.name in cmr_application_data:
                logger.debug(f"Found cross model relation: {relation.name}. Creating policy.")
                source_app_name = cmr_application_data[relation.app.name].app_name
                source_namespace = cmr_application_data[relation.app.name].juju_model_name
            else:
                logger.debug(f"Found in-model relation: {relation.name}. Creating policy.")
                source_app_name = relation.app.name
                source_namespace = target_namespace

            mesh_policies.append(
                MeshPolicy(
                    source_app_name=source_app_name,
                    source_namespace=source_namespace,
                    target_app_name=target_app_name,
                    target_namespace=target_namespace,
                    target_service=policy.service,
                    endpoints=policy.endpoints,
                ).model_dump()
            )
    return mesh_policies
