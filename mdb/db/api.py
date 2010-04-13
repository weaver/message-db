## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""api -- high-level operations"""

from __future__ import absolute_import
from md.prelude import *
from md import fluid
from .. import avro, data
from . import _tree

__all__ = ('branch', 'init', 'get', 'delta')

BRANCH = fluid.cell(None)
branch = fluid.accessor(BRANCH)

def init(zs):
    BRANCH.set(_Branch(zs.open()))
    return zs

def get(key):
    if key is None or isinstance(key, _tree.Content):
        return key
    elif isinstance(key, (basestring, _tree.Key)):
        return branch().get(str(key))
    else:
        return branch().mget(str(k) for k in key)

# def _delete(key):
#     if isinstance(key, models.Model):
#         key = key.key
#     if isinstance(key, (basestring, models.Key)):
#         stm.delete(key)
#     else:
#         for k in key: stm.delete(k)


### Changes

@contextmanager
def delta(message):
    """Replace the _Branch with a _Delta in the calling context.
    Methods that use branch() (such as get()) will use this delta
    instead."""

    delta = branch().begin(message)
    with branch(delta):
        yield delta

class _Branch(object):
    """A _Branch is a thin wrapper that acts as an interface between
    this api and the data api."""

    def __init__(self, zs):
        self._zs = zs

    def get(self, key):
        val = self._zs.get(key)
        return val and val.update(_key=_tree.Key(key))

    def mget(self, keys):
        for (key, val) in self._zs.mget(keys):
            yield val and val.update(_key=_tree.Key(key))

    def begin(self, message):
        return _Delta(message, self, self._zs.begin_transaction())

    def checkpoint(self, mark, message, delta):
        with data.message(message):
            self._zs.end_transaction(mark, self._zs.checkpoint(delta))
        return self

class _Delta(object):
    """A delta is a set of changes about to be committed to a
    zipper."""

    def __init__(self, message, source, mark):
        self._message = message
        self._source = source
        self._data = {}
        self._mark = mark

    def new(self, cls, state):
        key = _tree.Key.make(cls.__kind__, state.pop('key_name', None))
        obj = cls(**state).update(_key=key)
        self._data[str(key)] = obj
        return obj

    def get(self, key):
        probe = self._data.get(key, Undefined)
        if probe is not Undefined:
            return probe
        return self._source.get(key)

    def mget(self, keys):
        need = []

        for key in keys:
            probe = self._data.get(key, Undefined)
            if probe is not Undefined:
                yield probe
            else:
                need.append(key)

        if need:
            for obj in self._source.mget(need):
                yield obj

    def checkpoint(self):
        self._source.checkpoint(self._mark, self._message, self._data)
        return self

