#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import pytest
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
    await ops_test.model.deploy(**asdict(ISTIO_K8S))
    await ops_test.model.wait_for_idle([ISTIO_K8S.application_name], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, istio_beacon_charm):
    # Not the model name just an alias
    await ops_test.track_model("beacon")
    istio_beacon = ops_test.models.get("beacon")
    (await istio_beacon.model.deploy(istio_beacon_charm, application_name=APP_NAME, trust=True),)
    await istio_beacon.model.wait_for_idle([APP_NAME], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_mesh_config(ops_test: OpsTest):
    # Not the model name just an alias
    istio_beacon = ops_test.models.get("beacon")
    await istio_beacon.model.applications[APP_NAME].set_config({"model-on-mesh": "true"})
    await istio_beacon.model.wait_for_idle(
        [APP_NAME], status="active", timeout=1000, raise_on_error=False
    )
    await validate_labels(istio_beacon, APP_NAME, should_be_present=True)

    await istio_beacon.model.applications[APP_NAME].set_config({"model-on-mesh": "false"})
    await istio_beacon.model.wait_for_idle(
        [APP_NAME], status="active", timeout=1000, raise_on_error=False
    )
    await validate_labels(istio_beacon, APP_NAME, should_be_present=False)
