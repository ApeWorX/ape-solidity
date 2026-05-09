import json
import re
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from ape.exceptions import CompilerError
from packaging.version import Version
from semantic_version import NpmSpec  # type: ignore[import-untyped]
from semantic_version import Version as SemVerVersion  # type: ignore[import-untyped]
from solcx.install import get_executable
from solcx.wrapper import get_solc_version as get_solc_version_from_binary

OUTPUT_SELECTION = [
    "abi",
    "bin-runtime",
    "devdoc",
    "userdoc",
    "evm.bytecode.object",
    "evm.bytecode.sourceMap",
    "evm.deployedBytecode.object",
]


class Extension(Enum):
    SOL = ".sol"


class SolidityVersionSpecifier:
    def __init__(self, expression: str):
        self.pragma_str = expression
        self.expression = _normalize_pragma_expression(expression)
        self._npm_spec = NpmSpec(self.expression)

    def __contains__(self, version: Union[str, Version, SemVerVersion]) -> bool:
        return self.contains(version)

    def __str__(self) -> str:
        return self.expression

    def match(self, version: Version) -> bool:
        semver = _as_npm_version(version)
        return self._npm_spec.match(semver) or self._matches_solc_prerelease(semver)

    def contains(self, version: Union[str, Version, SemVerVersion]) -> bool:
        if isinstance(version, Version):
            return self.match(version)

        semver = _coerce_semver_version(version)
        return self._npm_spec.match(semver) or self._matches_solc_prerelease(semver)

    def filter(self, versions: Iterable[Version]) -> Iterable[Version]:
        return (version for version in versions if self.match(version))

    def _matches_solc_prerelease(self, version: SemVerVersion) -> bool:
        if not version.prerelease:
            return False

        if self.expression in ("*", ">=*"):
            return True

        return any(
            _matches_partial_greater_than(block, version) for block in self.expression.split()
        )


def _as_npm_version(version: Version) -> SemVerVersion:
    return SemVerVersion(version.base_version)


def _coerce_semver_version(version: Union[str, Version, SemVerVersion]) -> SemVerVersion:
    if isinstance(version, SemVerVersion):
        return version

    if isinstance(version, Version):
        return _as_npm_version(version)

    return SemVerVersion(str(version))


def _normalize_pragma_expression(expression: str) -> str:
    expression = expression.strip().replace('"', "").replace("'", "")
    expression = re.sub(r"([<>=~^]=?)\s+", r"\1", expression)
    expression = re.sub(r"(?<=[0-9xX*])(?=[<>=~^])", " ", expression)
    return re.sub(r"\s+", " ", expression)


def _matches_partial_greater_than(block: str, version: SemVerVersion) -> bool:
    match = re.fullmatch(r">(\d+)(?:\.(\d+))?", block)
    if not match:
        return False

    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    if match.group(2) is None:
        lower_bound = SemVerVersion(f"{major + 1}.0.0-0")
        upper_bound = SemVerVersion(f"{major + 1}.0.0")
    else:
        lower_bound = SemVerVersion(f"{major}.{minor + 1}.0-0")
        upper_bound = SemVerVersion(f"{major}.{minor + 1}.0")

    return lower_bound <= version < upper_bound


def get_import_lines(source_paths: Iterable[Path]) -> dict[Path, list[str]]:
    imports_dict: dict[Path, list[str]] = {}
    for filepath in source_paths:
        imports_dict[filepath] = get_single_import_lines(filepath)

    return imports_dict


def get_single_import_lines(source_path: Path) -> list[str]:
    import_set = set()
    if not source_path.is_file():
        return []

    source_lines = source_path.read_text(encoding="utf8").splitlines()
    num_lines = len(source_lines)
    for line_number, ln in enumerate(source_lines):
        if not ln.startswith("import"):
            continue

        import_str = ln
        second_line_number = line_number
        while ";" not in import_str:
            second_line_number += 1
            if second_line_number >= num_lines:
                raise CompilerError("Import statement missing semicolon.")

            next_line = source_lines[second_line_number]
            import_str += f" {next_line.strip()}"

        import_set.add(import_str)
        line_number += 1

    return list(import_set)


def get_pragma_spec_from_path(
    source_file_path: Union[Path, str],
) -> Optional[SolidityVersionSpecifier]:
    """
    Extracts pragma information from Solidity source code.

    Args:
        source_file_path (Union[Path, str]): Solidity source file path.

    Returns:
        ``Optional[SolidityVersionSpecifier]``
    """
    path = Path(source_file_path)
    if not path.is_file():
        return None

    source_str = path.read_text(encoding="utf8")
    return get_pragma_spec_from_str(source_str)


def get_pragma_spec_from_str(
    source_str: str,
) -> Optional[SolidityVersionSpecifier]:
    if not (
        pragma_match := next(
            re.finditer(r"(?:\n|^)\s*pragma\s*solidity\s*([^;\n]*)", source_str), None
        )
    ):
        return None  # Try compiling with latest

    try:
        return SolidityVersionSpecifier(pragma_match.groups()[0])
    except ValueError:
        return None


def load_dict(data: Union[str, dict]) -> dict:
    return data if isinstance(data, dict) else json.loads(data)


def add_commit_hash(version: Union[str, Version]) -> Version:
    vers = Version(f"{version}") if isinstance(version, str) else version
    has_commit = len(f"{vers}") > len(vers.base_version)
    if has_commit:
        # Already added.
        return vers

    solc = get_executable(version=vers)
    return get_solc_version_from_binary(solc, with_commit_hash=True)


def get_versions_can_use(
    pragma_spec: SolidityVersionSpecifier, options: Iterable[Version]
) -> list[Version]:
    return sorted(list(pragma_spec.filter(options)), reverse=True)


def select_version(
    pragma_spec: SolidityVersionSpecifier, options: Iterable[Version]
) -> Optional[Version]:
    choices = get_versions_can_use(pragma_spec, options)
    return choices[0] if choices else None


def strip_commit_hash(version: Union[str, Version]) -> Version:
    """
    Version('0.8.21+commit.d9974bed') => Version('0.8.21')> the simple way.
    """
    return Version(f"{str(version).split('+')[0].strip()}")
