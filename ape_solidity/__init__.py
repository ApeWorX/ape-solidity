from ape import plugins

from ._utils import Extension
from .compiler import SolidityCompiler, SolidityConfig


@plugins.register(plugins.Config)
def config_class():
    return SolidityConfig


@plugins.register(plugins.CompilerPlugin)
def register_compiler():
    return (Extension.SOL.value,), SolidityCompiler
