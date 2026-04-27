from importlib.metadata import version

import typer
from typer import Typer


def version_callback(value: bool) -> None:
    if value:
        print(version("pier"))
        raise typer.Exit()


app = Typer(no_args_is_help=True)


@app.callback()
def main(
    version: bool | None = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
) -> None:
    pass


if __name__ == "__main__":
    app()
