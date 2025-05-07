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
    
    for module_name in [
        name
    ]:
        try:
            module = importlib.import_module(module_name)
            break
        except ImportError as e:
            message = str(e)
            if "No module named" in message:
                failed_module = message.split()[-1]
                if failed_module.replace("'", "") in module_name:
                    continue
            raise e
    else:
        raise Exception(
            'Cannot import "{install_name}". Is the library installed?'.format(
                install_name=name
            )
        )
    
    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and issubclass(obj, VendorParser):
            return obj
    
    raise Exception(
        'No class inheriting "device_discovery.vendor_parsers.base.VendorParser" found in "{install_name}".'.format(
            install_name=name
        )
    )