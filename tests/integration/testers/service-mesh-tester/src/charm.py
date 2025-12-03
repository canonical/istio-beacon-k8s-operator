#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

from charms.istio_beacon_k8s.v0.service_mesh import (
    AppPolicy,
    Endpoint,
    MeshPolicy,
    MeshType,
    PolicyResourceManager,
    PolicyTargetType,
    ServiceMeshConsumer,
    UnitPolicy,
)
from lightkube import Client
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class ServiceMeshTester(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self._ports = [8080, 8081]
        self.unit.set_ports(*self._ports)

        charm_auth_policies = [
            AppPolicy(
                relation="inbound",
                endpoints=[
                    Endpoint(
                        ports=self._ports,
                        methods=["GET", "POST"],  # type: ignore
                        paths=["/foo", "/bar/"],
                    ),
                ],
            ),
            UnitPolicy(
                relation="inbound-unit",
                ports=self._ports,
            ),
        ]
        if bool(self.config["peer-communication"]):
            charm_auth_policies.append(
                UnitPolicy(
                    relation="peers",
                    ports=self._ports,
                )
            )
        self._mesh = ServiceMeshConsumer(
            self,
            policies=charm_auth_policies,
            auto_join=bool(self.config["auto-join-mesh"]),
        )

        # Initialize PolicyResourceManager for wildcard policy support
        self._policy_resource_manager = None
        if bool(self.config["use-wildcard-policy"]):
            try:
                lightkube_client = Client(field_manager=f"{self.app.name}-{self.model.name}")
                labels = {
                    "app.kubernetes.io/name": f"{self.app.name}-{self.model.name}",
                    "kubernetes-resource-handler-scope": "wildcard-policy-test",
                }
                self._policy_resource_manager = PolicyResourceManager(
                    charm=self,  # type: ignore[arg-type]
                    lightkube_client=lightkube_client,  # type: ignore[arg-type]
                    labels=labels,
                )
            except Exception as e:
                logger.error(f"Failed to initialize PolicyResourceManager: {e}")

        self.framework.observe(self.on.echo_server_pebble_ready, self.on_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.leader_elected, self._reconcile_wildcard_policy)

    def _on_config_changed(self, event):
        if self.unit.is_leader():
            self._mesh.update_service_mesh()
            self._reconcile_wildcard_policy(event)

    def on_pebble_ready(self, _):
        container = self.unit.get_container("echo-server")
        if not container.can_connect():
            raise ValueError("container.can_connect() failed during a pebble_ready handler")

        layer = Layer(
            # Start a listener for each defined port
            {
                "summary": "echo server layer",
                "description": "pebble config layer for echo server",
                "services": {
                    f"echo-server-{i}": {
                        "override": "replace",
                        "command": "/bin/echo-server",
                        "startup": "enabled",
                        "environment": {"PORT": str(port)},
                    }
                    for i, port in enumerate(self._ports)
                },
            }
        )

        container.add_layer("echo-server", layer, combine=True)
        container.autostart()
        self.unit.status = ActiveStatus("Echo server running")

    def _reconcile_wildcard_policy(self, event):
        """Reconcile wildcard policy if configured."""
        if not self.unit.is_leader():
            return

        if not bool(self.config["use-wildcard-policy"]):
            logger.info("Wildcard policy disabled, skipping reconciliation")
            return

        if self._policy_resource_manager is None:
            logger.error("PolicyResourceManager not initialized")
            self.unit.status = BlockedStatus("PolicyResourceManager not initialized")
            return

        try:
            # Create a wildcard MeshPolicy that allows any source to reach this app
            wildcard_policy = MeshPolicy(
                enforce_source=False,
                target_namespace=self.model.name,
                target_app_name=self.app.name,
                target_type=PolicyTargetType.app,
                endpoints=[
                    Endpoint(
                        ports=self._ports,
                    )
                ],
            )
            logger.info(f"Reconciling wildcard policy for {self.app.name}")
            self._policy_resource_manager.reconcile([wildcard_policy], MeshType.istio)
            logger.info("Wildcard policy reconciled successfully")
        except Exception as e:
            logger.error(f"Failed to reconcile wildcard policy: {e}")
            self.unit.status = BlockedStatus(f"Failed to reconcile wildcard policy: {e}")


if __name__ == "__main__":
    main(ServiceMeshTester)
