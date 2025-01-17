from . import scheduler
from . import logger
import random
import inspect
import copy


class MethodWrapper:

    def __init__(self, obj, func, name):
        self.func = func
        self.obj = obj
        self.__name__ = name
        self.begins = scheduler.Trigger(f'{name} begin')
        self.ends = scheduler.Trigger(f'{name} end')
        self.default_trigger = self.ends

    def __call__(self, *args, **keys):
        self.obj.sch.trigger(self.begins)
        val = self.func(self.obj, *args, **keys)
        self.obj.sch.trigger(self.ends)
        return val


class MethodGeneratorWrapper(MethodWrapper):

    def _generator(self, *args, **keys):
        self.obj.sch.trigger(self.begins)
        for x in self.func(self.obj, *args, **keys):
            yield x
        self.obj.sch.trigger(self.ends)

    def __call__(self, *args, **keys):
        return self.obj.sch.add(self._generator, args=args, keys=keys)

    def __str__(self):
        return f'<MGW {self.obj} {self.name}'


def log_everything(model, log=None):
    if log is None:
        log = logger.log_proxy
    if not hasattr(model, 'log'):
        model.run(limit=0)
    model.log = log
    for k, v in list(model.__dict__.items()):
        if k[0] != '_' and k != 'parent':
            if isinstance(v, Model) and v.parent is model:
                log_everything(v, getattr(log, k))


class Model:

    __converted = False
    _convert_methods = True
    _auto_run_start = True
    name = 'top'

    def __init__(self, log=None, **keys):
        self.__init_log = log
        for k, v in list(keys.items()):
            setattr(self, k, v)

    def __getitem__(self, item):
        return getattr(self, item)

    def __convert(self, parent=None, name=None):
        assert self.__converted is False
        self.__converted = True
        self.changes = scheduler.Trigger()

        if hasattr(self, 'parent'):
            parent = self.parent

        methods = {}
        objects = {}

        for klass in inspect.getmro(self.__class__)[:-1]:
            if klass is not Model:
                for k, v in inspect.getmembers(klass):
                    if k[0] != '_':
                        if inspect.isfunction(v):
                            if (k not in ['run', 'now', 'get_children']
                                    and k not in methods
                                    and klass is not Model):
                                methods[k] = v
                        else:
                            if (inspect.isclass(v)
                                    and Model in inspect.getmro(v)):
                                v = v()
                            if k not in objects:
                                objects[k] = v
        objects = copy.deepcopy(objects)

        if parent:
            if not parent.__converted:
                parent.__convert()
            self.sch = parent.sch
            self.log = logger.dummy
            self.random = parent.random
            self.parent = parent
        else:
            self.sch = scheduler.Scheduler()
            if self.__init_log is True:
                self.log = logger.log()
            elif self.__init_log is None:
                self.log = logger.dummy
            else:
                self.log = self.__init_log
            self.random = random.Random()
            self.parent = None

        self._convert_info(objects, methods)
        for name, obj in list(objects.items()):
            if isinstance(obj, Model):
                if not obj.__converted:
                    obj.__convert(self, name)
                else:
                    obj.name = name
                try:
                    self._children[name] = obj
                except AttributeError:
                    self._children = {name: obj}
            self.__dict__[name] = obj

        if self._convert_methods:
            for name, func in list(methods.items()):
                # check if function is a generator
                if func.__code__.co_flags & 0x20 == 0x20:
                    w = MethodGeneratorWrapper(self, func, name)
                else:
                    w = MethodWrapper(self, func, name)
                self.__dict__[name] = w

        if self._auto_run_start:
            self.start()

        for k, v in list(self.__dict__.items()):
            if k[0] != '_' and k != 'parent' and isinstance(v, Model):
                if not v.__converted:
                    v.__convert(parent=self)

    def _convert_info(self, objects, methods):
        pass

    def __setattr__(self, key, value):
        if (key == 'parent' and value is None
                and getattr(self, 'parent', None) is not None):
            del self.parent._children[self.name]

        if isinstance(value, Model) and key[0] != '_' and key != 'parent':
            self._ensure_converted()
            p = self
            ancestor = True
            while p is not None:
                if value is p:
                    break
                p = getattr(p, 'parent', None)
            else:
                if getattr(value, 'parent', None) is not None:
                    pass
                else:
                    value.parent = self
                    value.name = key
                    try:
                        self._children[key] = value
                    except AttributeError:
                        self._children = {key: value}
                    if self.__converted and not value.__converted:
                        value.__convert(name=key, parent=self)

        skip_keys = ['parent', 'sch', 'changes', 'log', 'random', 'name']
        if self.__converted and key[0] != '_' and key not in skip_keys:
            m = self
            done = []
            while m is not None:
                self.sch.trigger(m.changes, priority=-1)
                done.append(m)
                m = m.parent
                if m in done:
                    m = None
            if self.log:
                setattr(self.log, key, value)

        if key == 'log' and value is not None:
            for k, v in list(self.__dict__.items()):
                if k[0] != '_' and k not in skip_keys:
                    if isinstance(v, (int, str, float, type(None))):
                        setattr(value, k, v)

        self.__dict__[key] = value

    def start(self):
        pass

    def run(self, limit=None, func=None):
        if not self.__converted:
            self.__convert()
        if limit is not None:
            self.sch.add(self.sch.stop, limit, priority=-9999999)
        if func is not None:
            self.sch.add(func)
        self.sch.run()

    def stop(self):
        if not self.__converted:
            self.__convert()
        self.sch.stop()

    def now(self):
        if not self.__converted:
            self.__convert()
        return self.sch.time

    def get_children(self):
        try:
            return list(self._children.values())
        except AttributeError:
            return []

    def _get_scheduler(self):
        self._ensure_converted()
        return self.sch

    def _ensure_converted(self):
        if not self.__converted:
            self.__convert()

    def _is_converted(self):
        return self.__converted
