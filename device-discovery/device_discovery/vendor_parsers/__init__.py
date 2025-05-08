import inspect
import importlib

from typing import Type
from device_discovery.vendor_parsers.base import VendorParser

def get_vendor_parser(name: str) -> Type[VendorParser]:
    if not (isinstance(name, str) and len(name) > 0):
        raise Exception("Please provide a valid parser name.")
    
    # Only lowercase allowed
    # Try to not raise error when users requests IOS-XR for e.g.
    name = name.lower().replace("-", "")
    
    try:
        module = importlib.import_module(f"device_discovery.vendor_parsers.{name}")
    except ImportError as e:
        raise ImportError(f'Cannot import module device_discovery.vendor_parsers.{name}')

    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and issubclass(obj, VendorParser):
            return obj()
    
    raise LookupError(f'No subclass of VendorParsers found in device_discovery.vendor_parsers.{name}')