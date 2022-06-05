# Ape Solidity

Compile Solidity contracts.

## Dependencies

* [python3](https://www.python.org/downloads) version 3.7.2 or greater, python3-dev

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

### Compiler Version

By default, the `ape-solidity` plugin tries to figure out the best compiler versions to use to compile your project.
However, to manually set a version expression, use the `version:` key in your project's `ape-config.yaml` file:

```yaml
solidity:
  version: =0.8.12
```

This can help resolve issues when a newer Solidity version has breaking changes and you are compiling a source file with a more lenient version constraint.

### Dependency Mapping

To configure import remapping, use your project's `ape-config.yaml` file:

```yaml
solidity:
  import_remapping:
    - "@openzeppelin=path/to/open_zeppelin/contracts"
```

If you are using the `dependencies:` key in your `ape-config.yaml`, `ape` can automatically
search those dependencies for the path.

```yaml
dependencies:
  - name: OpenZeppelin
    github: OpenZeppelin/openzeppelin-contracts
    version: 4.4.2

solidity:
  import_remapping:
    - "@openzeppelin=OpenZeppelin/4.4.2"
```

Once you have your dependencies configured, you can import packages using your import keys:

```solidity
import "@openzeppelin/token/ERC721/ERC721.sol";
```

## Development

Please see the [contributing guide](CONTRIBUTING.md) to learn more how to contribute to this project.
Comments, questions, criticisms and pull requests are welcomed.

## License

This project is licensed under the [Apache 2.0](LICENSE).
