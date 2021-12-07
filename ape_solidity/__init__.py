from ape import plugins

from .compiler import SolidityCompiler, SolidityConfig


@plugins.register(plugins.Config)
def config_class():
    return SolidityConfig


@plugins.register(plugins.CompilerPlugin)
def register_compiler():
    return (".sol",), SolidityCompiler
