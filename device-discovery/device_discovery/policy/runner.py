#!/usr/bin/env python
# Copyright 2024 NetBox Labs Inc
"""Device Discovery Policy Runner."""

import logging
import time
import uuid
import re
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from napalm import get_network_driver
from napalm.base.base import NetworkDriver

from device_discovery.client import Client
from device_discovery.discovery import discover_device_driver, supported_drivers
from device_discovery.metrics import get_metric
from device_discovery.policy.models import Config, Scope, Status

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PolicyRunner:
    """Policy Runner class."""

    def __init__(self):
        """Initialize the PolicyRunner."""
        self.name = ""
        self.scopes = dict[str, Scope]()
        self.config = None
        self.status = Status.NEW
        self.scheduler = BackgroundScheduler()

    def setup(self, name: str, config: Config, scopes: list[Scope]):
        """
        Set up the policy runner.

        Args:
        ----
            name: Policy name.
            config: Configuration data containing site information.
            scopes: scope data for the devices.

        """
        self.name = name.replace("\r\n", "").replace("\n", "")
        self.config = config

        if self.config is None:
            self.config = Config(defaults={})
        elif self.config.defaults is None:
            self.config.defaults = {}

        self.scheduler.start()
        set_telemetry = True
        for scope in scopes:
            sanitized_hostname = scope.hostname.replace("\r\n", "").replace("\n", "")
            if scope.driver and scope.driver not in supported_drivers:
                self.scheduler.shutdown()
                raise Exception(
                    f"Policy {self.name}, Hostname {sanitized_hostname}: specified driver '{scope.driver}' "
                    f"was not found in the current installed drivers list: {supported_drivers}."
                )

            if self.config.schedule is not None:
                logger.info(
                    f"Policy {self.name}, Hostname {sanitized_hostname}: Scheduled to run with '{self.config.schedule}'"
                )
                trigger = CronTrigger.from_crontab(self.config.schedule)
            else:
                logger.info(
                    f"Policy {self.name}, Hostname {sanitized_hostname}: One-time run"
                )
                trigger = DateTrigger(run_date=datetime.now() + timedelta(seconds=1))

            id = str(uuid.uuid4())
            self.scopes[id] = scope
            self.scheduler.add_job(
                self.run, id=id, trigger=trigger, args=[id, scope, self.config]
            )
            if set_telemetry:
                set_telemetry = False
                self.scheduler.add_job(
                    self.telemetry,
                    id=str(uuid.uuid4()),
                    trigger=trigger,
                )
            self.status = Status.RUNNING

        active_policies = get_metric("active_policies")
        if active_policies:
            active_policies.add(1, {"policy": self.name})

    def telemetry(self):
        """Telemetry job."""
        policy_executions = get_metric("policy_executions")
        if policy_executions:
            policy_executions.add(1, {"policy": self.name})

    def _discover_driver(self, scope: Scope, sanitized_hostname: str) -> bool:
        """
        Discover the device driver if not provided.

        Args:
        ----
            scope: Scope data for the device.
            sanitized_hostname: Sanitized hostname for logging.

        Returns:
        -------
            bool: True if driver discovery succeeded or wasn't needed, False otherwise.

        """
        if scope.driver is None:
            logger.info(
                f"Policy {self.name}, Hostname {sanitized_hostname}: Driver not informed, discovering it"
            )
            scope.driver = discover_device_driver(scope)
            if scope.driver is None:
                self.status = Status.FAILED
                logger.error(
                    f"Policy {self.name}, Hostname {sanitized_hostname}: Not able to discover device driver"
                )
                return False
        return True

    def _collect_ios_interfaces_vlans(self, device: NetworkDriver):
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
                    "access_vlan": int | the vlan that is set as the access vlan
                    "trunk_vlans": [] | the list of vlans that the port is trunking. If none are defined explicitly then it is ["ALL"]
                    "native_vlan": int | the vlan the port uses as its native vlan when in trunking mode
                    "tagged_native_vlan": bool | if the port is configured to have a native vlan when in trunk mode
                }
            ]
        """
        # Get the output of the show interfaces switchport command on the device
        raw_interfaces = device.cli(commands=["show interfaces switchport"])["show interfaces switchport"].strip()
    
        # Split the output into individual interface blocks. Each interface block starts with Name: <interface name>
        interface_blocks = re.findall(r"^Name: .+?(?=^Name: |\Z)", raw_interfaces, re.DOTALL | re.MULTILINE)

        # Iterate through the list of interface blocks and parse the information from them
        interface_vlans_parsed = {}
        for block in interface_blocks:
            parsed = {}
            
            # Convert each line into a key/value dict pair
            for line in block.strip().splitlines():
                match = re.match(r"^(.+?):\s+(.*)$", line)
                if match:
                    key, value = match.groups()
                    parsed[key.strip()] = value.strip()
                    
            # Get the name and ensure it is parsed out to the full length name
            name = parsed.get("Name", "")
            if name.startswith("Gi"):
                name = name.replace("Gi", "GigabitEthernet", 1)
            elif name.startswith("Fa"):
                    name = name.replace("Fa", "FastEthernet", 1)
            elif name.startswith("Te"):
                name = name.replace("Te", "TenGigabitEthernet", 1)
            
            # Determine the mode the port is running in
            mode = "unknown"
            admin_mode = parsed.get("Administrative Mode", "").lower()
            oper_mode = parsed.get("Operational Mode", "").lower()
            
            if admin_mode in ["dynamic auto", "dynamic desirable"]:
                mode = "trunk" if oper_mode == "trunk" else "access"
            elif admin_mode == "static access":
                mode = "access"
            elif admin_mode == "trunk":
                mode = "trunk"
            
            # Get the access mode vlan. Ensure we are returning only the number
            access_vlan_match = re.match(r"(\d+)", parsed.get("Access Mode VLAN", ""))
            access_vlan = int(access_vlan_match.group(1)) if access_vlan_match else None
            
            # Get the trunk vlans. If the word ALL is present then simply return that. Otherwise return
            # an expanded list of the vlans allowed to be trunked
            trunk_vlans_raw = parsed.get("Trunking VLANs Enabled", "")
            trunk_vlans = []
            if trunk_vlans_raw.strip().upper() == "ALL":
                trunk_vlans = ["ALL"]
            else:
                for part in trunk_vlans_raw.split(","):
                    part = part.strip()
                    if "-" in part:
                        start, end = part.split("-")
                        trunk_vlans.extend(range(int(start), int(end) + 1))
                    elif part:
                        trunk_vlans.append(int(part))
            
            # Get the native vlan
            native_vlan_match = re.match(r"(\d+)", parsed.get("Trunking Native Mode VLAN", ""))
            native_vlan = int(native_vlan_match.group(1)) if native_vlan_match else None
            
            # Get if trunk mode has a native vlan enabled
            tagged_native = parsed.get("Administrative Native VLAN tagging", "").lower() == "enabled"
            
            # Add this interface's parsed information
            interface_vlans_parsed[name] = {
                "mode": mode,
                "access_vlan": access_vlan,
                "trunk_vlans": trunk_vlans,
                "native_vlan": native_vlan,
                "tagged_native_vlan": tagged_native
            }
        
        return interface_vlans_parsed
        

    def _collect_device_data(
        self, scope: Scope, sanitized_hostname: str, config: Config
    ):
        """
        Connect to device and collect data.

        Args:
        ----
            scope: Scope data for the device.
            sanitized_hostname: Sanitized hostname for logging.
            config: Configuration data containing site information.

        """
        np_driver = get_network_driver(scope.driver)
        logger.info(
            f"Policy {self.name}, Hostname {sanitized_hostname}: Getting information"
        )

        # Measure device connection time
        connection_start_time = time.perf_counter()
        with np_driver(
            scope.hostname,
            scope.username,
            scope.password,
            scope.timeout,
            scope.optional_args,
        ) as device:
            connection_duration = (time.perf_counter() - connection_start_time) * 1000
            device_connection_latency = get_metric("device_connection_latency")
            if device_connection_latency:
                device_connection_latency.record(
                    connection_duration,
                    {
                        "policy": self.name,
                        "hostname": sanitized_hostname,
                        "driver": scope.driver,
                    },
                )
                
            data = {
                "driver": scope.driver,
                "device": device.get_facts(),
                "interface": device.get_interfaces(),
                "interface_ip": device.get_interfaces_ip(),
                "defaults": config.defaults,
                "overrides": scope.default_overrides
            }
            try:
                data["vlan"] = device.get_vlans()
            except Exception as e:
                logger.error(
                    f"Policy {self.name}, Hostname {sanitized_hostname}: Error getting VLANs: {e}"
                )
                
            if scope.driver == "ios":
                data["interface_vlans"] = self._collect_ios_interfaces_vlans(device)
                
            Client().ingest(scope.hostname, data)
            discovery_success = get_metric("discovery_success")
            if discovery_success:
                discovery_success.add(1, {"policy": self.name})

    def run(self, id: str, scope: Scope, config: Config):
        """
        Run the device driver code for a single scope item.

        Args:
        ----
            id: Job ID.
            scope: scope data for the device.
            config: Configuration data containing site information.

        """
        discovery_start_time = time.perf_counter()
        sanitized_hostname = scope.hostname.replace("\r\n", "").replace("\n", "")

        # Try to discover driver if needed
        if not self._discover_driver(scope, sanitized_hostname):
            try:
                self.scheduler.remove_job(id)
            except Exception as e:
                logger.error(
                    f"Policy {self.name}, Hostname {sanitized_hostname}: Error removing job: {e}"
                )
            return

        logger.info(
            f"Policy {self.name}, Hostname {sanitized_hostname}: Get driver '{scope.driver}'"
        )

        try:
            discovery_attempts = get_metric("discovery_attempts")
            if discovery_attempts:
                discovery_attempts.add(1, {"policy": self.name})

            # Collect data from device
            self._collect_device_data(scope, sanitized_hostname, config)

            # Record total discovery duration
            discovery_latency = get_metric("discovery_latency")
            if discovery_latency:
                discovery_duration = (time.perf_counter() - discovery_start_time) * 1000
                discovery_latency.record(
                    discovery_duration,
                    {
                        "policy": self.name,
                        "hostname": sanitized_hostname,
                        "driver": scope.driver,
                    },
                )

        except Exception as e:
            discovery_failure = get_metric("discovery_failure")
            if discovery_failure:
                discovery_failure.add(1, {"policy": self.name})
            logger.error(f"Policy {self.name}, Hostname {sanitized_hostname}: {e}")

            # Still record discovery duration on failure
            discovery_latency = get_metric("discovery_latency")
            if discovery_latency:
                discovery_duration = (time.perf_counter() - discovery_start_time) * 1000
                discovery_latency.record(
                    discovery_duration,
                    {
                        "policy": self.name,
                        "hostname": sanitized_hostname,
                        "driver": str(scope.driver),
                        "status": "failed",
                    },
                )

    def stop(self):
        """Stop the policy runner."""
        self.scheduler.shutdown()
        active_policies = get_metric("active_policies")
        if active_policies:
            active_policies.add(-1, {"policy": self.name})
        self.status = Status.FINISHED
