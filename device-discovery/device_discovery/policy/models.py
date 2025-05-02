#!/usr/bin/env python
# Copyright 2024 NetBox Labs Inc
"""Device Discovery Policy Models."""

from enum import Enum
from typing import Any

from croniter import CroniterBadCronError, croniter
from pydantic import BaseModel, Field, field_validator


class Status(Enum):
    """Enumeration for status."""

    NEW = "new"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"

class ObjectParameters(BaseModel):
    """Model for object parameters."""

    comments: str | None = Field(default=None, description="Comments, optional")
    description: str | None = Field(default=None, description="Description, optional")
    tags: list[str] | None = Field(default=None, description="Tags, optional")

class DeviceParameters(ObjectParameters):
    """Model for device parameters"""
    
    device_model: str | None = Field(default=None, description="Device Model, optional")
    role: str | None = Field(default="undefined", description="Device role, optional")

class InterfaceParameters(ObjectParameters):
    """Model for interface parameters"""
    
    type: str | None = Field(default="other", description="Interface type, optional")

class VlanParameters(ObjectParameters):
    """Model for VLAN parameters."""

    site: str | None = Field(default=None, description="Site name, optional")
    group: str | None = Field(default=None, description="VLAN group, optional")
    tenant: str | None = Field(default=None, description="VLAN tenant, optional")
    role: str | None = Field(default=None, description="VLAN role, optional")

class IpamParameters(ObjectParameters):
    """Model for IPAM parameters."""

    site: str | None = Field(default=None, description="Site name, optional")
    role: str | None = Field(default=None, description="IPAM role, optional")
    tenant: str | None = Field(default=None, description="IPAM tenant, optional")
    vrf: str | None = Field(default=None, description="IPAM VRF, optional")

class Defaults(BaseModel):
    """Model for default configuration."""

    site: str | None = Field(default="undefined", description="Site name, optional")
    tags: list[str] | None = Field(default=None, description="Tags, optional")
    device: DeviceParameters | None = Field(default=None, description="Device parameters, optional")
    interface: InterfaceParameters | None = Field(default=None, description="Interface parameters, optional")
    ipaddress: IpamParameters | None = Field(default=None, description="IP Address parameters, optional")
    prefix: IpamParameters | None = Field(default=None, description="Prefix parameters, optional")
    vlan: VlanParameters | None = Field(default=None, description="VLAN parameters, optional")

class Scope(BaseModel):
    """Model for Individual scope configuration."""

    driver: str | None = Field(default=None, description="Driver name, optional")
    hostname: str
    username: str
    password: str
    timeout: int = 60
    optional_args: dict[str, Any] | None = Field(
        default=None, description="Optional arguments"),
    default_overrides: Defaults | None = Field(default=None, description="Override Defaults, optional")

class Config(BaseModel):
    """Model for discovery configuration."""

    schedule: str | None = Field(default=None, description="cron interval, optional")
    defaults: Defaults | None = Field(default=None, description="Default configuration, optional")

    @field_validator("schedule")
    @classmethod
    def validate_cron(cls, value):
        """
        Validate the cron schedule format.

        Args:
        ----
            value: The cron schedule value.

        Raises:
        ------
            ValueError: If the cron schedule format is invalid.

        """
        try:
            croniter(value)
        except CroniterBadCronError:
            raise ValueError("Invalid cron schedule format.")
        return value


class Policy(BaseModel):
    """Model for a policy configuration."""

    config: Config | None = Field(default=None, description="Configuration data")
    scope: list[Scope]


class PolicyRequest(BaseModel):
    """Model for a policy request."""

    policies: dict[str, Policy]
