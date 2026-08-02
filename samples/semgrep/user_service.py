# Bait for mutation-requires-authz-python — issue #21.
#
# A separate file because the rule is PATH-GATED to `*service.py` / `*handler.py`
# for the same reason its C# and TypeScript twins are: "a public method whose
# name starts with a mutation verb" is a rule about service entry points, and
# applied to every file in a repo it would be a rule about naming.
#
# Nothing here is compiled, linted or type-checked. Semgrep only parses it.


class UserService:
    def __init__(self, repo: object, authz: object) -> None:
        self._repo = repo
        self._authz = authz

    # Branch: sync def, mutation verb, no gate.
    def delete_user(self, user_id: str) -> None:
        self._repo.delete(user_id)

    # Branch: async def, mutation verb, no gate.
    async def update_user(self, user_id: str, name: str) -> None:
        await self._repo.update(user_id, name)

    # NEGATIVE CONTROLS — the gate, in both spellings and both definition forms.
    # `await` is deliberately not spelled out in the rule: semgrep matches the
    # inner call inside the await expression, so one exemption covers both. That
    # is asserted by the async cases here rather than assumed.
    def create_user(self, name: str) -> None:
        self._authz.require("users:create")
        self._repo.create(name)

    async def remove_user(self, user_id: str) -> None:
        await self._authz.require("users:delete")
        await self._repo.delete(user_id)

    async def grant_role(self, user_id: str, role: str) -> None:
        await self._authz.authorize("roles:grant")
        await self._repo.grant(user_id, role)

    # NEGATIVE CONTROL. A read is not a mutation.
    def get_user(self, user_id: str) -> object:
        return self._repo.find(user_id)

    # NEGATIVE CONTROL, and the reason the name regex is anchored rather than a
    # bare prefix match. `set` and `grant` are prefixes of ordinary English
    # words, and Python's snake_case puts them flush against the rest of the
    # name where C#'s PascalCase would not. `settle_invoice` is not a `set`.
    def settle_invoice(self, invoice_id: str) -> None:
        self._repo.settle(invoice_id)

    # NEGATIVE CONTROL. A leading underscore is Python's own answer to the
    # question the C# twin asks with `public`: this is a helper, not an entry
    # point, and the caller that reached it went through a gated method.
    def _delete_row(self, row_id: str) -> None:
        self._repo.delete(row_id)
