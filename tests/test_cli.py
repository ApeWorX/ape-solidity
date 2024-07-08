import subprocess

from ape.utils import create_tempdir

from ape_solidity._cli import cli


def test_cli_flatten(project, cli_runner):
    path = project.contracts_folder / "Imports.sol"
    arguments = ["flatten", str(path)]
    end = ("--project", str(project.path))
    with create_tempdir() as tmpdir:
        file = tmpdir / "Imports.sol"
        arguments.extend([str(file), *end])
        result = cli_runner.invoke(cli, arguments, catch_exceptions=False)
        assert result.exit_code == 0, result.stderr_bytes
        output = file.read_text(encoding="utf8")
        breakpoint()
        x = ""


def test_compile():
    """
    Integration: Testing the CLI using an actual subprocess because
    it is the only way to test compiling the project such that it
    isn't treated as a tempdir project.
    """
    # Use a couple contracts
    cmd_ls = ("ape", "compile", "subdir", "--force")
    completed_process = subprocess.run(cmd_ls, capture_output=True)
    output = completed_process.stdout.decode(encoding="utf8")
    assert "SUCCESS" in output
    assert "zero_four_in_subdir.vy" in output
