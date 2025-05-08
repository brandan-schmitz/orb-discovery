from napalm.junos import JunOSDriver
from device_discovery.vendor_parsers.base import VendorParser

class JuneOSParser(VendorParser):
    
    def collect_interfaces_vlans(device_driver: JunOSDriver):
        return super().collect_interfaces_vlans()