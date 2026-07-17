"""TE2 (audit 2026-07-17): fake↔real interface contracts.

Every suite drives the pipeline through duck-typed fakes — nothing used to
guard against silent interface drift (a renamed real method leaves the fake
testing a phantom API, and the suite stays green while production breaks).
These tests pin the contract mechanically:

- every public method a fake defines must exist on the real class it stands
  in for (no phantom methods);
- for each shared method, every parameter the REAL accepts must be accepted
  by the fake (same names, so a call written against the real signature runs
  against the fake) — extra fake-only defaults are fine.
"""

import inspect
import unittest

from src.login_session import LoginSession
from src.submit_session import SubmitSession, WriteSubmitSession

from tests.test_submitter import (
    FakeSubmitSession,
    FakeWriteSession,
    ReflowWriteSession,
    ReimportingWriteSession,
)
from tests.test_login_session import FakeLoginSession


# Transport/lifecycle plumbing the fakes deliberately do not model.
_PLUMBING = {
    "open", "close", "evaluate_readonly",
}


def _public_methods(cls) -> dict[str, inspect.Signature]:
    methods = {}
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_") or name in _PLUMBING:
            continue
        methods[name] = inspect.signature(member)
    return methods


def _check_contract(test: unittest.TestCase, fake_cls, real_cls) -> None:
    fake = _public_methods(fake_cls)
    real = _public_methods(real_cls)

    phantom = set(fake) - set(real)
    test.assertFalse(
        phantom,
        f"{fake_cls.__name__} defines methods {sorted(phantom)} that "
        f"{real_cls.__name__} does not have — the fake tests a phantom API",
    )

    for name in sorted(set(fake) & set(real)):
        fake_params = list(fake[name].parameters)
        if any(
            p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
            for p in fake[name].parameters.values()
        ):
            continue  # *args/**kwargs pass-through accepts any real call
        for param_name, param in real[name].parameters.items():
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            test.assertIn(
                param_name,
                fake_params,
                f"{fake_cls.__name__}.{name} does not accept parameter "
                f"{param_name!r} of {real_cls.__name__}.{name} — a caller "
                "written against the real signature breaks on the fake",
            )


class SubmitSessionContractTests(unittest.TestCase):
    def test_fake_submit_session_matches_real(self):
        _check_contract(self, FakeSubmitSession, SubmitSession)

    def test_fake_write_session_matches_real(self):
        _check_contract(self, FakeWriteSession, WriteSubmitSession)

    def test_reflow_session_matches_real(self):
        _check_contract(self, ReflowWriteSession, WriteSubmitSession)

    def test_reimporting_session_matches_real(self):
        _check_contract(self, ReimportingWriteSession, WriteSubmitSession)


class LoginSessionContractTests(unittest.TestCase):
    def test_fake_login_session_matches_real(self):
        _check_contract(self, FakeLoginSession, LoginSession)


if __name__ == "__main__":
    unittest.main()
