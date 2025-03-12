# pylint: disable=missing-docstring

class Vector:

    def __init__(self, *items):
        self._items = list(items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, index):
        return self._items[index]

    def append(self, item):
        _items = self._items.copy()
        _items.append(item)
        return Vector(*_items)

    def assoc(self, *args):
        _items = self._items.copy()
        for i in range(0, len(args), 2):
            index = args[i]
            value = args[i+1]
            _items[index] = value
        return Vector(*_items)

def record(name, *fields):
    def __init__(self, **kwargs):
        for field_name in fields:
            if field_name not in kwargs:
                raise TypeError(f"Missing argument: {field_name}")
            self._storage[field_name] = kwargs[field_name]

        for kwarg in kwargs:
            if kwarg not in fields:
                raise TypeError(f"Unexpected argument: {kwarg}")

    def _getattr(self, attr):
        try :
            return self._storage[attr]
        except KeyError as ex:
            raise AttributeError(
                f"Record of type '{name}' has no attribute '{attr}'") from ex

    def _setattr(self, attr, value):
        raise AttributeError(f"Record of type '{name}' is immutable")

    def assoc(self, **kwargs):
        _storage = self._storage.copy()
        _storage.update(kwargs)
        return type(self)(**_storage)

    _type = type(name, (), {
        "_storage": {},
        "__init__": __init__,
        "__getattr__": _getattr,
        "__setattr__": _setattr,
        "assoc": assoc,
    })

    return _type
