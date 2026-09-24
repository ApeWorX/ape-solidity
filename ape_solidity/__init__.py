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


def __getattr__(name: str):
    if name == "Extension":
        from ._utils import Extension

        return Extension

    if name == "SolidityCompiler":
        from .compiler import SolidityCompiler

        return SolidityCompiler

    if name == "SolidityConfig":
        from .compiler import SolidityConfig

        return SolidityConfig

    raise AttributeError(name)


__all__ = [
    "Extension",
    "SolidityCompiler",
    "SolidityConfig",
]
