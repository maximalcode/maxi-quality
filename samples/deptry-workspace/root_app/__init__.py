"""The root package's own code. Imports exactly what the root manifest declares."""

import click


@click.command()
def cli() -> None:
    """Entry point for the workspace root."""
    click.echo("root")
