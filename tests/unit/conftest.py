#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from lightkube import Client


@pytest.fixture(autouse=True)
def mock_lightkube_client():
    """Global mock for the Lightkube Client to avoid loading kubeconfig in CI."""
    with patch.object(Client, "__init__", lambda self, *args, **kwargs: None):
        with patch.object(Client, "get"):
            with patch.object(Client, "patch"):
                yield
