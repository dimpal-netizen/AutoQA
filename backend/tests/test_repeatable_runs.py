"""A test has to give the same answer the second time you run it.

The recorded suite's own regression test read:

    register_buyer.email_input.fill('lucy@yopmail.com')
    register_buyer.mobile_number_input.fill('9632587412')

It passed the day it was recorded and failed every day after. By the second run
that account existed, and the application was right to refuse a second one. The
steps were correct, the application was correct, and the test was red.

That is the most expensive way for a test to be wrong. Nothing on screen says
"this failed because it worked last time", so the tester spends an afternoon on
it — and then learns to look at the next red test a little less carefully.

`synth.py` has had placeholders for this since the model started inventing
sign-up cases. The recording never went through them: it replays exactly what
was typed, which is right for a login and fatal for a registration.
"""

import ast

import pytest

from app.codegen.converter import build_ir
from app.codegen.generator import render

SIGNUP = "https://x.test/register/buyer"
LOGIN = "https://x.test/login"


def typed(value, name, *, url=SIGNUP, input_type="text", **attributes):
    return {
        "action_type": "input",
        "url": url,
        "frame_path": [],
        "selectors": [{"strategy": "label", "value": name, "unique": True, "score": 90}],
        "element": {
            "tag": "input", "input_type": input_type, "role": "textbox",
            "accessible_name": name, "text": "", "attributes": attributes,
        },
        "payload": {"value": value},
        "is_ignored": False,
    }


def submitted(url=SIGNUP):
    return {
        "action_type": "click",
        "url": url,
        "frame_path": [],
        "selectors": [
            {"strategy": "role_name", "value": "button|Create Account",
             "unique": True, "score": 95}
        ],
        "element": {
            "tag": "button", "input_type": None, "role": "button",
            "accessible_name": "Create Account", "text": "Create Account",
            "attributes": {},
        },
        "payload": {},
        "is_ignored": False,
    }


def generate(actions, *, start_url=SIGNUP) -> str:
    ir = build_ir(actions, suite_name="Suite", start_url=start_url)
    files = {f.path: f.content for f in render(ir, browser_info={})}
    return files[ir.file_path]


# ---------------------------------------------------------------------------
# The value that cannot be replayed
# ---------------------------------------------------------------------------
def test_a_recorded_signup_address_is_not_replayed():
    code = generate([typed("lucy@yopmail.com", "Email", input_type="email"), submitted()])
    ast.parse(code)

    assert "'lucy@yopmail.com'" not in code
    assert "uuid4()" in code
    assert "from uuid import uuid4" in code


def test_the_domain_the_application_accepted_is_kept():
    """example.test cannot receive mail. The recorded domain demonstrably works."""
    code = generate([typed("lucy@yopmail.com", "Email", input_type="email"), submitted()])

    assert "@yopmail.com'" in code


def test_a_domain_that_is_not_a_domain_falls_back_to_a_reserved_one():
    code = generate([
        typed("someone@nonsense domain", "Email", input_type="email"), submitted()
    ])
    ast.parse(code)

    assert "@example.test'" in code


def test_the_phone_keeps_the_shape_that_was_accepted():
    """A hard-coded shape is how an Indian number lands in a Kenyan form."""
    code = generate([typed("9632587412", "Mobile Number", input_type="tel"), submitted()])
    ast.parse(code)

    assert "'9632587412'" not in code
    # Ten digits, still starting with 9 — whatever the form's country expects.
    assert "f'9{uuid4().int % 1000000000:09d}'" in code


def test_a_short_number_is_left_alone_rather_than_mangled():
    """Nothing sensible to vary in a single digit."""
    code = generate([typed("7", "Mobile Number", input_type="tel"), submitted()])

    assert "'7'" in code


# ---------------------------------------------------------------------------
# The values that must NOT change
# ---------------------------------------------------------------------------
def test_the_password_is_left_exactly_as_recorded():
    """It is not an identity. The account is created with it and needed again.

    `Test@1234` has an @ in it, which is how the first version of this replaced
    it with an email address.
    """
    code = generate([
        typed("lucy@yopmail.com", "Email", input_type="email"),
        typed("Test@1234", "Password", input_type="password"),
        submitted(),
    ])
    ast.parse(code)

    assert "'Test@1234'" in code


@pytest.mark.parametrize("field", ["Password", "Confirm Password", "OTP", "CVV"])
def test_no_secret_is_ever_substituted(field):
    code = generate([typed("Test@1234", field, input_type="password"), submitted()])

    assert "'Test@1234'" in code


def test_a_login_replays_the_account_it_recorded():
    """The whole point of a login test is the account that already exists."""
    code = generate(
        [typed("lucy@yopmail.com", "Email", url=LOGIN, input_type="email"),
         submitted(url=LOGIN)],
        start_url=LOGIN,
    )

    assert "'lucy@yopmail.com'" in code
    assert "uuid4" not in code


def test_an_ordinary_field_on_a_signup_form_is_still_replayed():
    """Only what has to be unique. A first name repeats perfectly well."""
    code = generate([typed("John", "First Name"), submitted()])

    assert "'John'" in code
    assert "uuid4" not in code


# ---------------------------------------------------------------------------
# Two fields, one value
# ---------------------------------------------------------------------------
def test_an_address_typed_twice_stays_one_address():
    """Two calls to uuid4() would fail the form's own "these must match" check."""
    code = generate([
        typed("lucy@yopmail.com", "Email", input_type="email"),
        typed("lucy@yopmail.com", "Confirm Email", input_type="email"),
        submitted(),
    ])
    ast.parse(code)

    assert code.count("fresh_email = ") == 1
    assert code.count(".fill(fresh_email)") == 2


def test_two_different_addresses_get_two_different_variables():
    code = generate([
        typed("lucy@yopmail.com", "Email", input_type="email"),
        typed("other@yopmail.com", "Backup Email", input_type="email"),
        submitted(),
    ])
    ast.parse(code)

    assert "fresh_email = " in code
    assert "fresh_email_2 = " in code


# ---------------------------------------------------------------------------
# The generated file has to say what it did
# ---------------------------------------------------------------------------
def test_the_substitution_is_explained_where_it_happens():
    """Silently changing what someone recorded is worse than not doing it."""
    code = generate([typed("lucy@yopmail.com", "Email", input_type="email"), submitted()])

    assert "Fresh every run" in code
    assert "lucy@yopmail.com" in code  # what was recorded, named in the comment
    assert "Change these in the recording" in code


def test_a_suite_with_nothing_to_freshen_carries_no_note():
    code = generate([typed("John", "First Name"), submitted()])

    assert "Fresh every run" not in code
