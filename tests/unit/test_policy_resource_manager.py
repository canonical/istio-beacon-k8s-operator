# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from charms.istio_beacon_k8s.v0.service_mesh import (
    POLICY_RESOURCE_TYPES,
    Endpoint,
    MeshPolicy,
    MeshType,
    PolicyResourceManager,
    PolicyTargetType,
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


@patch('charms.istio_beacon_k8s.v0.service_mesh.KubernetesResourceManager')
def test_policy_resource_manager_init_with_istio_mesh_type(mock_krm, mock_charm, mock_lightkube_client):
    """Test PolicyResourceManager uses correct resource types when mesh_type is istio."""
    _ = PolicyResourceManager(
        charm=mock_charm,
        lightkube_client=mock_lightkube_client,
        mesh_type=MeshType.istio,
    )

    # Check that KRM was called with istio resource types
    mock_krm.assert_called_once()
    call_kwargs = mock_krm.call_args[1]
    assert call_kwargs['resource_types'] == POLICY_RESOURCE_TYPES[MeshType.istio]


@patch('charms.istio_beacon_k8s.v0.service_mesh.KubernetesResourceManager')
def test_policy_resource_manager_init_without_mesh_type(mock_krm, mock_charm, mock_lightkube_client):
    """Test PolicyResourceManager uses all resource types when mesh_type is None."""
    _ = PolicyResourceManager(
        charm=mock_charm,
        lightkube_client=mock_lightkube_client,
        mesh_type=None,
    )

    # Check that KRM was called with all supported resource types
    mock_krm.assert_called_once()
    call_kwargs = mock_krm.call_args[1]

    # Should contain all resources from all mesh types
    expected_resources = set()
    for mesh_resources in POLICY_RESOURCE_TYPES.values():
        expected_resources.update(mesh_resources)

    assert call_kwargs['resource_types'] == expected_resources


def test_policy_resource_manager_reconcile_without_mesh_type_raises_error(mock_charm, mock_lightkube_client):
    """Test reconcile raises ValueError when mesh_type is None."""
    prm = PolicyResourceManager(
        charm=mock_charm,
        lightkube_client=mock_lightkube_client,
        mesh_type=None,
    )

    policies = [
        MeshPolicy(
            source_namespace="source-ns",
            source_app_name="source-app",
            target_namespace="target-ns",
            target_app_name="target-app",
            target_type=PolicyTargetType.app,
            endpoints=[Endpoint(ports=[80])]
        )
    ]

    with pytest.raises(ValueError, match="cannot reconcile policies for a None mesh_type"):
        prm.reconcile(policies)


def test_policy_resource_manager_delete_handles_404_error(mock_charm, mock_lightkube_client):
    """Test delete method handles 404 errors gracefully when ignore_missing=True."""
    with patch('charms.istio_beacon_k8s.v0.service_mesh.KubernetesResourceManager'):
        prm = PolicyResourceManager(
            charm=mock_charm,
            lightkube_client=mock_lightkube_client,
            mesh_type=MeshType.istio,
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
