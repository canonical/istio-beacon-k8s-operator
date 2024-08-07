# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import scenario
from charm import IstioBeaconCharm

# TODO: introduce mocks needed for testing model-on-mesh
def test_relation_changed_status():
    ctx = scenario.Context(IstioBeaconCharm)
    out = ctx.run('start', scenario.State())
    assert out.unit_status.name == "unknown"
