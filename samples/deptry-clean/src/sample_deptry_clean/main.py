"""Entry point. Everything imported is declared; everything declared is used."""

import click


@click.command()
def run() -> None:
    click.echo("clean")


if __name__ == "__main__":
    run()
