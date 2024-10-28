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
