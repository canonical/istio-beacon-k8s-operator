#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import pytest
import sh
import yaml
from helpers import validate_labels
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


@dataclass
class CharmDeploymentConfiguration:
    entity_url: str  # aka charm name or local path to charm
    application_name: str
    channel: str
    trust: bool
    config: Optional[dict] = None


ISTIO_K8S = CharmDeploymentConfiguration(
    entity_url="istio-k8s", application_name="istio-k8s", channel="latest/edge", trust=True
)


@pytest.mark.abort_on_fail
async def test_deploy_dependencies(ops_test: OpsTest):
    # Not the model name just an alias
    await ops_test.track_model("istio-system")
    istio_system_model = ops_test.models.get("istio-system")

    await istio_system_model.model.deploy(**asdict(ISTIO_K8S))
    await istio_system_model.model.wait_for_idle(
        [ISTIO_K8S.application_name], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, istio_beacon_charm):
    await ops_test.model.deploy(istio_beacon_charm, application_name=APP_NAME, trust=True),
    await ops_test.model.wait_for_idle([APP_NAME], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_mesh_config(ops_test: OpsTest):
    await ops_test.model.applications[APP_NAME].set_config({"model-on-mesh": "true"})
    await ops_test.model.wait_for_idle(
        [APP_NAME], status="active", timeout=1000, raise_on_error=False
    )
    await validate_labels(ops_test, APP_NAME, should_be_present=True)

    await ops_test.model.applications[APP_NAME].set_config({"model-on-mesh": "false"})
    await ops_test.model.wait_for_idle(
        [APP_NAME], status="active", timeout=1000, raise_on_error=False
    )
    await validate_labels(ops_test, APP_NAME, should_be_present=False)


@pytest.mark.abort_on_fail
async def test_service_mesh_relation(ops_test: OpsTest, sender_receiver_charm):
    # Ensure model is on mesh
    await ops_test.model.applications[APP_NAME].set_config({"model-on-mesh": "true"})

    # Deploy tester charms
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}
    # Applications that will be given authorization policies
    await ops_test.model.deploy(
        sender_receiver_charm, application_name="receiver1", resources=resources
    )
    await ops_test.model.deploy(
        sender_receiver_charm, application_name="sender1", resources=resources
    )
    await ops_test.model.add_relation("receiver1:service-mesh", APP_NAME)
    await ops_test.model.add_relation("receiver1:inbound", "sender1:outbound")

    await ops_test.model.wait_for_idle([APP_NAME])

    await ops_test.model.wait_for_idle(["receiver1", "sender1", "sender2"])

    await ops_test.model.wait_for_idle(
        [APP_NAME], status="active", timeout=1000, raise_on_error=False
    )

    # Assert that communication is correctly controlled
    # sender/0 can talk to receiver on any combination of:
    # * port: [8080, 8081]
    # * path: [/foo, /bar/]
    # * method: [GET, POST]
    # but not others
    assert get_code_for_request("sender1/0", "http://receiver1:8080/foo") == 200
    assert get_code_for_request("sender1/0", "http://receiver1:8081/foo") == 200
    assert get_code_for_request("sender1/0", "http://receiver1:8080/bar/") == 200
    assert get_code_for_request("sender1/0", "http://receiver1:8080/foo", method="post") == 200
    assert get_code_for_request("sender1/0", "http://receiver1:8080/foo", method="delete") == 403

    # other service accounts should get a 403 error
    assert get_code_for_request("sender2/0", "http://receiver1:8080/foo") == 403


def get_code_for_request(source_unit: str, target_url: str, method: str = "get") -> int:
    """Get the status code for a request from a source unit to a target URL on a given method.

    Note that if the request fails (ex: python script raises an exception) the exit code will be returned.
    """
    try:
        resp = sh.juju.ssh(
            source_unit,
            f'python3 -c "import requests; resp = requests.{method}(\\"{target_url}\\"); print(resp.status_code)"',
            _return_cmd=True,
        )
        return int(str(resp).strip())
    except sh.ErrorReturnCode as e:
        # Returns
        return e.exit_code
