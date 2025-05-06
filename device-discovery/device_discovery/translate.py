#!/usr/bin/env python
# Copyright 2024 NetBox Labs Inc
"""Translate from NAPALM output format to Diode SDK entities."""

import ipaddress
from collections.abc import Iterable

from netboxlabs.diode.sdk.ingester import (
    VLAN,
    Device,
    DeviceType,
    Entity,
    Interface,
    IPAddress,
    Platform,
    Prefix,
)
import netboxlabs.diode.sdk.diode.v1.ingester_pb2 as pb

from device_discovery.policy.models import Defaults


def int32_overflows(number: int) -> bool:
    """
    Check if an integer is overflowing the int32 range.

    Args:
    ----
        number (int): The integer to check.

    Returns:
    -------
        bool: True if the integer is overflowing the int32 range, False otherwise.

    """
    INT32_MIN = -2147483648
    INT32_MAX = 2147483647
    return not (INT32_MIN <= number <= INT32_MAX)


def get_param(overrides, defaults, section: str, attr: str = None):
    """
    Retrieve a parameter from overrides or defaults with fallback logic.

    Args:
        overrides: The overrides model instance.
        defaults: The defaults model instance.
        section (str): The section name (e.g., "device", "vlan", "ipaddress", "prefix", "interface", or "site").
        attr (str, optional): The attribute to fetch within the section. If None, assumes section itself is the field.

    Returns:
        The first non-"undefined" value from overrides, then defaults, or None.
    """
    # Special case handling for top-level tags
    if attr == "tags":
        tags = (defaults.tags or [])[:]  # Start with top-level default tags
        if section:  # If section is specified, look for section-specific tags
            section_default = getattr(defaults, section, None)
            section_override = getattr(overrides, section, None)

            # Add section-specific default tags (device, interface, prefix, etc.)
            if section_default and section_default.tags:
                tags.extend(section_default.tags)
            
            # Override tags with the section's override value
            if section_override and section_override.tags:
                return list(section_override.tags)  # Full override if present
        
        # Return merged tags if found, otherwise None
        return tags if tags else None
    
    # Handle standard non-tags attributes (device, interface, etc.)
    section_override = getattr(overrides, section, None) if section else None
    section_default = getattr(defaults, section, None) if section else None

    if attr is None:
        override_val = section_override
        default_val = section_default
    else:
        override_val = getattr(section_override, attr, None) if section_override else None
        default_val = getattr(section_default, attr, None) if section_default else None

    # Prioritize override value, then default, and finally None
    if override_val not in (None, "undefined"):
        return override_val
    if default_val not in (None, "undefined"):
        return default_val
    if override_val == "undefined" or default_val == "undefined":
        return "undefined"
    return None


def translate_device(device_info: dict, defaults: Defaults, overrides: Defaults) -> Device:
    """
    Translate device information from NAPALM format to Diode SDK Device entity.

    Args:
    ----
        device_info (dict): Dictionary containing device information.
        defaults (Defaults): Default configuration.
        overrides (Defaults): Default Overrides for this device.

    Returns:
    -------
        Device: Translated Device entity.

    """
    device_model = get_param(overrides, defaults, "device", "device_model") or device_info.get("model")
    role = get_param(overrides, defaults, "device", "role")
    description = get_param(overrides, defaults, "device", "description")
    comments = get_param(overrides, defaults, "device", "comments")
    site = get_param(overrides, defaults, "site")
    tags = get_param(overrides, defaults, "device", "tags")

    device = Device(
        name=device_info.get("hostname"),
        device_type=DeviceType(
            model=device_model,
            manufacturer=device_info.get("vendor")
        ),
        platform=Platform(
            name=device_info.get("driver"),
            manufacturer=device_info.get("vendor")
        ),
        role=role,
        serial=device_info.get("serial_number"),
        status="active",
        site=site,
        tags=tags,
        description=description,
        comments=comments,
    )
    return device


def translate_interface(
    device: Device, if_name: str, interface_info: dict, defaults: Defaults, overrides: Defaults
) -> Interface:
    """
    Translate interface information from NAPALM format to Diode SDK Interface entity.

    Args:
    ----
        device (Device): The device to which the interface belongs.
        if_name (str): The name of the interface.
        interface_info (dict): Dictionary containing interface information.
        defaults (Defaults): Default configuration.

    Returns:
    -------
        Interface: Translated Interface entity.

    """
    tags = get_param(overrides, defaults, "interface", "tags")
    description = get_param(overrides, defaults, "interface", "description")
    type = get_param(overrides, defaults, "interface", "type")

    description = interface_info.get("description", description)
    mac_address = interface_info.get("mac_address") if interface_info.get("mac_address") != "" else None

    interface = Interface(
        device=device,
        name=if_name,
        enabled=interface_info.get("is_enabled"),
        primary_mac_address=mac_address,
        description=description,
        tags=tags,
        type=type,
    )

    # Convert napalm interface speed from Mbps to Netbox Kbps
    speed = int(interface_info.get("speed")) * 1000
    if speed > 0 and not int32_overflows(speed):
        interface.speed = speed

    mtu = interface_info.get("mtu")
    if mtu > 0 and not int32_overflows(mtu):
        interface.mtu = mtu

    return interface


def translate_interface_ips(
    interface: Interface, interfaces_ip: dict, defaults: Defaults, overrides: Defaults
) -> Iterable[Entity]:
    """
    Translate IP address and Prefixes information for an interface.

    Args:
    ----
        interface (Interface): The interface entity.
        if_name (str): The name of the interface.
        interfaces_ip (dict): Dictionary containing interface IP information.
        defaults (Defaults): Default configuration.

    Returns:
    -------
        Iterable[Entity]: Iterable of translated IP address and Prefixes entities.

    """
    ip_tags = get_param(overrides, defaults, "ipaddress", "tags")
    ip_comments = get_param(overrides, defaults, "ipaddress", "comments")
    ip_description = get_param(overrides, defaults, "ipaddress", "description")
    ip_role = get_param(overrides, defaults, "ipaddress", "role")
    ip_tenant = get_param(overrides, defaults, "ipaddress", "tenant")
    ip_vrf = get_param(overrides, defaults, "ipaddress", "vrf")

    prefix_tags = get_param(overrides, defaults, "prefix", "tags")
    prefix_comments = get_param(overrides, defaults, "prefix", "comments")
    prefix_description = get_param(overrides, defaults, "prefix", "description")
    prefix_site = get_param(overrides, defaults, "prefix", "site")
    prefix_role = get_param(overrides, defaults, "prefix", "role")
    prefix_tenant = get_param(overrides, defaults, "prefix", "tenant")
    prefix_vrf = get_param(overrides, defaults, "prefix", "vrf")

    ip_entities = []

    for if_ip_name, ip_info in interfaces_ip.items():
        if interface.name == if_ip_name:
            for ip_version, default_prefix in (("ipv4", 32), ("ipv6", 128)):
                for ip, details in ip_info.get(ip_version, {}).items():
                    ip_address = f"{ip}/{details.get('prefix_length', default_prefix)}"
                    network = ipaddress.ip_network(ip_address, strict=False)
                    ip_entities.append(
                        Entity(
                            prefix=Prefix(
                                prefix=str(network),
                                scope_site=prefix_site,
                                vrf=prefix_vrf,
                                role=prefix_role,
                                tenant=prefix_tenant,
                                tags=prefix_tags,
                                comments=prefix_comments,
                                description=prefix_description,
                            )
                        )
                    )
                    ip_entities.append(
                        Entity(
                            ip_address=IPAddress(
                                address=ip_address,
                                assigned_object_interface=interface,
                                role=ip_role,
                                tenant=ip_tenant,
                                vrf=ip_vrf,
                                tags=ip_tags,
                                comments=ip_comments,
                                description=ip_description,
                            )
                        )
                    )

    return ip_entities


def translate_vlan(vid: str, vlan_name: str, defaults: Defaults, overrides: Defaults) -> VLAN:
    """
    Translate VLAN information for a given VLAN ID.

    Args:
    ----
        vid (str): VLAN ID.
        vlan_name (str): VLAN name.
        defaults (Defaults): Default configuration.

    """
    tags = get_param(overrides, defaults, "vlan", "tags")
    comments = get_param(overrides, defaults, "vlan", "comments")
    description = get_param(overrides, defaults, "vlan", "description")
    site = get_param(overrides, defaults, "vlan", "site")
    group = get_param(overrides, defaults, "vlan", "group")
    tenant = get_param(overrides, defaults, "vlan", "tenant")
    role = get_param(overrides, defaults, "vlan", "role")

    vlan = VLAN(
        vid=int(vid),
        name=vlan_name,
        site=site,
        group=group,
        tenant=tenant,
        role=role,
        tags=tags,
        comments=comments,
        description=description,
    )

    return vlan


def translate_data(data: dict) -> Iterable[Entity]:
    """
    Translate data from NAPALM format to Diode SDK entities.

    Args:
    ----
        data (dict): Dictionary containing data to be translated.

    Returns:
    -------
        Iterable[Entity]: Iterable of translated entities.

    """
    entities: list[pb.Entity] = []

    defaults = data.get("defaults", Defaults())
    overrides = data.get("overrides", Defaults())

    device_info = data.get("device", {})
    interfaces = data.get("interface", {})
    interfaces_ip = data.get("interface_ip", {})
    if device_info:
        device_info["driver"] = data.get("driver")
        device = translate_device(device_info, defaults, overrides)
        entities.append(Entity(device=device))

        for if_name, interface_info in interfaces.items():
            interface = translate_interface(device, if_name, interface_info, defaults, overrides)
            entities.append(Entity(interface=interface))
            entities.extend(translate_interface_ips(interface, interfaces_ip, defaults, overrides))

    if data.get("vlan"):
        for vid, vlan_info in data.get("vlan").items():
            vlan = translate_vlan(vid, vlan_info.get("name"), defaults, overrides)
            entities.append(Entity(vlan=vlan))

    if data.get("interface_vlans"):
        vlans = [e.vlan for e in entities if e.HasField("vlan")]
        entity_interfaces = [e.interface for e in entities if e.HasField("interface")]
        
        for if_name, interface_info in data.get("interface_vlans").items():
            matching_interface = next((iface for iface in entity_interfaces if iface.name == if_name), None)
        
            if matching_interface is None:
                continue  # No matching interface found, skip to next
            
            # Get list of VLAN IDs this interface is tagged with
            tagged_vlan_ids = interface_info.get("trunk_vlans", None)
            native_vlan_id = interface_info.get("native_vlan", None)
            access_vlan_id = interface_info.get("access_vlan", None)
            tagged_native_vlan = interface_info.get("tagged_native_vlan", None)
            port_mode = interface_info.get("mode", None)
            
            access_vlan = next((vlan for vlan in vlans if vlan.vid == access_vlan_id), None)
            
            if port_mode == "access":
                matching_interface.mode = "access"
                if access_vlan is not None:
                    matching_interface.untagged_vlan.CopyFrom(access_vlan)
            elif port_mode == "trunk":
                matching_interface.mode = "tagged"
                
                if tagged_vlan_ids == ["ALL"]:
                    matching_interface.mode = "tagged-all"
                else:
                    matching_interface.tagged_vlans.extend([vlan for vlan in vlans if vlan.vid in tagged_vlan_ids])
                    
                if tagged_native_vlan is not None and tagged_native_vlan is True:
                    matching_interface.untagged_vlan.CopyFrom(next(vlan for vlan in vlans if vlan.vid == native_vlan_id))
            
    return entities
