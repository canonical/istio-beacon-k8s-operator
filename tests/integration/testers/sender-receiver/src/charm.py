#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging

import ops
import requests
from charms.istio_beacon_k8s.v0.service_mesh import Endpoint, Policy, ServiceMeshRequirer
from ops import BlockedStatus
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class IPARequirerMock(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self._ports = [8080, 8081]
        self.unit.set_ports(*self._ports)

        try:
            self._mesh = ServiceMeshRequirer(
                self,
                policies=[
                    Policy(
                        relation="inbound",
                        endpoints=[
                            Endpoint(
                                ports=self._ports,
                                methods=["GET", "POST"],
                                paths=["/foo", "/bar/"],
                            ),
                        ],
                    ),
                ],
            )
        except ops.TooManyRelatedAppsError as e:
            self.unit.status = BlockedStatus(e)

        self.framework.observe(self.on.echo_server_pebble_ready, self.on_pebble_ready)
        self.framework.observe(self.on["outbound"].relation_changed, self.send_to_outbound)
        self.framework.observe(self.on["inbound"].relation_changed, self.on_inbound_changed)
        self.framework.observe(self.on.update_status, self.send_to_outbound)
        # having a config_changed event makes it easy to proc the send_to_outbound
        self.framework.observe(self.on.config_changed, self.send_to_outbound)

    def on_pebble_ready(self, _):
        container = self.unit.get_container("echo-server")
        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble ready")
            return

        layer = Layer(
            {
                "summary": "echo server layer",
                "description": "pebble config layer for echo server",
                "services": {
                    f"echo-server-{i}": {
                        "override": "replace",
                        "command": "/bin/echo-server",
                        "startup": "enabled",
                        "environment": {
                            "PORT": str(port)
                        }
                    } for i, port in enumerate(self._ports)
                },
            }
        )

        container.add_layer("echo-server", layer, combine=True)
        container.autostart()
        self.unit.status = ActiveStatus("Echo server running")

    def on_inbound_changed(self, event):
        for relation in self.model.relations["inbound"]:
            # Send our details so they can talk to us
            data = {
                "name": self.app.name,
                "namespace": self.model.name,
                "ports": str(self._ports)
            }
            for k, v in data.items():
                logger.error(f"doing k={k}, v={v}")
                relation.data[self.app][k] = v

        self.unit.status = ActiveStatus("passed on_inbound_changed")

    def send_to_outbound(self, event):
        logger.info(f"Sending to outbound with self.model.relations['outbound']: {self.model.relations['outbound']}")
        for relation in self.model.relations["outbound"]:
            logger.info(f"Processing outbound relation to {relation.name}")
            if not relation.data:
                continue
            name = relation.data[relation.app].get("name")
            namespace = relation.data[relation.app].get("namespace")
            ports = relation.data[relation.app].get("ports")
            if not all([name, namespace, ports]):
                continue

            go_active = True
            urls = []
            for port in json.loads(ports):

                url = f"http://{name}.{namespace}.svc.cluster.local:{port}/foo"
                logger.info(f"Sending to {url}")

                try:
                    resp = requests.get(url)
                    resp.raise_for_status()
                    msg = f"Sent to {url}: {resp.status_code}"
                    urls.append(url)
                    logger.info(msg)
                except:
                    msg = f"Failed to send to {url}: {resp.status_code}"
                    logger.error(msg)
                    self.unit.status = BlockedStatus(msg)
                    # set go_active=False so that we don't go to active later.  We only preserve the most recent Blocked
                    # status this way, but that's fine.
                    go_active = False

            if go_active:
                msg = f"Sent to {urls} successfully"
                self.unit.status = ActiveStatus(msg)


if __name__ == "__main__":
    main(IPARequirerMock)
