import os
import textwrap
import traceback
from datetime import datetime
from functools import partial, wraps

import six
from boardfarm.exceptions import CodeError, ContOnFailError, TestError
from boardfarm.tests_wrappers import continue_on_fail
from termcolor import cprint


class TestResult:
    __test__ = False
    logged = {}

    def __init__(self, name, grade, message, result=(None, None)):
        self.name = name
        self.result_grade = grade
        self.result_message = message
        self.step, self.result = result

    def output(self):
        """Return output of a TestAction

        This method should only be called, while verifying TestStep
        with an expected value.

        :param self: TestResult instance for a TestAction
        :returns: result
        :rtype: TestResult.result
        """
        return self.result


class TestStepMeta(type):
    section = {}

    def __new__(cls, name, bases, dct):
        dct['__init__'] = cls.set_args(dct['__init__'])
        return super(TestStepMeta, cls).__new__(cls, name, bases, dct)

    @classmethod
    def set_args(cls, func):
        @wraps(func)
        def wrapper(self, tst_cls, *args, **kwargs):
            cls.section[tst_cls] = cls.section.get(tst_cls, {})
            self.section = cls.section[tst_cls]
            return func(self, tst_cls, *args, **kwargs)

        return wrapper


class TestStep(six.with_metaclass(TestStepMeta, object)):
    __test__ = False

    def __init__(self, parent_test, name, prefix="Execution"):
        self.section[prefix] = self.section.get(prefix, 0) + 1
        self.step_id = self.section[prefix]
        self.parent_test = parent_test
        self.name = name
        self.actions = []
        self.result = []
        self.prefix = prefix
        self.verify_f, self.v_msg = None, None
        self.called_with = False
        # Device manager, for accessing devices
        self.dev = parent_test.dev
        if parent_test.log_to_file is None:
            parent_test.log_to_file = ""

        # to maintain an id for each action.
        self.action_id = 1

    def log_msg(self, msg, attr=['bold'], no_time=False, wrap=True):
        time = datetime.now().strftime("%b %d %Y %H:%M:%S")
        indent = ""
        if not no_time:
            indent = " " * (len(time) + 1)
            msg = "{} {}".format(time, msg)
        if wrap:
            msg = textwrap.TextWrapper(width=80,
                                       subsequent_indent=indent).fill(text=msg)
        self.parent_test.log_to_file += msg + "\r\n"
        cprint(msg, None, attrs=attr)

    def add_verify(self, func, v_msg):
        self.verify_f = func
        self.v_msg = v_msg

    def add(self, func, *args, **kwargs):
        TestAction(self, partial(func, *args, **kwargs))

    def call(self, func, *args, **kwargs):
        self.add(func, *args, **kwargs)
        self.execute()

    def __enter__(self):
        self.msg = "[{}]:[{} Step {}]".format(
            self.parent_test.__class__.__name__, self.prefix, self.step_id)
        print()
        self.log_msg(('#' * 80), no_time=True)
        self.log_msg("{}: START".format(self.msg))
        self.log_msg("Description: {}".format(self.name))
        self.log_msg(('#' * 80), no_time=True)
        self.called_with = True
        return self

    def __exit__(self, ex_type, ex_value, tb):
        r = "PASS" if not tb else "FAIL"
        self.log_msg(('-' * 80), no_time=True)
        self.log_msg("{}: END\t\tResult: {}".format(self.msg, r))
        if tb:
            trace = traceback.format_exception(ex_type, ex_value, tb)
            self.log_msg("".join(trace).strip(),
                         attr=[],
                         no_time=True,
                         wrap=False)
        self.log_msg(('-' * 80), no_time=True)
        if tb and 'BFT_DEBUG' in os.environ:
            step_output = ["Logging step output:"]
            for i in self.result:
                step_output.append("[{}] :: {}".format(i.step, i.result))
            self.log_msg("\n".join(step_output), no_time=True, wrap=False)
            self.log_msg(('-' * 80), no_time=True)
        self.called_with = False

    # msg has to be the verification message.
    def verify(self, cond, msg):
        if not cond:
            self.log_msg("{}::[Verification] :\n{} - FAILED".format(
                self.msg, msg))
            raise TestError('{}::[Verification] :\n{} - FAILED'.format(
                self.msg, msg))
        else:
            self.log_msg("{}::[Verification] :\n{} - PASSED".format(
                self.msg, msg))

    def execute(self):
        # enforce not to call execute without using with clause.
        if not self.called_with:
            raise CodeError(
                "{} - need to execute step using 'with' clause".format(
                    self.msg))

        # enforce not to call execute without adding an action
        if not self.actions:
            raise CodeError(
                "{} - no actions added before calling execute".format(
                    self.msg))

        for a_id, action in enumerate(self.actions):
            func_name = action.action.func.__name__
            prefix = "[{}]:[{} Step {}.{}]::[{}]".format(
                self.parent_test.__class__.__name__, self.prefix, self.step_id,
                self.action_id, func_name)
            tr = None

            try:
                output = action.execute()
                tr = TestResult(prefix, "OK", "", (func_name, output))
                self.log_msg("{} : DONE".format(prefix))
            except Exception as e:
                tr = TestResult(prefix, "FAIL", str(e), (func_name, str(e)))
                self.log_msg("{} : FAIL :: {}:{}".format(
                    prefix, e.__class__.__name__, str(e)))
                raise (e)
            finally:
                self.result.append(tr)
                self.action_id += 1
                self.actions = []
        if self.verify_f:
            try:
                cond = self.verify_f()
            except Exception as e:
                raise CodeError("{}::[Verification] :\n{}".format(
                    self.msg, str(e)))
            self.verify(cond, self.v_msg)

        self.actions = []


class TestAction(object):
    __test__ = False

    def __init__(self, parent_step, func):
        self.name = func.func.__name__
        parent_step.actions.append(self)
        self.action = func

    def execute(self):
        try:
            output = self.action()
            return output
        except AssertionError as e:
            raise CodeError(e)


class TearDown(TestStep):
    __test__ = False

    def __init__(self, parent_test, name, prefix="TearDown"):
        super(TearDown, self).__init__(parent_test, name, prefix)
        self.td_result = True
        self.print_enter = False

    def add(self, func, *args, **kwargs):
        wrapped_func = continue_on_fail(func)
        super(TearDown, self).add(wrapped_func, *args, **kwargs)

    def enter(self):
        self.print_enter = True
        super(TearDown, self).__enter__()

    def call(self, func, *args, **kwargs):
        if not self.print_enter:
            self.enter()
        check = "exp" in kwargs
        exp = kwargs.pop("exp", None)
        self.add(func, *args, **kwargs)
        self.execute()
        if type(self.result[-1].output()) is ContOnFailError:
            pass
        elif check:
            r = self.result[-1].output() == exp
            if not r:
                r = ContOnFailError(
                    "Teardown Assertion FAIL :\nExp: {} Actual: {}".format(
                        exp, self.result[-1].output()))
                r.tb = (None, None, None)
                self.result[-1].result = r

        self.print_log(self.result[-1])

    def print_log(self, i):
        step_id = self.result.index(i) + 1
        if issubclass(type(i.result), Exception):
            self.log_msg(
                "Teardown failed for Step {}.{}\n{} - Reason: {}".format(
                    self.step_id, step_id, i.step, i.result),
                no_time=True,
                wrap=False)
            self.td_result = False

            if hasattr(i.result, "tb") and 'BFT_DEBUG' in os.environ:
                trace = traceback.format_exception(*i.result.tb)
                self.log_msg("".join(trace).strip(),
                             attr=[],
                             no_time=True,
                             wrap=False)

        self.log_msg(('-' * 80), no_time=True)
        self.log_msg("[{}]:[{} Step {}.{}]\tResult: {}".format(
            self.parent_test.__class__.__name__, self.prefix, self.step_id,
            step_id, ["FAIL", "PASS"][self.td_result]))
        self.log_msg("Output: {}".format(i.result), no_time=True)
        self.log_msg(('-' * 80), no_time=True)


if __name__ == '__main__':

    def action1(a, m=2):
        print("\nAction 1 performed multiplication\nWill return value: {}\n".
              format(a * m))
        return a * m

    def action2(a, m=3):
        print("\nAction 2 performed division\nWill return value: {}\n".format(
            a / m))
        return a / m

    def add_100(a):
        print("\nAction addition performed \nWill return value: {}\n".format(
            a + 100))
        return a + 100

    class Test1(object):
        steps = []
        log_to_file = None
        dev = None

        def runTest(self):
            # this one can be used to define common test Steps
            # note: we could assign a section to a test-step, e.g. Set-up in this case.
            with TestStep(self, "This is step1 of test setup",
                          "Example 1") as ts:

                # if you're intializing a TA, pass the function as a partial,
                # else code will fail
                TestAction(ts, partial(action1, 2, m=3))
                TestAction(ts, partial(action2, 6, m=2))

                # add verification, call it later after execute.
                # if no verification is added, we're expecting step to pass with exception from actions
                def _verify():
                    return ts.result[0].output() == 6 and \
                           ts.result[1].output() == 3

                ts.add_verify(_verify, "verify step1 output")
                ts.execute()

            # variation 2, call execute multiple times.
            # Note: here you might need to change verification for each execute, manually
            # Note: don't pop the output, we might need it to log step results later
            with TestStep(self, "This is step1 of execution",
                          "Example 2") as ts:
                for i in [1, 2, 3, 4]:
                    ts.add(add_100, i)
                    ts.execute()
                    ts.verify(ts.result[-1].output() == 100 + i,
                              "Verification for input: {}".format(i))

            # variation 4
            # This is to ensure that you can call and verify functions directly
            with TestStep(self, "This is call step variation of execution",
                          "Example 4") as ts:
                ts.call(action1, 2, m=3)
                ts.call(action2, 6, m=1)
                ts.verify(ts.result[1].output() != 3,
                          "verify variation 4 output")

            # variation 3
            # need this to reset the counter.
            with TestStep(self, "This is step2 of execution",
                          "Example 3") as ts:
                ts.add(action1, 2, m=3)
                ts.add(action2, 6, m=0)
                ts.execute()
                # since we didn't add a verification before,we can call one directly as well
                ts.verify(ts.result[1].output() != 3, "verify step2 output")

    obj = Test1()
    try:
        obj.runTest()
    except Exception:
        # handle retry condition for TC
        pass
    print("\n\nHow stuff will look like in txt file:\n{}".format(
        obj.log_to_file))
