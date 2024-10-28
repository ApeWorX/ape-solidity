from typing import Any

from ape import plugins


@plugins.register(plugins.Config)
def config_class():
    from .compiler import SolidityConfig

    return SolidityConfig


@plugins.register(plugins.CompilerPlugin)
def register_compiler():
    from ._utils import Extension
    from .compiler import SolidityCompiler

    return (Extension.SOL.value,), SolidityCompiler


def __getattr__(name: str) -> Any:
    if name == "Extension":
        from ._utils import Extension

        return Extension

    elif name == "SolidityCompiler":
        from .compiler import SolidityCompiler

        return SolidityCompiler

    elif name == "SolidityConfig":
        from .compiler import SolidityConfig

        return SolidityConfig

    else:
        raise AttributeError(name)


__all__ = [
    "Extension",
    "SolidityCompiler",
    "SolidityConfig",
]
