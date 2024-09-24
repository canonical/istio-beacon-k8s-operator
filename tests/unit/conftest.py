#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from lightkube import Client


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
