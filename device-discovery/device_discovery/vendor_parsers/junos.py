from device_discovery.vendor_parsers.base import VendorParser

class JuneOSParser(VendorParser):
    
    def collect_interfaces_vlans(device_driver):
        return super().collect_interfaces_vlans()