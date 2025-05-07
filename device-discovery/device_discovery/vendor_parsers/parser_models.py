from pydantic import BaseModel, Field

class InterfaceVlans(BaseModel):
    mode: str | None = Field(default=None, description="Interface mode")
    access_vlan_id: int | None = Field(default=None, description="Access VLAN ID")
    native_vlan_id: int | None = Field(default=None, description="Native VLAN ID")
    tagged_vlan_ids: list[int | str] | None = Field(default=None, description="Tagged VLAN IDs or ALL for all vlans")
    native_vlan_enabled: bool | None = Field(default=None, description="Native VLAN is enabled")