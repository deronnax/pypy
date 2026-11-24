# Collects and executes application-level tests.
#
# Classes which names start with "AppTest"
# are not executed by the host Python, but
# by an interpreted pypy object space.
#
# ...unless the -A option ('runappdirect') is passed.

import py
import _pytest._code
import sys, textwrap, types, gc
from pypy.interpreter.gateway import app2interp_temp
from pypy.interpreter.error import OperationError
from pypy.interpreter.function import Method
from pypy.tool.pytest import appsupport
from inspect import getmro


class AppError(Exception):
    def __init__(self, excinfo):
        self.excinfo = excinfo


class AppTestMethod(py.test.collect.Function):
    def _prunetraceback(self, excinfo):
        # a runaway recursion can produce a traceback with hundreds of
        # repeated frames, which is fine to inspect when running a single
        # test in isolation but floods the log when running a whole suite
        # (e.g. on the buildbot). Cap it in that case, unless the recursion
        # itself is the only thing selected to run.
        if len(self.session.items) > 1:
            traceback = excinfo.traceback
            recursionindex = traceback.recursionindex()
            if recursionindex is not None:
                # list.__getslice__ (py2) would silently downgrade this to
                # a plain list, breaking traceback.recursionindex() calls
                # later on; wrap explicitly to keep the Traceback type.
                excinfo.traceback = _pytest._code.Traceback(traceback[:recursionindex + 1])
            elif len(traceback) > 100:
                excinfo.traceback = _pytest._code.Traceback(traceback[:100])

    def execute_appex(self, space, target, *args):
        self.space = space
        try:
            target(*args)
        except OperationError as e:
            if self.config.option.raise_operr:
                raise
            tb = sys.exc_info()[2]
            if e.match(space, space.w_KeyboardInterrupt):
                raise KeyboardInterrupt, KeyboardInterrupt(), tb
            appexcinfo = appsupport.AppExceptionInfo(space, e)
            if appexcinfo.traceback:
                raise AppError, AppError(appexcinfo), tb
            raise

    def repr_failure(self, excinfo):
        if excinfo.errisinstance(AppError):
            excinfo = excinfo.value.excinfo
        return super(AppTestMethod, self).repr_failure(excinfo)

    def _getdynfilename(self, func):
        code = getattr(func, 'im_func', func).func_code
        return "[%s:%s]" % (code.co_filename, code.co_firstlineno)

    def track_allocations_collect(self):
        gc.collect()
        # must also invoke finalizers now; UserDelAction
        # would not run at all unless invoked explicitly
        if hasattr(self, 'space'):
            self.space.getexecutioncontext()._run_finalizers_now()

    def setup(self):
        super(AppTestMethod, self).setup()
        instance = self.parent.obj
        w_instance = self.parent.w_instance
        space = instance.space
        for name in dir(instance):
            if name.startswith('w_'):
                if self.config.option.runappdirect:
                    setattr(instance, name[2:], getattr(instance, name))
                else:
                    obj = getattr(instance, name)
                    if isinstance(obj, types.MethodType):
                        source = py.code.Source(obj).indent()
                        w_func = space.appexec([], textwrap.dedent("""
                        ():
                        %s
                            return %s
                        """) % (source, obj.__name__))
                        w_obj = Method(space, w_func, w_instance, space.w_None)
                    else:
                        w_obj = obj
                    space.setattr(w_instance, space.wrap(name[2:]), w_obj)

    def runtest(self):
        target = self.obj
        if self.config.option.runappdirect:
            return target()
        space = target.im_self.space
        filename = self._getdynfilename(target)
        func = app2interp_temp(target.im_func, filename=filename)
        w_instance = self.parent.w_instance
        self.execute_appex(space, func, space, w_instance)


class AppClassInstance(py.test.collect.Instance):
    def _makeitem(self, name, obj):
        if callable(obj) and self.funcnamefilter(name):
            return AppTestMethod(name, parent=self)
        return super(AppClassInstance, self)._makeitem(name, obj)

    @property
    def w_instance(self):
        # created lazily: with pytest >= 4, setup_class() runs from a
        # fixture, i.e. only when the first test of the class is set up
        w_instance = self.__dict__.get('_w_instance')
        if w_instance is None:
            instance = self.obj
            if self.config.option.runappdirect:
                w_instance = instance
            else:
                space = instance.space
                w_instance = space.call_function(self.parent.w_class)
            self._w_instance = w_instance
        return w_instance


class AppClassCollector(py.test.Class):
    def collect(self):
        # pytest >= 4 runs setup_class/setup_method through fixtures that
        # Class.collect() injects; we override collect(), so do it here
        self._inject_setup_class_fixture()
        self._inject_setup_method_fixture()
        return [AppClassInstance(name="()", parent=self)]

    def setup(self):
        super(AppClassCollector, self).setup()
        cls = self.obj
        #
        # <hack>
        for name in dir(cls):
            if name.startswith('test_'):
                func = getattr(cls, name, None)
                code = getattr(func, 'func_code', None)
                if code and code.co_flags & 32:
                    raise AssertionError("unsupported: %r is a generator "
                                         "app-level test method" % (name,))
        # </hack>

    @property
    def w_class(self):
        # lazy, see AppClassInstance.w_instance
        w_class = self.__dict__.get('_w_class')
        if w_class is None:
            cls = self.obj
            space = cls.space
            clsname = cls.__name__
            if self.config.option.runappdirect:
                w_class = cls
            else:
                w_class = space.call_function(space.w_type,
                                              space.wrap(clsname),
                                              space.newtuple([]),
                                              space.newdict())
            self._w_class = w_class
        return w_class
