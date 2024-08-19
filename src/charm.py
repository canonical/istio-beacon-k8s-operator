#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio Beacon Charm."""

import logging
import time

import ops
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import create_namespaced_resource
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import Deployment
from lightkube.resources.core_v1 import Namespace
from lightkube_extensions.batch import KubernetesResourceManager, create_charm_default_labels
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

from models import AllowedRoutes, IstioWaypointResource, IstioWaypointSpec, Listener, Metadata

logger = logging.getLogger(__name__)

RESOURCE_TYPES = {
    "Gateway": create_namespaced_resource(
        "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
    ),
}

WAYPOINT_RESOURCE_TYPES = {RESOURCE_TYPES["Gateway"]}
WAYPOINT_LABEL = "istio-waypoint"


class IstioBeaconCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)

        self._lightkube_field_manager: str = self.app.name
        self._lightkube_client = None

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on["service-mesh"].relation_changed, self.on_mesh_changed)
        self.framework.observe(self.on["service-mesh"].relation_broken, self.on_mesh_broken)

    def _on_config_changed(self, _):
        """Event handler for config changed."""
        self._sync_all_resources()

    def on_mesh_changed(self, _):
        """Event handler for service-mesh relation_changed."""
        self._sync_all_resources()

    def on_mesh_broken(self, _):
        """Event handler for service-mesh relation_broken."""
        self._sync_all_resources()

    def _on_remove(self, _):
        """Event handler for remove."""
        self._update_labels(False)
        krm = self._get_waypoint_resource_manager()
        krm.delete()

    @property
    def lightkube_client(self):
        """Returns a lightkube client configured for this charm."""
        if self._lightkube_client is None:
            self._lightkube_client = Client(
                namespace=self.model.name, field_manager=self._lightkube_field_manager
            )
        return self._lightkube_client

    def _get_waypoint_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=WAYPOINT_LABEL
            ),
            resource_types=WAYPOINT_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _is_deployment_ready(self) -> bool:
        """Check if the deployment is ready after 10 attempts."""
        timeout = int(self.config["ready-timeout"])
        check_interval = 10
        attempts = timeout // check_interval

        for _ in range(attempts):
            try:
                deployment = self.lightkube_client.get(
                    Deployment,
                    name=f"{self.app.name}-{self.model.name}-waypoint",
                    namespace=self.model.name,
                )
                if (
                    deployment.status
                    and deployment.status.readyReplicas == deployment.status.replicas
                ):
                    return True
            except ApiError as e:
                logger.error(f"Error checking waypoint deployment status: {e}")

            time.sleep(check_interval)

        return False

    def _is_ready(self) -> bool:

        if not self._is_deployment_ready():
            return False
        return True

    def _sync_all_resources(self):
        if not self.unit.is_leader():
            self.unit.status = BlockedStatus("Waypoint can only be provided on the leader unit.")
            return
        self.unit.status = MaintenanceStatus("Validating waypoint readiness")
        self._sync_waypoint_resources()
        if not self._is_ready():
            self.unit.status = BlockedStatus(
                "Waypoint's k8s deployment not ready, is istio properly installed?"
            )
            return
        self.unit.status = ActiveStatus()

    def _construct_waypoint(self):
        gateway = IstioWaypointResource(
            metadata=Metadata(
                name=f"{self.app.name}-{self.model.name}-waypoint",
                namespace=self.model.name,
                labels={"istio.io/waypoint-for": "service"},
            ),
            spec=IstioWaypointSpec(
                gatewayClassName="istio-waypoint",
                listeners=[
                    Listener(
                        name="mesh",
                        port=15008,
                        protocol="HBONE",
                        allowedRoutes=AllowedRoutes(namespaces={"from": "All"}),
                    )
                ],
            ),
        )
        gateway_resource = RESOURCE_TYPES["Gateway"]
        return gateway_resource(
            metadata=ObjectMeta.from_dict(gateway.metadata.model_dump()),
            spec=gateway.spec.model_dump(),
        )

    def _sync_waypoint_resources(self):
        resources_list = []
        krm = self._get_waypoint_resource_manager()
        resource_to_append = self._construct_waypoint()
        resources_list.append(resource_to_append)
        krm.reconcile(resources_list)

        if self.config["model-on-mesh"]:
            self._update_labels()
        else:
            self._update_labels(False)

    def _update_labels(self, add_labels=True):
        """Add or remove specific labels from a namespace based on the add_labels flag.

        Args:
            add_labels (bool): If True, add labels; if False, remove labels.
        """
        try:
            namespace = self.lightkube_client.get(Namespace, self.model.name)
        except ApiError as e:
            logger.error(f"Error checking namespace labels {e}")
            return

        if add_labels:
            labels_to_add = {
                "istio.io/use-waypoint": f"{self.app.name}-{self.model.name}-waypoint",
                "istio.io/dataplane-mode": "ambient",
            }
            if namespace.metadata and namespace.metadata.labels:
                namespace.metadata.labels.update(labels_to_add)
        else:
            labels_to_remove = {"istio.io/use-waypoint": None, "istio.io/dataplane-mode": None}

            if (
                namespace.metadata
                and namespace.metadata.labels
                and (
                    "istio.io/use-waypoint" in namespace.metadata.labels
                    or "istio.io/dataplane-mode" in namespace.metadata.labels
                )
            ):
                namespace.metadata.labels.update(labels_to_remove)
        try:
            self.lightkube_client.patch(Namespace, self.model.name, namespace)
        except ApiError as e:
            logger.error(f"Error patching istio labels {e}")


if __name__ == "__main__":
    ops.main(IstioBeaconCharm)  # type: ignore
