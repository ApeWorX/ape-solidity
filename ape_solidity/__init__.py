from ape import plugins

from .compiler import SolidityCompiler


@plugins.register(plugins.CompilerPlugin)
def register_compiler():
    return (".sol",), SolidityCompiler
