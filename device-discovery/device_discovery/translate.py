#!/usr/bin/env python
# Copyright 2024 NetBox Labs Inc
"""Translate from NAPALM output format to Diode SDK entities."""

import logging
import ipaddress
import json
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
    CustomFieldValue,
    CustomFieldObjectReference
)

from netboxlabs.diode.sdk.diode.v1 import ingester_pb2 as pb

from device_discovery.policy.models import Defaults
from device_discovery.vendor_parsers import parser_models


from google.protobuf.json_format import MessageToDict

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    interface = Interface(
        device=device,
        name=if_name,
        enabled=interface_info.get("is_enabled"),
        primary_mac_address=interface_info.get("mac_address") if interface_info.get("mac_address") != "" else None,
        description=interface_info.get("description", get_param(overrides, defaults, "interface", "description")),
        tags=get_param(overrides, defaults, "interface", "tags"),
        type=get_param(overrides, defaults, "interface", "type"),
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
                                scope_site=get_param(overrides, defaults, "prefix", "site"),
                                vrf=get_param(overrides, defaults, "prefix", "vrf"),
                                role=get_param(overrides, defaults, "prefix", "role"),
                                tenant=get_param(overrides, defaults, "prefix", "tenant"),
                                tags=get_param(overrides, defaults, "prefix", "tags"),
                                comments=get_param(overrides, defaults, "prefix", "comments"),
                                description=get_param(overrides, defaults, "prefix", "description"),
                            )
                        )
                    )
                    ip_entities.append(
                        Entity(
                            ip_address=IPAddress(
                                address=ip_address,
                                assigned_object_interface=interface,
                                role=get_param(overrides, defaults, "ipaddress", "role"),
                                tenant=get_param(overrides, defaults, "ipaddress", "tenant"),
                                vrf=get_param(overrides, defaults, "ipaddress", "vrf"),
                                tags=get_param(overrides, defaults, "ipaddress", "tags"),
                                comments=get_param(overrides, defaults, "ipaddress", "comments"),
                                description=get_param(overrides, defaults, "ipaddress", "description"),
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
    vlan = VLAN(
        vid=int(vid),
        name=vlan_name.strip(),
        site=get_param(overrides, defaults, "vlan", "site"),
        group=get_param(overrides, defaults, "vlan", "group"),
        tenant=get_param(overrides, defaults, "vlan", "tenant"),
        role=get_param(overrides, defaults, "vlan", "role"),
        tags=get_param(overrides, defaults, "vlan", "tags"),
        comments=get_param(overrides, defaults, "vlan", "comments"),
        description=get_param(overrides, defaults, "vlan", "description"),
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
    try:
        entities: list[Entity] = []

        defaults = data.get("defaults", Defaults())
        overrides = data.get("overrides", Defaults())

        device_info = data.get("device", {})
        interfaces = data.get("interface", {})
        interfaces_ip = data.get("interface_ip", {})
        if device_info:
            device_info["driver"] = data.get("driver")
            device: pb.Device = translate_device(device_info, defaults, overrides)
            entities.append(Entity(device=device))

            for if_name, interface_info in interfaces.items():
                interface = translate_interface(device, if_name, interface_info, defaults, overrides)
                entities.append(Entity(interface=interface))
                entities.extend(translate_interface_ips(interface, interfaces_ip, defaults, overrides))

        if data.get("vlan"):
            for vid, vlan_info in data.get("vlan").items():
                vlan = translate_vlan(vid, vlan_info.get("name"), defaults, overrides)
                entities.append(Entity(vlan=vlan))
            
        if data.get("interfaces_vlans"):
            interfaces_vlans: dict[str, parser_models.InterfaceVlans] = data.get("interfaces_vlans")
            entity_vlans = [e.vlan for e in entities if e.HasField("vlan")]
            entity_interfaces = [e.interface for e in entities if e.HasField("interface")]
            
            logger.info("Interfaces VLANs: %s", json.dumps({k: v.model_dump() for k, v in interfaces_vlans.items()}, indent=2))
            
            # Helper ot get or create a VLAN if it does not exist
            def _get_or_create_vlan(id: int) -> VLAN:
                vlan = next((vlan for vlan in entity_vlans if vlan.vid == id), None)
                if vlan is None:
                    vlan = VLAN(
                        vid=id,
                        name=f"Undefined vlan {id} on device {device.name}",
                    )
                    entities.append(Entity(vlan=vlan))
                    entity_vlans.append(vlan)  # Add to local list so it's available for future matches
                    logger.warning(f"Undefined VLAN {id} for interface {if_name} on device {device.name}")
                return vlan
            
            voice_as_tagged = get_param(overrides, defaults, "interface", "voice_as_tagged")
            voice_cf_enabled = get_param(overrides, defaults, "interface", "voice_cf_enabled")
            
            logger.info(f"voice_as_tagged: {voice_as_tagged}")
            logger.info(f"voice_cf_enabled: {voice_cf_enabled}")
            
            for interface_name, interface_vlan_info in interfaces_vlans.items():
                # Attempt to match the interface name to an interface already created
                # Skip this one if it does not as that should not happen and something is weird
                matching_interface = next((iface for iface in entity_interfaces if iface.name == interface_name), None)
                if matching_interface is None:
                    continue
                
                interface_mode = interface_vlan_info.mode
                access_vlan_id = interface_vlan_info.access_vlan_id
                native_vlan_id = interface_vlan_info.native_vlan_id
                
                if interface_mode == "voice" and voice_as_tagged:
                    matching_interface.mode = "tagged"
                    matching_interface.untagged_vlan.CopyFrom(_get_or_create_vlan(native_vlan_id))
                    matching_interface.tagged_vlans.extend([_get_or_create_vlan(vid) for vid in interface_vlan_info.tagged_vlan_ids])
                    if voice_cf_enabled:
                        matching_interface.custom_fields["voice_vlan_enabled"].CopyFrom(CustomFieldValue(
                            boolean=True
                        ))
                elif interface_mode == "access" or (interface_mode == "voice" and not voice_as_tagged):
                    matching_interface.mode = "access"
                    matching_interface.untagged_vlan.CopyFrom(_get_or_create_vlan(access_vlan_id))
                elif interface_mode == "tagged":
                    matching_interface.mode = interface_mode
                    matching_interface.tagged_vlans.extend([_get_or_create_vlan(vid) for vid in interface_vlan_info.tagged_vlan_ids])
                elif interface_mode == "tagged-all" or interface_mode == "tagged" and interface_vlan_info.native_vlan_enabled and native_vlan_id is not None:
                    matching_interface.mode = interface_mode
                    matching_interface.untagged_vlan.CopyFrom(_get_or_create_vlan(native_vlan_id))
                
                
                logger.info("Matched Interface for: %s", MessageToDict(matching_interface))

        # Dakota Central customization for setting a list of VLANs
        # if any(entity.HasField("vlan") for entity in entities):
        #     device.custom_fields["device_global_vlans"].CopyFrom(CustomFieldValue(
        #         multiple_objects=[
        #             CustomFieldObjectReference(vlan=e.vlan)
        #             for e in entities if e.HasField("vlan")
        #         ]
        #     ))
        #     logger.info("Official Device: %s", MessageToDict(device))
        
        # Dakota Central customization for only shoing top-level interfaces in junos
        if data.get("driver") == "junos":
            for i in range(len(entities) - 1, -1, -1):
                entity: pb.Entity = entities[i]
                if entity.interface:
                    interface_name = entity.interface.name
                    print(f"Checking interface: {interface_name}")
                    
                    if '.' in interface_name:
                        entities.pop(i)
                        print(f"Removed entity with interface: {interface_name}")

            for entity in entities:
                if entity.interface:
                    print(f"Remaining entity with interface: {entity.interface.name}")
        
    except Exception as e:
        logger.error("Error caught in translate_data(): ", exc_info=True)
                        
    return entities