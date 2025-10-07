# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from charms.istio_beacon_k8s.v0.service_mesh import (
    MeshType,
    PolicyResourceManager,
)
from ops import CharmBase


@pytest.fixture
def mock_charm():
    charm = MagicMock(spec=CharmBase)
    charm.app.name = "test-app"
    charm.model.name = "test-model"
    return charm


@pytest.fixture
def mock_lightkube_client():
    return MagicMock()


def test_policy_resource_manager_reconcile_empty_policies_calls_delete(mock_charm, mock_lightkube_client):
    """Test reconcile calls delete when policies list is empty."""
    with patch('charms.istio_beacon_k8s.v0.service_mesh.KubernetesResourceManager'):
        prm = PolicyResourceManager(
            charm=mock_charm,
            lightkube_client=mock_lightkube_client,
        )

        # Mock the _krm
        prm._krm = MagicMock()
        # Call reconcile with empty policies
        prm.reconcile([], MeshType.istio)
        # Should call delete instead of trying to build policies
        prm._krm.delete.assert_called_once()


def test_policy_resource_manager_delete_handles_404_error(mock_charm, mock_lightkube_client):
    """Test delete method handles 404 errors gracefully when ignore_missing=True."""
    with patch('charms.istio_beacon_k8s.v0.service_mesh.KubernetesResourceManager'):
        prm = PolicyResourceManager(
            charm=mock_charm,
            lightkube_client=mock_lightkube_client,
        )

        # Mock the _krm and logger
        prm._krm = MagicMock()
        prm.log = MagicMock()

        # Mock a 404 HTTP error
        mock_response = Mock()
        mock_response.status_code = 404
        http_error = httpx.HTTPStatusError("Not found", request=Mock(), response=mock_response)
        prm._krm.delete.side_effect = http_error

        # Should not raise an exception
        prm.delete(ignore_missing=True)

        prm.log.info.assert_called_once_with("CRD not found, skipping deletion")
