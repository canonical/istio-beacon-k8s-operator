#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from charms.tempo_coordinator_k8s.v0 import charm_tracing
from lightkube import Client


@pytest.fixture(autouse=True)
def charm_tracing_buffer_to_tmp(tmp_path):
    with patch.object(charm_tracing, "BUFFER_DEFAULT_CACHE_FILE_NAME", tmp_path):
        yield


@pytest.fixture(autouse=True)
def mock_lightkube_client(request):
    """Global mock for the Lightkube Client to avoid loading kubeconfig in CI."""
    # Skip this fixture if the test has explicitly disabled it.
    # To use this feature in a test, mark it with @pytest.mark.disable_lightkube_client_autouse
    if "disable_lightkube_client_autouse" in request.keywords:
        yield
    else:
        with patch.object(Client, "__init__", lambda self, *args, **kwargs: None):
            with patch.object(Client, "get"):
                with patch.object(Client, "patch"):
                    yield
