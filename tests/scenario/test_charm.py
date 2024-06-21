# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import scenario
from charm import IstioBeaconCharm


def test_relation_changed_status():
    ctx = scenario.Context(IstioBeaconCharm)
    rel = scenario.Relation(endpoint="service-mesh", interface="service_mesh")
    out = ctx.run(rel.changed_event, scenario.State())
    assert out.unit_status.name == "active"
