#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""This module defines Pydantic schemas for various resources used in the Kubernetes Gateway API."""

from typing import Dict, List, Optional

from pydantic import BaseModel


# Global metadata schema
class Metadata(BaseModel):
    """Global metadata schema for Kubernetes resources."""

    name: str
    namespace: str
    labels: Optional[Dict[str, str]] = None
    annotations: Optional[Dict[str, str]] = None


class AllowedRoutes(BaseModel):
    """AllowedRoutes defines namespaces from which traffic is allowed."""

    namespaces: Dict[str, str]


class Listener(BaseModel):
    """Listener defines a port and protocol configuration."""

    name: str
    port: int
    protocol: str
    allowedRoutes: AllowedRoutes  # noqa: N815


class IstioWaypointSpec(BaseModel):
    """IstioWaypointSpec defines the specification of a waypoint."""

    gatewayClassName: str  # noqa: N815
    listeners: List[Listener]


class IstioWaypointResource(BaseModel):
    """IstioWaypointResource defines the structure of an waypoint Kubernetes resource."""

    metadata: Metadata
    spec: IstioWaypointSpec
