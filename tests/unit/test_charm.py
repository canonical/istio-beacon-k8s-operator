#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Namespace
from ops.testing import Harness

from charm import IstioBeaconCharm


@pytest.fixture()
def harness():
    harness = Harness(IstioBeaconCharm)
    harness.set_model_name("istio-system")
    yield harness
    harness.cleanup()


def test_add_labels(harness: Harness[IstioBeaconCharm]):
    """Test the _add_labels method with namespace labeling logic."""
    harness.begin()
    charm = harness.charm

    mock_namespace = Namespace(
        metadata=ObjectMeta(
            name="istio-system",
            labels={
                "foo": "bar",
            },
        )
    )

    # Scenario #1: Namespace has other k8s labels with no istio labels
    # Expected: Positive Scenario, istio labels to be updated normally
    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:

        charm._add_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        mock_patch.assert_called_once_with(Namespace, "istio-system", mock_namespace)
        assert mock_namespace.metadata.labels == {
            "istio.io/use-waypoint": "istio-beacon-k8s-istio-system-waypoint",
            "istio.io/dataplane-mode": "ambient",
            "charms.canonical.com/istio.io.waypoint.managed-by": "istio-beacon-k8s-istio-system",
            "foo": "bar",
        }

    # Scenario #2: Namespace labels are managed by another entity
    # Expected: Negative Scenario, labels shouldn't be added
    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:
        mock_namespace.metadata.labels.clear()
        entity_managed_labels = {
            "istio.io/use-waypoint": "another-entity",
            "istio.io/dataplane-mode": "ambient",
        }
        mock_namespace.metadata.labels.update(entity_managed_labels)
        charm._add_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        mock_patch.assert_not_called()
        assert mock_namespace.metadata.labels == entity_managed_labels

    # Scenario #3: Namespace labels are managed by this charm
    # Expected: Positive Scenario, istio labels to be updated normally
    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:
        mock_namespace.metadata.labels.clear()
        istio_managed_labels = {
            "istio.io/use-waypoint": "istio-beacon-k8s-istio-system-waypoint",
            "istio.io/dataplane-mode": "ambient",
            "charms.canonical.com/istio.io.waypoint.managed-by": "istio-beacon-k8s-istio-system",
        }
        mock_namespace.metadata.labels.update(istio_managed_labels)
        charm._add_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        mock_patch.assert_called_once_with(Namespace, "istio-system", mock_namespace)
        assert mock_namespace.metadata.labels == istio_managed_labels

    # Scenario #4: Namespace has no labels configured, not even external k8s ones
    # Expected: Positive Scenario, istio labels to be updated normally
    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:
        mock_namespace.metadata.labels.clear()
        istio_managed_labels = {
            "istio.io/use-waypoint": "istio-beacon-k8s-istio-system-waypoint",
            "istio.io/dataplane-mode": "ambient",
            "charms.canonical.com/istio.io.waypoint.managed-by": "istio-beacon-k8s-istio-system",
        }
        charm._add_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        mock_patch.assert_called_once_with(Namespace, "istio-system", mock_namespace)
        assert mock_namespace.metadata.labels == istio_managed_labels


def test_remove_labels(harness: Harness[IstioBeaconCharm]):
    """Test the _remove_labels method with namespace labeling logic."""
    harness.begin()
    charm = harness.charm

    mock_namespace = Namespace(
        metadata=ObjectMeta(
            name="istio-system",
            labels={
                "istio.io/use-waypoint": "istio-beacon-k8s-istio-system-waypoint",
                "istio.io/dataplane-mode": "ambient",
                "charms.canonical.com/istio.io.waypoint.managed-by": "istio-beacon-k8s-istio-system",
                "foo": "bar",
            },
        )
    )

    # Scenario #1: Namespace labels are managed by this charm
    # Expected: Positive Scenario, istio labels to be removed
    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:

        charm._remove_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        mock_patch.assert_called_once_with(Namespace, "istio-system", mock_namespace)
        assert mock_namespace.metadata.labels == {
            "foo": "bar",
            "charms.canonical.com/istio.io.waypoint.managed-by": None,
            "istio.io/dataplane-mode": None,
            "istio.io/use-waypoint": None,
        }

    # Scenario #2: Namespace labels are managed by another entity
    # Expected: Negative Scenario, labels shouldn't be removed
    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:
        mock_namespace.metadata.labels.clear()
        entity_managed_labels = {
            "istio.io/use-waypoint": "another-entity",
            "istio.io/dataplane-mode": "ambient",
        }
        mock_namespace.metadata.labels.update(entity_managed_labels)
        charm._remove_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        mock_patch.assert_not_called()
        assert mock_namespace.metadata.labels == entity_managed_labels

    # Scenario #3: Namespace has some labels missing, but managed by this charm
    # Expected: Positive Scenario, existing istio labels to be removed
    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:
        mock_namespace.metadata.labels.clear()
        partial_labels = {
            "charms.canonical.com/istio.io.waypoint.managed-by": "istio-beacon-k8s-istio-system",
            "foo": "bar",
        }
        mock_namespace.metadata.labels.update(partial_labels)
        charm._remove_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        mock_patch.assert_called_once_with(Namespace, "istio-system", mock_namespace)
        assert mock_namespace.metadata.labels == {
            "foo": "bar",
            "charms.canonical.com/istio.io.waypoint.managed-by": None,
            "istio.io/dataplane-mode": None,
            "istio.io/use-waypoint": None,
        }

    # Scenario #4: Namespace has no labels configured at all
    # Expected: No operation is performed, as there are no labels to remove
    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:
        mock_namespace.metadata.labels.clear()
        charm._remove_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        mock_patch.assert_not_called()
        assert mock_namespace.metadata.labels == {}


def test_sync_waypoint_resources_add_labels(harness: Harness[IstioBeaconCharm]):
    """Test _sync_waypoint_resources when model-on-mesh is True."""
    harness.begin()
    harness.update_config({"model-on-mesh": True})
    charm = harness.charm

    with patch.object(charm, "_get_waypoint_resource_manager") as mock_krm, patch.object(
        charm, "_construct_waypoint"
    ) as mock_construct_waypoint, patch.object(
        charm, "_add_labels"
    ) as mock_add_labels, patch.object(
        charm, "_remove_labels"
    ) as mock_remove_labels:

        mock_krm.return_value.reconcile = MagicMock()
        mock_construct_waypoint.return_value = MagicMock()

        charm._sync_waypoint_resources()

        # Ensure resource manager and waypoint construction were called
        mock_krm.return_value.reconcile.assert_called_once()
        mock_construct_waypoint.assert_called_once()

        # Ensure add_labels is called since model-on-mesh is True
        mock_add_labels.assert_called_once()

        # Ensure remove_labels is not called
        mock_remove_labels.assert_not_called()


def test_sync_waypoint_resources_remove_labels(harness: Harness[IstioBeaconCharm]):
    """Test _sync_waypoint_resources when model-on-mesh is False."""
    harness.begin()
    harness.update_config({"model-on-mesh": False})
    charm = harness.charm

    with patch.object(charm, "_get_waypoint_resource_manager") as mock_krm, patch.object(
        charm, "_construct_waypoint"
    ) as mock_construct_waypoint, patch.object(
        charm, "_add_labels"
    ) as mock_add_labels, patch.object(
        charm, "_remove_labels"
    ) as mock_remove_labels:

        mock_krm.return_value.reconcile = MagicMock()
        mock_construct_waypoint.return_value = MagicMock()

        charm._sync_waypoint_resources()

        # Ensure resource manager and waypoint construction were called
        mock_krm.return_value.reconcile.assert_called_once()
        mock_construct_waypoint.assert_called_once()

        # Ensure remove_labels is called since model-on-mesh is False
        mock_remove_labels.assert_called_once()

        # Ensure add_labels is not called
        mock_add_labels.assert_not_called()
