"""DELIBERATELY MISFORMATTED. `ruff format --check` must reject this file.

Nothing here is a lint error — the formatter is the only thing with an opinion
about it. See README.md in this directory.

This file is not covered by `ruff check`; `samples/python` is the lint fixture
and this directory is deliberately outside it, so the finding manifests cannot
move when the formatting fixtures change.
"""


def add(a,b) :
    return   a+b


VALUES = [ 1,2,
        3, 4 ]


class  Thing :
    def __init__( self,name ):
        self.name=name
