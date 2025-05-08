from napalm.base.base import NetworkDriver
from device_discovery.vendor_parsers import parser_models

class VendorParser(object):
    def __init__(self):
        pass

    def collect_interfaces_vlans(self, device_driver: NetworkDriver) -> dict[str, parser_models.InterfaceVlans]:
        """
        Discover what vlans each interface has, and if the interface is operating in a access or trunk mode.
        
        Args:
        ----
            device: The device drive built to connect to the device
        
        Returns:
        -------
            [
                "interface_name": {
                    "mode": string | either access or trunk
                    "access_vlan_id": int | the vlan that is set as the access vlan
                    "native_vlan_id": int | the vlan the port uses as its native vlan when in trunking mode
                    "tagged_vlan_ids": [] | the list of vlans that the port is trunking. If none are defined explicitly then it is ["ALL"]
                    "native_vlan_enabled": bool | if the port is configured to have a native vlan when in trunk mode
                }
            ]
        """
        raise NotImplementedError