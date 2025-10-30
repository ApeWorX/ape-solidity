from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from ape.exceptions import ContractLogicError
from ape.utils import ManagerAccessMixin, cached_property

if TYPE_CHECKING:
    from ape.api import CompilerAPI, TestAccountAPI
    from ape.contracts import ContractInstance
    from ethpm_types import ContractType


# TODO: Configure EVM context? Pre-compiles? Foundry-like cheatcodes?


def pytest_collect_file(parent, file_path):
    if file_path.name.endswith(".t.sol"):
        return SolTest.from_parent(parent, path=file_path)


class SolTest(pytest.File, ManagerAccessMixin):
    @property
    def compiler(self) -> "CompilerAPI":
        return self.compiler_manager.registered_compilers[".sol"]

    @cached_property
    def contract_type(self) -> "ContractType":
        # TODO: Use `settings=` for test-only settings?
        return self.compiler.compile_code(self.path.read_text())

    @property
    def executor(self) -> "TestAccountAPI":
        return self.account_manager.test_accounts[-1]

    @cached_property
    def instance(self) -> "ContractInstance":
        # TODO: How do I enter network context with Ape?
        network_context = self.network_manager.parse_network_choice("::test")
        network_context.__enter__()
        if hasattr(instance := self.executor.deploy(self.contract_type), "setUp"):
            instance.setUp(sender=self.executor)

        self.snapshot = self.chain_manager.snapshot()
        return instance

    def collect(self) -> Iterator["SolTestcase"]:
        for method in self.contract_type.mutable_methods:
            if method.name.startswith("test"):
                yield SolTestcase.from_parent(self, name=method.name)

            # TODO: "table tests"? fuzzing? invariant testing?


class SolTestcase(pytest.Item, ManagerAccessMixin):
    # TODO: What functionality does foundry's test runner support?

    def runtest(self):
        assert isinstance(self.parent, SolTest)  # mypy happy
        method = getattr(self.parent.instance, self.name)
        # TODO: Handle `args` for fixtures, parametrization ("table tests"), and fuzzing
        try:
            method(sender=self.parent.executor)
            # TODO: Test reporting functionality? Handle raises?

        # NOTE: Catch if marked xfail?
        except ContractLogicError as e:
            breakpoint()
            raise e

        finally:
            self.chain_manager.restore(self.parent.snapshot)
