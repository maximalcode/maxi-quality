"""Entry point. Uses click and bs4; yaml is imported but never declared."""

import click
import yaml
from bs4 import BeautifulSoup


@click.command()
def run() -> None:
    soup = BeautifulSoup("<p>hi</p>", "html.parser")
    config = yaml.safe_load("mode: fast")
    click.echo(soup.get_text())
    click.echo(str(config))


if __name__ == "__main__":
    run()
