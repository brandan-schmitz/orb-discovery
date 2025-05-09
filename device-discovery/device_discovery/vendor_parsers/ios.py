import logging
import re

from napalm.ios import IOSDriver
from device_discovery.vendor_parsers.base import VendorParser
from device_discovery.vendor_parsers import parser_models

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class IOSParser(VendorParser):
    
    def collect_interfaces_vlans(self, device_driver: IOSDriver):
        try: 
            # Get the output of the show interfaces switchport command on the device
            raw_interfaces = device_driver.cli(commands=["show interfaces switchport"])["show interfaces switchport"].strip()
        
            # Split the output into individual interface blocks. Each interface block starts with Name: <interface name>
            interface_blocks: list[str] = re.findall(r"^Name: .+?(?=^Name: |\Z)", raw_interfaces, re.DOTALL | re.MULTILINE)

            # Iterate through the list of interface blocks and parse the information from them
            interface_vlans: dict[str, parser_models.InterfaceVlans] = dict()
            for block in interface_blocks:
                parsed = {}
                
                # Convert each line into a key/value dict pair
                for line in block.strip().splitlines():
                    match = re.match(r"^(.+?):\s+(.*)$", line)
                    if match:
                        key, value = match.groups()
                        parsed[key.strip()] = value.strip()
                        
                # Get the name and ensure it is parsed out to the full length name
                name: str = parsed.get("Name", "")
                if name.startswith("Gi"):
                    name = name.replace("Gi", "GigabitEthernet", 1)
                elif name.startswith("Fa"):
                        name = name.replace("Fa", "FastEthernet", 1)
                elif name.startswith("Te"):
                    name = name.replace("Te", "TenGigabitEthernet", 1)
                
                # Determine the mode the port is running in
                mode = "access"
                admin_mode = parsed.get("Administrative Mode", "").lower()
                oper_mode = parsed.get("Operational Mode", "").lower()
                voice_vlan = parsed.get("Voice VLAN", "").lower()
                
                logger.info(f"Interface {name} Voice Vlan: {voice_vlan}")
                
                if admin_mode in ["dynamic auto", "dynamic desirable"]:
                    mode = "tagged" if oper_mode == "trunk" else "access"
                elif admin_mode == "static access":
                    mode = "access"
                elif admin_mode == "trunk":
                    mode = "tagged"
                elif voice_vlan != "none":
                    mode = "voice"
                else:
                    logger.warning(f"Unable to determine mode for interface {name} on {device_driver.hostname}")
                    continue
                
                # Get the access mode vlan. Ensure we are returning only the number
                access_vlan_match = re.match(r"(\d+)", parsed.get("Access Mode VLAN", ""))
                access_vlan = int(access_vlan_match.group(1)) if access_vlan_match else None
                
                # Get the trunk vlans. If the word ALL is present then simply return that. Otherwise return
                # an expanded list of the vlans allowed to be trunked
                tagged_vlans_raw: str = parsed.get("Trunking VLANs Enabled", "")
                tagged_vlans: list[int | str] = []
                if tagged_vlans_raw.strip().upper() == "ALL":
                    tagged_vlans = ["ALL"]
                    if mode == "tagged":
                        mode = "tagged-all"
                else:
                    for part in tagged_vlans_raw.split(","):
                        part = part.strip()
                        if "-" in part:
                            start, end = part.split("-")
                            tagged_vlans.extend(range(int(start), int(end) + 1))
                        elif part:
                            tagged_vlans.append(int(part))
                
                # Get the native vlan
                native_vlan_match = re.match(r"(\d+)", parsed.get("Trunking Native Mode VLAN", ""))
                native_vlan = int(native_vlan_match.group(1)) if native_vlan_match else None
                
                # Override tagged_vlans and native_vlan for voice mode
                if mode == "voice":
                    tagged_vlans = [int(re.match(r"(\d+)", voice_vlan).group(1))]
                    native_vlan = access_vlan
                
                # Get if trunk mode has a native vlan enabled
                tagged_native: bool = str(parsed.get("Administrative Native VLAN tagging", "")).lower() == "enabled"
                
                # Add this interface's parsed information
                interface_vlans[name] = parser_models.InterfaceVlans(
                    mode=mode,
                    access_vlan_id=access_vlan,
                    native_vlan_id=native_vlan,
                    tagged_vlan_ids=tagged_vlans,
                    native_vlan_enabled=tagged_native
                )
        
            return interface_vlans
        
        except Exception:
            logger.exception("An error occured in IOSParser.collect_interfaces_vlans()")