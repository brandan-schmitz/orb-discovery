import logging

from jnpr.junos import Device
from napalm.junos import JunOSDriver

from device_discovery.vendor_parsers.utils import junos_views
from device_discovery.vendor_parsers.base import VendorParser
from device_discovery.vendor_parsers import parser_models

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class JunOSParser(VendorParser):
    
    # This is adapted from a PR that was never pulled into Netpalm
    # https://github.com/napalm-automation/napalm/pull/1683
    def collect_interfaces_vlans(self, device_driver: JunOSDriver):
        try:
            interface_vlans: dict[str, parser_models.InterfaceVlans] = dict()

            switch_style = device_driver.device.facts["switch_style"]
            switch_version = float(device_driver.device.facts["version"][:4])
            
            logger.info(f"switch_style: {switch_style}")
            logger.info(f"switch_version: {switch_version}")

            if switch_style == "VLAN":
                table = junos_views.junos_iface_vlan_table(device_driver.device)
                table.get()

                for iface in table:
                    interface_mode = iface.mode.lower()
                    access_vlan = -1
                    tagged_vlans = []
                    native_vlan = -1
                    tagged_native_vlan = False

                    if isinstance(iface.vlans_id, list):
                        for i in range(len(iface.vlans_tag)):
                            if iface.vlans_tag[i] == "tagged":
                                tagged_vlans.append(int(iface.vlans_id[i]))

                        if iface.mode == "Access" and "tagged" in iface.vlans_tag:
                            interface_mode = "voice"
                            access_vlan = int(
                                iface.vlans_id[iface.vlans_tag.index("untagged")]
                            )
                            native_vlan = access_vlan
                        elif iface.mode == "Trunk" and "untagged" in iface.vlans_tag:
                            native_vlan = int(
                                iface.vlans_id[iface.vlans_tag.index("untagged")]
                            )
                            tagged_native_vlan = True

                    else:
                        if iface.mode == "Access":
                            if iface.vlans_id:
                                access_vlan = int(iface.vlans_id)
                            else:
                                continue
                        elif iface.mode == "Trunk":
                            tagged_vlans.append(int(iface.vlans_id))
                            
                    # Make sure mode is representative of netbox interface modes
                    if interface_mode == "trunk":
                        interface_mode = "tagged"
                            
                    interface_vlans[iface.name] = parser_models.InterfaceVlans(
                        mode=interface_mode,
                        access_vlan_id=access_vlan,
                        native_vlan_id=native_vlan,
                        tagged_vlan_ids=tagged_vlans,
                        native_vlan_enabled=tagged_native_vlan
                    )

            elif switch_style == "VLAN_L2NG" or switch_style == "BRIDGE_DOMAIN":
                if switch_version < 20.4:
                    table = junos_views.junos_iface_vlan_table_switch_l2ng_sub20_4(
                        device_driver.device
                    )
                else:
                    table = junos_views.junos_iface_vlan_table_switch_l2ng(device_driver.device)
                table.get()

                mode_table = junos_views.junos_iface_mode_switch_l2ng(device_driver.device)
                mode_table.get()

                iface_data = {}

                for iface in table:
                    if iface.name not in iface_data.keys():
                        iface_data[iface.name] = {"vlans_id": [], "vlans_tag": []}

                    if iface.vlans_id and iface.vlans_tag:
                        iface_data[iface.name]["vlans_id"].append(iface.vlans_id)
                        iface_data[iface.name]["vlans_tag"].append(iface.vlans_tag)

                for iface in mode_table:
                    if iface.mode != None and iface.name + ".0" in iface_data.keys():
                        iface_data[iface.name + ".0"]["mode"] = iface.mode

                for iface_name, data in iface_data.items():
                    interface_mode = "access"
                    access_vlan = -1
                    tagged_vlans = []
                    native_vlan = -1
                    tagged_native_vlan = False

                    for i in range(len(data["vlans_tag"])):
                        if data["vlans_tag"][i] == "tagged":
                            tagged_vlans.append(int(data["vlans_id"][i]))

                    if data["mode"] == "access":
                        interface_mode = "access"
                        access_vlan = int(
                            data["vlans_id"][data["vlans_tag"].index("untagged")]
                        )
                        if "tagged" in data["vlans_tag"]:
                            interface_mode = "voice"
                            native_vlan = access_vlan
                    elif data["mode"] == "trunk":
                        interface_mode = "tagged"
                        if "untagged" in data["vlans_tag"]:
                            native_vlan = int(
                                data["vlans_id"][data["vlans_tag"].index("untagged")]
                            )
                            tagged_native_vlan = True
                    
                    
                    interface_vlans[iface_name] = parser_models.InterfaceVlans(
                        mode=interface_mode,
                        access_vlan_id=access_vlan,
                        native_vlan_id=native_vlan,
                        tagged_vlan_ids=tagged_vlans,
                        native_vlan_enabled=tagged_native_vlan
                    )

            return interface_vlans
        
        except Exception as e:
            logger.error("Error in junos.collect_interfaces_vlans(): ", exc_info=True)