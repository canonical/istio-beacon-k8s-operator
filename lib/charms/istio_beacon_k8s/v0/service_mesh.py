# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""#Service Mesh Library.

The service mesh library is used to facilitate adding you charmed application to a service mesh.
The library leverages the `service_mesh` interface and the `cross_model_mesh` interface

To add service mesh support to your charm, instantiate a ServiceMeshConsumer object in the
`__init__` method of your charm:

```
from charms.istio_beacon_k8s.v0.service_mesh import Policy, ServiceMeshConsumer

...
try:
    self._mesh = ServiceMeshConsumer(
        self,
        policies=[
            Policy(relation="logging", endpoints=[f"*:{HTTP_LISTEN_PORT}"]),
        ],
    )
except ops.TooManyRelatedAppsError as e:
    self.unit.status = BlockedStatus(e)
```
"""

import enum
import json
import logging
import re
from typing import List, Optional

import pydantic
from ops import CharmBase, Object

LIBID = "3f40cb7e3569454a92ac2541c5ca0a0c"  # Never change this
LIBAPI = 0
LIBPATCH = 1

PYDEPS = ["pydantic"]

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

    hosts: List[str]
    ports: List[int]
    methods: List[Method]
    paths: List[str]


class Policy(pydantic.BaseModel):
    """Data type for holding a service mesh policy."""

    relation: str
    endpoints: List[Endpoint]
    service: Optional[str]


class ServiceMeshConsumer(Object):
    """Class used for joining a service mesh."""

    def __init__(
        self,
        charm: CharmBase,
        mesh_relation_name: str = "service-mesh",
        policies: Optional[List[Policy]] = None,
    ):
        """Class used for joining a service mesh.

        Args:
            charm: The charm instantiating this object.
            mesh_relation_name: The relation name as defined in metadata.yaml or charmcraft.yaml
                for the relation which used the service_mesh interface.
            policies: List of access policies this charm supports.
        """
        super().__init__(charm, mesh_relation_name)
        self._charm = charm
        self._relation = self._charm.model.get_relation(mesh_relation_name)
        self._policies = policies or []
        self.framework.observe(
            self._charm.on[mesh_relation_name].relation_created, self._relations_changed
        )
        self.framework.observe(self._charm.on.upgrade_charm, self._relations_changed)
        for policy in self._policies:
            self.framework.observe(
                self._charm.on[policy.relation].relation_created, self._relations_changed
            )
            self.framework.observe(
                self._charm.on[policy.relation].relation_broken, self._relations_changed
            )

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
        policies = []
        cmr_matcher = re.compile(r"remote\-[a-f0-9]+")
        for policy in self._policies:
            for relation in self._charm.model.relations[policy.relation]:
                if cmr_matcher.fullmatch(relation.app.name):
                    logger.debug(
                        f"Cross model relation found: {relation.name}. Currently not implemented. Skipping."
                    )
                else:
                    logger.debug(f"Found relation: {relation.name}. Creating policy.")
                    policies.append(
                        {
                            "app_name": relation.app.name,
                            "namespace": self._my_namespace(),
                            "endpoints": policy.endpoints,
                            "service": policy.service,
                        }
                    )
        mesh_rel_data = {
            "app_name": self._charm.app.name,
            "model": self._my_namespace(),
            "policies": policies,
        }
        self._relation.data[self._charm.app]["mesh_data"] = json.dumps(mesh_rel_data)

    def _my_namespace(self):
        """Return the namespace of the running charm."""
        # This method currently assumes the namespace is the same as the model name. We
        # should consider if there is a better way to do this.
        return self._charm.model.name
