"""Installed computational CAE bridge with lazy compatibility exports."""

__all__ = [
    "CAEBridge",
    "CAEBridgeConfig",
    "CalculiXBridge",
    "CalculiXBridgeConfig",
    "register_cae_tools",
    "register_calculix_tools",
]


def __getattr__(name: str):
    if name in {"CAEBridge", "CAEBridgeConfig"}:
        from device_bridges.cae import bridge

        return getattr(bridge, name)
    if name in {"CalculiXBridge", "CalculiXBridgeConfig"}:
        from device_bridges.cae import calculix

        return getattr(calculix, name)
    if name == "register_cae_tools":
        from device_bridges.cae.tools import register_cae_tools

        return register_cae_tools
    if name == "register_calculix_tools":
        from device_bridges.cae.calculix_tools import register_calculix_tools

        return register_calculix_tools
    raise AttributeError(name)
