"""
pytest plugin: support for "yield tests" (test generators).

pytest 4.0 removed them, but we have a lot of them (e.g. the rsre tests
against the CPython test suite, or the astcompiler tests).  This is the
collection code of pytest 3.10, adapted to pytest 4.6.

A test function or method that is a generator is collected as a node whose
children are the yielded items, named "[0]", "[1]", ... (or "['name']" if
the first item of the yielded tuple is a string).  Each yielded item is a
tuple (callable, arg1, arg2, ...).
"""
import contextlib
import inspect
import pytest
import six
from _pytest.compat import getimfunc
from _pytest.python import (Function, FunctionMixin, PyCollector,
                            _call_with_optional_argument,
                            _get_non_fixture_func)


class YieldedFunction(Function):
    """A test made of one item yielded by a test generator."""

    def __init__(self, name, parent, args, callobj):
        self._yielded_args = args
        # the arguments are given explicitly: do not look for fixtures
        # based on the signature of the callable (but autouse fixtures
        # still apply)
        fixtureinfo = parent.session._fixturemanager.getfixtureinfo(
            parent, callobj, parent.cls, funcargs=False)
        super(YieldedFunction, self).__init__(
            name, parent, callobj=callobj, fixtureinfo=fixtureinfo)

    def _getobj(self):
        raise AssertionError("callobj is always given")

    def runtest(self):
        self.obj(*self._yielded_args)


@contextlib.contextmanager
def xunit_setup(collector):
    """Run the setup_module/setup_class/setup_method of the generator while
    it is being collected, as pytest 3.10 did: in pytest >= 4 they are run by
    fixtures, i.e. only when running a test, but the body of a generator
    often needs what they set up."""
    def find(obj, *names):
        for name in names:
            func = _get_non_fixture_func(obj, name)
            if func is not None:
                return func

    module, cls, func = collector.module, collector.cls, collector.obj
    teardowns = []
    try:
        setup = find(module, 'setUpModule', 'setup_module')
        teardown = find(module, 'tearDownModule', 'teardown_module')
        if setup is not None:
            _call_with_optional_argument(setup, module)
        if teardown is not None:
            teardowns.append(lambda: _call_with_optional_argument(
                teardown, module))
        if cls is not None:
            setup = find(cls, 'setup_class')
            teardown = getattr(cls, 'teardown_class', None)
            if setup is not None:
                _call_with_optional_argument(getimfunc(setup), cls)
            if teardown is not None:
                teardowns.append(lambda: _call_with_optional_argument(
                    getimfunc(teardown), cls))
            instance = getattr(func, '__self__', None)
            if instance is not None:
                setup = find(instance, 'setup_method')
                teardown = getattr(instance, 'teardown_method', None)
                if setup is not None:
                    _call_with_optional_argument(setup, func)
                if teardown is not None:
                    teardowns.append(lambda: _call_with_optional_argument(
                        teardown, func))
        yield
    finally:
        while teardowns:
            teardowns.pop()()


class YieldTestCollector(FunctionMixin, PyCollector):
    def collect(self):
        values = []
        seen = {}
        with xunit_setup(self):
            yielded = list(self.obj())
        for i, x in enumerate(yielded):
            name, call, args = self.getcallargs(x)
            if not callable(call):
                raise TypeError("%r yielded non callable test %r" %
                                (self.obj, call))
            if name is None:
                name = "[%d]" % i
            else:
                name = "['%s']" % name
            if name in seen:
                raise ValueError("%r generated tests with non-unique name %r" %
                                 (self, name))
            seen[name] = True
            values.append(YieldedFunction(name, self, args, call))
        return values

    def getcallargs(self, obj):
        if not isinstance(obj, (tuple, list)):
            obj = (obj,)
        # explicit naming
        if isinstance(obj[0], six.string_types):
            name = obj[0]
            obj = obj[1:]
        else:
            name = None
        call, args = obj[0], obj[1:]
        return name, call, args


@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makeitem(collector, name, obj):
    if (collector.istestfunction(obj, name) and
            inspect.isgeneratorfunction(getattr(obj, '__func__', obj))):
        if getattr(obj, '__test__', True):
            return YieldTestCollector(name, parent=collector)
