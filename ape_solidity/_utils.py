import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from ape.exceptions import CompilerError
from packaging.version import Version
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


@dataclass(frozen=True)
class SoliditySemVer:
    major: int
    minor: int
    patch: int
    prerelease: str = ""
    build: str = ""

    @classmethod
    def parse(cls, version: str) -> "SoliditySemVer":
        match = re.fullmatch(
            r"(?P<major>0|[1-9]\d*)\."
            r"(?P<minor>0|[1-9]\d*)\."
            r"(?P<patch>0|[1-9]\d*)"
            r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
            r"(?:\+(?P<build>[0-9A-Za-z.-]+))?",
            version,
        )
        if not match:
            raise ValueError(f"Invalid Solidity version: '{version}'.")

        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=match.group("prerelease") or "",
            build=match.group("build") or "",
        )


class SolidityVersionSpecifier:
    def __init__(self, expression: str):
        self.expression = _normalize_pragma_expression(expression)
        self._ranges = _parse_solidity_version_expression(self.expression)

    def __contains__(self, version: Union[str, Version, SoliditySemVer]) -> bool:
        return self.contains(version)

    def __str__(self) -> str:
        return self.expression

    def match(self, version: Version) -> bool:
        return self.contains(_as_solidity_semver(version))

    def contains(self, version: Union[str, Version, SoliditySemVer]) -> bool:
        if isinstance(version, Version):
            return self.match(version)

        semver = _coerce_semver_version(version)
        return any(
            all(_match_solidity_component(component, semver) for component in conjunction)
            for conjunction in self._ranges
        )

    def filter(self, versions: Iterable[Version]) -> Iterable[Version]:
        return (version for version in versions if self.match(version))


def _as_solidity_semver(version: Version) -> SoliditySemVer:
    release = ".".join(str(part) for part in (*version.release[:3], 0, 0)[:3])
    prerelease = ""
    if version.pre:
        prerelease_name, prerelease_number = version.pre
        prerelease_name = {
            "a": "alpha",
            "b": "beta",
        }.get(prerelease_name, prerelease_name)
        prerelease = f"-{prerelease_name}.{prerelease_number}"
    elif version.dev is not None:
        prerelease = f"-dev.{version.dev}"

    return SoliditySemVer.parse(f"{release}{prerelease}")


def _coerce_semver_version(version: Union[str, Version, SoliditySemVer]) -> SoliditySemVer:
    if isinstance(version, SoliditySemVer):
        return version

    if isinstance(version, Version):
        return _as_solidity_semver(version)

    return SoliditySemVer.parse(str(version))


def _normalize_pragma_expression(expression: str) -> str:
    expression = expression.strip().replace('"', "").replace("'", "")
    expression = re.sub(r"([<>=~^]=?)\s+", r"\1", expression)
    expression = re.sub(r"(?<=[0-9xX*])(?=[<>=~^])", " ", expression)
    return re.sub(r"\s+", " ", expression)


VersionComponent = tuple[str, tuple[int, int, int], int]
WILDCARD_VERSION_PART = -1


def _parse_solidity_version_expression(expression: str) -> list[list[VersionComponent]]:
    ranges: list[list[VersionComponent]] = []
    for range_expression in expression.split("||"):
        blocks = range_expression.split()
        if not blocks:
            raise ValueError("Empty version pragma.")

        if len(blocks) == 3 and blocks[1] == "-":
            ranges.append(
                [
                    _parse_version_component(blocks[0], prefix=">="),
                    _parse_version_component(blocks[2], prefix="<="),
                ]
            )
        else:
            ranges.append([_parse_version_component(block) for block in blocks])

    return ranges


def _parse_version_component(component: str, prefix: str | None = None) -> VersionComponent:
    if prefix is None:
        prefix = "="
        for operator in (">=", "<=", "^", "~", ">", "<", "="):
            if component.startswith(operator):
                prefix = operator
                component = component.removeprefix(operator)
                break

    version_parts = component.split(".")
    if len(version_parts) > 3:
        raise ValueError("Too many version levels.")

    numbers = [0, 0, 0]
    for index, part in enumerate(version_parts):
        if part in ("*", "x", "X"):
            numbers[index] = WILDCARD_VERSION_PART
        elif part.isdecimal():
            numbers[index] = int(part)
        else:
            raise ValueError(f"Expected version number, wildcard, or operator but got '{part}'.")

    return prefix, (numbers[0], numbers[1], numbers[2]), len(version_parts)


def _match_solidity_component(component: VersionComponent, version: SoliditySemVer) -> bool:
    prefix, numbers, levels_present = component
    if prefix == "~":
        upper_levels = 2 if levels_present >= 2 else 1
        return _match_solidity_component((">=", numbers, levels_present), version) and (
            _match_solidity_component(("<=", numbers, upper_levels), version)
        )

    elif prefix == "^":
        upper_levels = 2 if numbers[0] == 0 and levels_present != 1 else 1
        return _match_solidity_component((">=", numbers, levels_present), version) and (
            _match_solidity_component(("<=", numbers, upper_levels), version)
        )

    cmp = 0
    did_compare = False
    version_parts = (version.major, version.minor, version.patch)
    for index in range(levels_present):
        if cmp == 0 and numbers[index] != WILDCARD_VERSION_PART:
            did_compare = True
            cmp = version_parts[index] - numbers[index]

    if cmp == 0 and version.prerelease and did_compare:
        cmp = -1

    if prefix == "=":
        return cmp == 0
    elif prefix == "<":
        return cmp < 0
    elif prefix == "<=":
        return cmp <= 0
    elif prefix == ">":
        return cmp > 0
    elif prefix == ">=":
        return cmp >= 0

    raise ValueError(f"Unexpected version operator: '{prefix}'.")


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


def select_version(
    pragma_spec: SolidityVersionSpecifier, options: Iterable[Version]
) -> Optional[Version]:
    choices = sorted(pragma_spec.filter(options), reverse=True)
    return choices[0] if choices else None


def strip_commit_hash(version: Union[str, Version]) -> Version:
    """
    Version('0.8.21+commit.d9974bed') => Version('0.8.21')> the simple way.
    """
    return Version(f"{str(version).split('+')[0].strip()}")
