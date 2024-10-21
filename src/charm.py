#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio Beacon Charm."""

import logging
import time
from typing import Dict

import ops
from charms.istio_beacon_k8s.v0.service_mesh import ServiceMeshProvider
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import create_namespaced_resource
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import Deployment
from lightkube.resources.core_v1 import Namespace
from lightkube_extensions.batch import KubernetesResourceManager, create_charm_default_labels
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import ChangeError, Layer

from models import (
    AllowedRoutes,
    AuthorizationPolicySpec,
    From,
    IstioWaypointResource,
    IstioWaypointSpec,
    Listener,
    Metadata,
    Operation,
    PolicyTargetReference,
    Rule,
    Source,
    To,
)

logger = logging.getLogger(__name__)

RESOURCE_TYPES = {
    "Gateway": create_namespaced_resource(
        "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
    ),
    "AuthorizationPolicy": create_namespaced_resource(
        "security.istio.io",
        "v1",
        "AuthorizationPolicy",
        "authorizationpolicies",
    ),
}

AUTHORIZATION_POLICY_LABEL = "istio-authorization-policy"
AUTHORIZATION_POLICY_RESOURCE_TYPES = {RESOURCE_TYPES["AuthorizationPolicy"]}
WAYPOINT_LABEL = "istio-waypoint"
WAYPOINT_RESOURCE_TYPES = {RESOURCE_TYPES["Gateway"]}


class IstioBeaconCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)

        self._lightkube_field_manager: str = self.app.name
        self._lightkube_client = None
        self._managed_labels = f"{self.app.name}-{self.model.name}"

        self._telemetry_labels = {
            f"charms.canonical.com/{self.model.name}.{self.app.name}.telemetry": "aggregated"
        }
        # Configure Observability
        self._scraping = MetricsEndpointProvider(
            self,
            jobs=[{"static_configs": [{"targets": ["*:15090"]}]}],
        )

        self._waypoint_name = f"{self.app.name}-{self.model.name}-waypoint"

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(
            self.on.metrics_proxy_pebble_ready, self._metrics_proxy_pebble_ready
        )
        self._mesh = ServiceMeshProvider(self, labels=self.mesh_labels())

        self.framework.observe(self.on["service-mesh"].relation_changed, self.on_mesh_changed)
        self.framework.observe(self.on["service-mesh"].relation_broken, self.on_mesh_broken)

    def _setup_proxy_pebble_service(self):
        """Define and start the metrics broadcast proxy Pebble service."""
        proxy_container = self.unit.get_container("metrics-proxy")
        if not proxy_container.can_connect():
            return
        proxy_layer = Layer(
            {
                "summary": "Metrics Broadcast Proxy Layer",
                "description": "Pebble layer for the metrics broadcast proxy",
                "services": {
                    "metrics-proxy": {
                        "override": "replace",
                        "summary": "Metrics Broadcast Proxy",
                        "command": f"metrics-proxy --labels {self.format_labels(self._telemetry_labels)}",
                        "startup": "enabled",
                    }
                },
            }
        )

        proxy_container.add_layer("metrics-proxy", proxy_layer, combine=True)

        try:
            proxy_container.replan()
        except ChangeError as e:
            logger.error(f"Error while replanning proxy container: {e}")

    def _on_config_changed(self, _):
        """Event handler for config changed."""
        self._sync_all_resources()

    def _metrics_proxy_pebble_ready(self, _):
        """Event handler for metrics_proxy_pebble_ready."""
        self._sync_all_resources()

    def on_mesh_changed(self, _):
        """Event handler for service-mesh relation_changed."""
        self._sync_all_resources()

    def on_mesh_broken(self, _):
        """Event handler for service-mesh relation_broken."""
        self._sync_all_resources()

    def _on_remove(self, _):
        """Event handler for remove."""
        self._remove_labels()
        for krm in (
            self._get_waypoint_resource_manager(),
            self._get_authorization_policy_resource_manager(),
        ):
            krm.delete()

    @property
    def lightkube_client(self):
        """Returns a lightkube client configured for this charm."""
        if self._lightkube_client is None:
            self._lightkube_client = Client(
                namespace=self.model.name, field_manager=self._lightkube_field_manager
            )
        return self._lightkube_client

    def _get_authorization_policy_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=AUTHORIZATION_POLICY_LABEL
            ),
            resource_types=AUTHORIZATION_POLICY_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _get_waypoint_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=WAYPOINT_LABEL
            ),
            resource_types=WAYPOINT_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _is_waypoint_deployment_ready(self) -> bool:
        """Check if the deployment is ready after 10 attempts."""
        timeout = int(self.config["ready-timeout"])
        check_interval = 10
        attempts = timeout // check_interval

        for _ in range(attempts):
            try:
                deployment = self.lightkube_client.get(
                    Deployment,
                    name=self._waypoint_name,
                    namespace=self.model.name,
                )
                if (
                    deployment.status
                    and deployment.status.readyReplicas == deployment.status.replicas
                ):
                    return True
                logger.info("Deployment not ready, retrying...")
            except ApiError:
                logger.info("Deployment not found, retrying...")

            time.sleep(check_interval)

        return False

    def _is_waypoint_ready(self) -> bool:
        if not self._is_waypoint_deployment_ready():
            return False
        return True

    def _sync_all_resources(self):
        if not self.unit.is_leader():
            self.unit.status = BlockedStatus("Waypoint can only be provided on the leader unit.")
            return

        self.unit.status = MaintenanceStatus("Validating waypoint readiness")
        self._sync_waypoint_resources()
        if not self._is_waypoint_ready():
            raise RuntimeError("Waypoint's k8s deployment not ready, is istio properly installed?")

        self._setup_proxy_pebble_service()

        self.unit.status = MaintenanceStatus("Updating AuthorizationPolicies")
        self._sync_authorization_policies()

        self.unit.status = ActiveStatus()

    def _build_authorization_policies(self, mesh_info):
        """Build authorization policies for all related applications."""
        authorization_policies = [None] * len(mesh_info)
        for i, policy in enumerate(mesh_info):
            target_service = policy.target_service or policy.target_app_name
            if policy.target_service is None:
                logger.info(
                    f"Got policy for application '{policy.target_app_name}' that has no target_service. "
                    f"Defaulting to application name '{target_service}'."
                )

            authorization_policies[i] = RESOURCE_TYPES["AuthorizationPolicy"](  # type: ignore
                metadata=ObjectMeta(
                    # TODO: Improve how we name these policies.  See
                    #  https://github.com/canonical/istio-beacon-k8s-operator/issues/22 for more details.
                    name=f"{self._managed_labels}-policy-{policy.source_app_name}-{policy.target_app_name}.{i}",
                    namespace=self.model.name,
                ),
                spec=AuthorizationPolicySpec(
                    targetRefs=[
                        PolicyTargetReference(
                            kind="Service",
                            group="",
                            name=target_service,
                        )
                    ],
                    rules=[
                        Rule(
                            from_=[  # type: ignore # this is accessible via an alias
                                From(
                                    source=Source(
                                        principals=[
                                            _get_peer_identity_for_juju_application(
                                                policy.source_app_name, self.model.name
                                            )
                                        ]
                                    )
                                )
                            ],
                            to=[
                                To(
                                    operation=Operation(
                                        # TODO: Make these ports strings instead of ints in endpoint?
                                        ports=[str(p) for p in endpoint.ports],
                                        hosts=endpoint.hosts,
                                        methods=endpoint.methods,
                                        paths=endpoint.paths,
                                    )
                                )
                                for endpoint in policy.endpoints
                            ],
                        )
                    ],
                    # by_alias=True because the model includes an alias for the `from` field
                    # exclude_unset=True because unset fields will be treated as their default values in Kubernetes
                    # exclude_none=True because null values in this data always mean the Kubernetes default
                ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
            )
        return authorization_policies

    def _construct_waypoint(self):
        gateway = IstioWaypointResource(
            metadata=Metadata(
                name=self._waypoint_name,
                namespace=self.model.name,
                labels={"istio.io/waypoint-for": "all", **self._telemetry_labels},
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

    def _sync_authorization_policies(self):
        """Sync authorization policies."""
        krm = self._get_authorization_policy_resource_manager()
        authorization_policies = self._build_authorization_policies(self._mesh.mesh_info())
        logger.debug("Reconciling state of AuthorizationPolicies to:")
        logger.debug(authorization_policies)
        krm.reconcile(authorization_policies)  # type: ignore

    def _sync_waypoint_resources(self):
        resources_list = []
        krm = self._get_waypoint_resource_manager()
        resource_to_append = self._construct_waypoint()
        resources_list.append(resource_to_append)
        krm.reconcile(resources_list)

        if self.config["model-on-mesh"]:
            self._add_labels()
        else:
            self._remove_labels()

    def _get_namespace(self):
        """Retrieve the namespace object."""
        try:
            return self.lightkube_client.get(Namespace, self.model.name)
        except ApiError as e:
            logger.error(f"Error fetching namespace: {e}")
            return None

    def _patch_namespace(self, namespace):
        """Patch the namespace with updated labels."""
        try:
            self.lightkube_client.patch(Namespace, self.model.name, namespace)
        except ApiError as e:
            logger.error(f"Error patching namespace: {e}")

    def _add_labels(self):
        """Add specific labels to the namespace."""
        namespace = self._get_namespace()
        if not namespace:
            raise RuntimeError(f"Error fetching namespace: {namespace}")

        # Ensure metadata is not None
        if namespace.metadata is None:
            namespace.metadata = ObjectMeta()

        # Ensure labels are a dictionary even if they are initially None or not set
        if namespace.metadata.labels is None:  # pyright: ignore
            namespace.metadata.labels = {}  # pyright: ignore

        existing_labels = namespace.metadata.labels  # pyright: ignore
        if (
            existing_labels.get("istio.io/use-waypoint")
            or existing_labels.get("istio.io/dataplane-mode")
        ) and existing_labels.get(
            "charms.canonical.com/istio.io.waypoint.managed-by"
        ) != f"{self._managed_labels}":
            logger.error(
                f"Cannot add labels: Namespace '{self.model.name}' is already configured with Istio labels managed by another entity."
            )
            return

        labels_to_add = {
            "istio.io/use-waypoint": self._waypoint_name,
            "istio.io/dataplane-mode": "ambient",
            "charms.canonical.com/istio.io.waypoint.managed-by": f"{self._managed_labels}",
        }

        namespace.metadata.labels.update(labels_to_add)  # pyright: ignore
        self._patch_namespace(namespace)

    def _remove_labels(self):
        """Remove specific labels from the namespace."""
        namespace = self._get_namespace()
        if not namespace:
            raise RuntimeError(f"Error fetching namespace: {namespace}")

        if namespace.metadata and namespace.metadata.labels:
            if (
                namespace.metadata.labels.get("charms.canonical.com/istio.io.waypoint.managed-by")
                != f"{self._managed_labels}"
            ):
                logger.warning(
                    f"Cannot remove labels: Namespace '{self.model.name}' has Istio labels managed by another entity."
                )
                return

            labels_to_remove = {
                "istio.io/use-waypoint": None,
                "istio.io/dataplane-mode": None,
                "charms.canonical.com/istio.io.waypoint.managed-by": None,
            }

            namespace.metadata.labels.update(labels_to_remove)
            self._patch_namespace(namespace)

    def mesh_labels(self):
        """Labels required for a workload to join the mesh."""
        if self.config["model-on-mesh"]:
            return {}
        return {
            "istio.io/dataplane-mode": "ambient",
            "istio.io/use-waypoint": self._waypoint_name,
            "istio.io/use-waypoint-namespace": self.model.name,
        }

    @staticmethod
    def format_labels(label_dict: Dict[str, str]) -> str:
        """Format a dictionary into a comma-separated string of key=value pairs."""
        return ",".join(f"{key}={value}" for key, value in label_dict.items())


def _get_peer_identity_for_juju_application(app_name, namespace):
    """Return a Juju application's peer identity.

    Format returned is defined by `principals` in
    [this reference](https://istio.io/latest/docs/reference/config/security/authorization-policy/#Source):

    This function relies on the Juju convention that each application gets a ServiceAccount of the same name in the same
    namespace.
    """
    service_account = app_name
    return _get_peer_identity_for_service_account(service_account, namespace)


def _get_peer_identity_for_service_account(service_account, namespace):
    """Return a ServiceAccount's peer identity.

    Format returned is defined by `principals` in
    [this reference](https://istio.io/latest/docs/reference/config/security/authorization-policy/#Source):
        "cluster.local/ns/{namespace}/sa/{service_account}"
    """
    return f"cluster.local/ns/{namespace}/sa/{service_account}"


if __name__ == "__main__":
    ops.main(IstioBeaconCharm)  # type: ignore
