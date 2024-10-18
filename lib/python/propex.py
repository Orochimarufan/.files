# Custom property-like classes
from typing import MutableMapping, NewType, Optional, Sequence, Generic, TypeVar, Callable, Type, Any, overload, Union

try:
    from typing import Self
except ImportError:
    try:
        from typing_extensions import Self
    except ImportError:
        Self = Any


T = TypeVar('T')
O = TypeVar('O')
Ow = TypeVar('Ow', covariant=True)


class CustomProperty(property, Generic[T]):
    """ Subclass property for IDE support.
        Subclasses need not call super().__init__(),
        but might want to initialize self.property_name if such information is available """

    property_name: str = "<<name unknown>>"

    def __init__(self):
        # Overwrite property constructor
        pass

    def __set_name__(self, owner: Type[O], name: str):
        """ Set name given in class body.
            May not be called if assigned outside class definition """
        self.property_name = name

    @overload # type: ignore
    def __get__(self, obj: None, cls: Type[O]) -> Self: ...
    @overload
    def __get__(self, obj: O, cls: Type[O]) -> T: ...

    def __get__(self, obj: Optional[O], cls: Type[O]):
        if obj is None:
            return self
        raise AttributeError(f"Cannot read property {self.property_name} of {obj!r}")

    def __set__(self, obj: O, value: T):
        raise AttributeError(f"Cannot write property {self.property_name} of {obj!r}")

    def __delete__(self, obj: O):
        raise AttributeError(f"Cannot delete property {self.property_name} of {obj!r}")


class CachedProperty(CustomProperty[T], Generic[T, Ow]):
    """ A property that is only computed once per instance and then replaces
        itself with an ordinary attribute. Deleting the attribute resets the
        property.

        Source: https://github.com/bottlepy/bottle/commit/fa7733e075da0d790d809aa3d2f53071897e6f76
        """

    def __init__(self, func: Callable[[Ow], T]):
        self.__doc__ = getattr(func, '__doc__')
        self.func = func
        self.property_name = func.__name__

    def __get__(self, obj: Optional[Ow], cls: Type[Ow]): # type: ignore[override]
        if obj is None:
            return self
        value = obj.__dict__[self.property_name] = self.func(obj)
        return value

    def __delete__(self, obj: Ow): # type: ignore[override,misc]
        del obj.__dict__[self.property_name]


class SettableCachedProperty(CachedProperty[T, O]):
    def __set__(self, obj: O, value: T): #type: ignore[override]
        obj.__dict__[self.property_name] = value


class DictPathRoProperty(CustomProperty[T]):
    _NoDefault = NewType("_NoDefault", object)
    _nodefault = _NoDefault(object())

    def __init__(self, source_member: str, path: Sequence[str],
            default: Union[T, _NoDefault]=_nodefault, type: Callable[[Any], T]=lambda x: x):
        self.source_member = source_member
        self.path = path
        self.default = default
        self.type = type

    def _get_parent(self, obj: O, *, create=False) -> MutableMapping[str, Any]:
        d: MutableMapping[str, Any] = getattr(obj, self.source_member)
        for pc in self.path[:-1]:
            try:
                d = d[pc]
            except KeyError:
                if not create:
                    raise
                nd: MutableMapping[str, Any] = {}
                d[pc] = nd
                d = nd
        return d

    def __get__(self, obj: Optional[O], cls: Type[O]): # type: ignore
        if obj is None:
            return self
        try:
            val = self._get_parent(obj)[self.path[-1]]
        except KeyError:
            if self.default is not self._nodefault:
                return self.default
            raise
        else:
            return self.type(val)


class DictPathProperty(DictPathRoProperty[T]):
    def __init__(self, *args, allow_create_parents=True, **kwds):
        super().__init__(*args, **kwds)
        self.allow_create_parents = allow_create_parents

    def __set__(self, obj, value):
        self._get_parent(obj, create=self.allow_create_parents)[self.path[-1]] = value

    def __delete__(self, obj):
        del self._get_parent(obj)[self.path[-1]]


# functools.cached_property polyfill
try:
    from functools import cached_property
except ImportError:
    cached_property = CachedProperty # type: ignore[assignment,misc]

__all__ = ['CustomProperty', 'CachedProperty', 'SettableCachedProperty', 'DictPathRoProperty', 'DictPathProperty', 'cached_property']
