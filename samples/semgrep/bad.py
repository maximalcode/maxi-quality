# Layer 2 bait for Python — issue #21.
#
# Python shipped as a full Layer 1 language (Ruff's 13 families plus mypy
# strict) and Layer 2 never followed: `semgrep --config semgrep samples/python`
# reported `Ran 19 rules on 0 files`. Not one rule id could match a `.py` file.
#
# What is here is only the measured gap. Ruff already covers five of the twelve
# conventions outright — T201, SIM105, S324, S608, S602 — and ASYNC251 covers
# sync-over-async, so none of those get a Semgrep rule they do not need. See
# docs/EVAL-vs-oss-tools.md §1f.
#
# Every secret-shaped string in this file is planted bait and has never been
# valid anywhere. See the README next to it.
#
# Nothing here is compiled, linted or type-checked — `ruff check` and `mypy`
# run against samples/python/, not this directory, so Layer 2 bait can never
# shift a Layer 1 count. Semgrep only parses it.
import datetime
import logging
import time
from datetime import date

logger = logging.getLogger(__name__)


# --- todo-without-issue -----------------------------------------------------
# The rule is `languages: [generic]` and always could have read Python; only its
# `paths.include` list kept it out. `#` had to join the comment markers.
# TODO: rename this before the migration


# NEGATIVE CONTROL. A tracked TODO is a decision somebody can find again. `#` is
# both the comment marker and the issue sigil, so this is the case that proves
# the exemption is anchored on `#[0-9]+` and not merely on `#`.
# TODO(#412): tracked, and therefore fine


# --- hardcoded-secret-python ------------------------------------------------
# Branch: plain assignment. Ruff's S105 also catches this one; it is here so the
# rule's own coverage is provable rather than inferred from Ruff's.
API_TOKEN = "sk-live-4f9a2c7e1b8d3a6f"

# Branch: annotated assignment. THE CASE THIS RULE EXISTS FOR — ruff 0.16.1 is
# silent here (measured 2026-08-02), because S105's name list does not reach
# `connection_string`, so a userinfo URL in a Python service was invisible to
# every layer this baseline runs.
CONNECTION_STRING: str = "postgres://admin:hunter2@db.internal:5432/app"


class Client:
    def __init__(self) -> None:
        # Branch: attribute assignment. The value is the base64 body with no
        # spaces in it, and that is not cosmetic — the fourth value guard below
        # drops anything containing whitespace, so a PEM header written out in
        # full would have made this branch look covered while testing the guard
        # instead of the branch.
        self.private_key = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ"

        # NEGATIVE CONTROL for the value guard, and the reason the guard exists
        # at all: Phase A scored the name test 0 true positives out of 5 (#17).
        # A bare URL is an endpoint, not a credential — and this one is in a
        # `token`-named attribute, which is exactly the false positive observed.
        self.token_endpoint = "https://auth.example.com/oauth2/token"

        # NEGATIVE CONTROL. Under 12 characters is a sentinel, not a key.
        self.api_key = "none"

        # NEGATIVE CONTROL. An obvious placeholder is not a secret.
        self.client_secret = "changeme"


# NEGATIVE CONTROL for the fourth value guard, the one the TS and C# twins do
# not have. Measured against 4,133 files of Django, Celery, SQLAlchemy, Flask
# and httpx, prose in a secret-named constant was the largest single false-
# positive class the other three guards left. A credential does not contain a
# space.
SECRET_KEY_WARNING = "Your SECRET_KEY is missing and the server will not start."


# --- no-ambient-clock-python ------------------------------------------------
# Branch: `.now()`. The fully-qualified spelling `import datetime` gives you,
# which is the one most Python code uses. It is baited because the first draft
# of the rule assumed semgrep matches a dotted suffix and would cover this from
# `datetime.now(...)`. It does not, and this fixture is what said so.
def expires_at() -> datetime.datetime:
    return datetime.datetime.now() + datetime.timedelta(days=1)


# Branch: `.utcnow()`.
def created_at() -> datetime.datetime:
    return datetime.datetime.utcnow()


# Branch: `.today()` — and the OTHER half of the receiver regex. The two cases
# above go through its `datetime.` prefix; this one goes through the prefix
# being absent, which is what `from datetime import date` produces. Both
# alternatives are reached, so neither can be deleted unobserved.
def billing_day() -> date:
    return date.today()


# Branch: `time.time()`, which has no receiver to match on and is its own
# pattern.
def stamp() -> float:
    return time.time()


# NEGATIVE CONTROL. Stamping a timestamp into a log line is not untestable
# business logic — the same carve-out the TS and C# rule makes.
def log_progress(step: str) -> None:
    logger.info("%s at %s", step, datetime.datetime.now())


# --- no-float-for-money-python ----------------------------------------------
# Branch: annotated assignment.
total_amount: float = 0.0


# Branch: bare annotation on a class attribute.
class Invoice:
    balance_due: float


# Branch: function parameter.
def apply_discount(item: str, unit_price: float) -> str:
    return item


# Branch: async function parameter.
async def charge(customer: str, total_fee: float) -> None:
    return None


# NEGATIVE CONTROLS. A float that is not money is not this rule's business, and
# a money amount that is already a Decimal is the fix, not the bug.
def resize(image: str, scale_factor: float) -> str:
    return image


def refund(amount: "decimal.Decimal") -> None:
    return None


# KNOWN GAP, kept visible on purpose. Python only has a type where somebody
# wrote an annotation, so an unannotated local is not reachable by this rule and
# this line is SILENT. A rule keyed on the literal instead would fire on every
# float in the codebase. If a future change makes this reachable, the finding
# has to be added to samples/expected/semgrep.json in the same change.
def running_total(rows: list[float]) -> float:
    total_price = 0.0
    for row in rows:
        total_price += row
    return total_price


# --- no-permission-denied-for-invisible-resource-python ---------------------
class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = "") -> None:
        super().__init__(detail)


class PermissionDenied(Exception):
    pass


class JSONResponse:
    def __init__(self, status_code: int, content: object = None) -> None:
        self.status_code = status_code


def HttpResponseForbidden(*args: object) -> object:  # noqa: N802
    return object()


# Branch: `is None` + raise with status_code=403 (FastAPI / Starlette).
def get_document(doc_id: str, repo: object) -> object:
    doc = repo.find(doc_id)
    if doc is None:
        raise HTTPException(status_code=403, detail="forbidden")
    return doc


# Branch: falsiness check + raise with status_code=403.
def get_invoice(invoice_id: str, repo: object) -> object:
    invoice = repo.find(invoice_id)
    if not invoice:
        raise HTTPException(status_code=403, detail="forbidden")
    return invoice


# Branch: `is None` + returned response object.
def get_report(report_id: str, repo: object) -> object:
    report = repo.find(report_id)
    if report is None:
        return JSONResponse(status_code=403, content={"detail": "forbidden"})
    return report


# Branch: falsiness check + Django's HttpResponseForbidden, which carries no
# number at all.
def get_page(page_id: str, repo: object) -> object:
    page = repo.find(page_id)
    if not page:
        return HttpResponseForbidden("forbidden")
    return page


# Branch: `is None` + DRF's PermissionDenied — the closest twin of the C# rule's
# `StatusCode.PermissionDenied`.
def get_folder(folder_id: str, repo: object) -> object:
    folder = repo.find(folder_id)
    if folder is None:
        raise PermissionDenied("forbidden")
    return folder


# NEGATIVE CONTROL. 404 for a resource the caller cannot see is the fix, and it
# must not fire.
def get_secret_note(note_id: str, repo: object) -> object:
    note = repo.find(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="not found")
    return note
