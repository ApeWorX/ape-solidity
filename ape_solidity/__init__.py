from ape import plugins

from .compiler import Extension, SolidityCompiler, SolidityConfig
from ._utils import StandardErrors


@plugins.register(plugins.Config)
def config_class():
    return SolidityConfig


@plugins.register(plugins.CompilerPlugin)
def register_compiler():
    return (Extension.SOL.value,), SolidityCompiler
