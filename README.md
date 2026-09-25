# Quick Start

Compile Solidity contracts.

## Dependencies

- [python3](https://www.python.org/downloads) version 3.9 up to 3.12.

## Installation

### via `pip`

You can install the latest release via [`pip`](https://pypi.org/project/pip/):

```bash
pip install ape-solidity
```

### via `setuptools`

You can clone the repository and use [`setuptools`](https://github.com/pypa/setuptools) for the most up-to-date version:

```bash
git clone https://github.com/ApeWorX/ape-solidity.git
cd ape-solidity
python3 setup.py install
```

## Quick Usage

In your project, make sure you have a `contracts/` directory containing Solidity files (`.sol`).

Then, while this plugin is installed, compile your contracts:

```bash
ape compile
```

The byte-code and ABI for your contracts should now exist in a `__local__.json` file in a `.build/` directory.

### Solidity Versioning

By default, `ape-solidity` tries to use the best versions of Solidity by looking at all the source files' pragma specifications.
However, it is often better to specify a version directly.
If you know the best version to use, set it in your `ape-config.yaml`, like this:

```yaml
solidity:
  version: 0.8.14
```

### EVM Versioning

By default, `ape-solidity` will use whatever version of EVM rules are set as default in the compiler version that gets used.
Sometimes, you might want to use a different version, such as deploying on Arbitrum or Optimism where new opcodes are not supported yet.
If you want to require a different version of EVM rules to use in the configuration of the compiler, set it in your `ape-config.yaml` like this:

```yaml
solidity:
  evm_version: paris
```

### Dependency Mapping

By default, `ape-solidity` knows to look at installed dependencies for potential remapping-values and will use those when it notices you are importing them.
For example, if you are using dependencies like:

```yaml
dependencies:
  - name: openzeppelin
    github: OpenZeppelin/openzeppelin-contracts
    version: 4.4.2
```

And your source files import from `openzeppelin` this way:

```solidity
import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
```

Ape knows how to resolve the `@openzeppelin` value and find the correct source.

If you want to override this behavior or add new remappings that are not dependencies, you can add them to your `ape-config.yaml` under the `solidity:` key.
For example, let's say you have downloaded `openzeppelin` somewhere and do not have it installed in Ape.
You can map to your local install of `openzeppelin` this way:

```yaml
solidity:
  import_remapping:
    - "@openzeppelin=path/to/openzeppelin"
```

### Library Linking

To compile contracts that use libraries, you need to add the libraries first.
Use the `add_library()` method from the `ape-solidity` compiler class to add the library.
A typical flow is:

1. Deploy the library.
2. Call `add_library()` using the Solidity compiler plugin, which will also re-compile contracts that need the library.
3. Deploy and use contracts that require the library.

For example:

```python
import pytest


@pytest.fixture
def contract(accounts, project, compilers):
    # Deploy the library.
    account = accounts[0]
    library = project.Set.deploy(sender=account)

    # Add the library to Solidity (re-compiles contracts that use the library).
    compilers.solidity.add_library(library)

    # Deploy the contract that uses the library.
    return project.C.deploy(sender=account)
```

### Compiler Settings

When using `ape-solidity`, your project's manifest's compiler settings will include standard JSON output.
You should have one listed `compiler` per `solc` version used in your project.
You can view your current project manifest, including the compiler settings, by doing:

```python
from ape import project

manifest = project.extract_manifest()

for compiler_entry in manifest.compilers:
    print(compiler_entry.version)
    print(compiler_entry.settings)
```

**NOTE**: These are the settings used during contract verification when using the [Etherscan plugin](https://github.com/ApeWorX/ape-etherscan).

#### `--via-IR` Yul IR Compilation Pipeline

You can enable `solc`'s `--via-IR` flag by adding the following values to your `ape-config.yaml`

```yaml
solidity:
  via_ir: True
```

### Contract Flattening

`ape-solidity` has contract-flattening capabilities.
If you are publishing contracts using Ape, Ape automatically detects and uses the flattened-contract approach if needed.

To manually flatten a contract for your own benefit, use the following code:

```python
from ape import compilers, project

source_path = project.source_paths[0]  # Replace with your path.
flattened_src = compilers.flatten_contract(source_path)
print(str(flattened_src))
```
