"""
pytest plugin: PyPy's default assertion mode, "reinterp".

Rewriting the asserts of test modules (pytest's default) changes their
bytecode, which breaks the tests that run RPython's flow space on functions
defined in test modules.  So by default we do not rewrite (pytest.ini passes
--assert=plain) and instead reinterpret a failing assert after the fact, with
the AST-based code in reinterpret.py.

  --assert=rewrite   pytest's usual rewriting
  --no-reinterp      really plain asserts
"""


def pytest_addoption(parser):
    parser.getgroup("general").addoption(
        "--no-reinterp", action="store_true", default=False,
        dest="no_reinterp",
        help="with --assert=plain, do not reinterpret failing asserts either")


def pytest_configure(config):
    if config.getoption("assertmode") != "plain":
        return
    if config.getoption("no_reinterp"):
        return
    import py
    from rpython.tool.pytest import reinterpret
    builtins = py.builtin.builtins
    orig = builtins.AssertionError
    builtins.AssertionError = reinterpret.AssertionError

    def undo():
        builtins.AssertionError = orig
    config.add_cleanup(undo)
