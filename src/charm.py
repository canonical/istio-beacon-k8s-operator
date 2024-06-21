#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio Beacon Charm."""

import logging

import ops

logger = logging.getLogger(__name__)


class IstioBeaconCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self.on_start)
        self.framework.observe(self.on["service-mesh"].relation_changed, self.on_mesh_changed)

    def on_start(self, _event):
        """Event handler for start."""
        self.unit.status = ops.ActiveStatus()

    def on_mesh_changed(self, _event):
        """Event handler for service-mesh relation_changed."""
        self.update_mesh()

    def update_mesh(self):
        """Update the service mesh.

        Reads all relations and any config to generate a kubernetes manifest. Then applies the
        manifest.
        """
        for relation in self.model.relations["service-mesh"]:
            # Update the mesh
            pass
        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":
    ops.main(IstioBeaconCharm)  # type: ignore
