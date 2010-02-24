## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""datastore -- datastore stub implemented with the AppEngine SDK"""

from __future__ import absolute_import
import os, yaml, glob, re, itertools as it, contextlib as ctx
from md import abc
from google.appengine.ext import db
from google.appengine.api import datastore_file_stub
from google.appengine.api import apiproxy_stub_map
from . import tree

Key = db.Key
get = db.get


### Models

@abc.implements(tree.Node)
class Item(db.Expando):

    def __init__(self, *args, **kw):
        name = make_slug(kw.get('name') or kw.get('title', ''))
        if not name:
            raise ValueError('An Item requires a title or a name.')
        super(Item, self).__init__(*args, **update(
            kw,
            name=name,
            title=(kw.get('title', '').strip() or make_title(name))
        ))

    def __repr__(self):
        return '<%s %s>' % (type(self).__name__, self.title)

    def __hash__(self):
        return hash(str(self.key()))

    def __leaf__(self):
        return True

    def __eq__(self, other):
        if isinstance(other, db.Model):
            return self.key() == other.key()
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, db.Model):
            return self.key() != other.key()
        return NotImplemented

    name = db.StringProperty()
    title = db.StringProperty()
    folder = db.ReferenceProperty(db.Model)

@abc.implements(tree.InnerNode)
class Folder(Item):
    contents = db.ListProperty(db.Key)

    def __nonzero__(self):
        return True

    def __len__(self):
        return len(self.contents)

    def __contains__(self, name):
        return any(name == c.name for c in self)

    def __iter__(self):
        return (db.get(k) for k in self.contents)

    def __leaf__(self):
        return False

    def index(self, item):
        return self.contents.index(item.key())

    def before(self, item):
        return it.takewhile(lambda c: c != item, self)

    def after(self, item):
        pivot = self.index(item) + 1
        return (db.get(k) for k in it.islice(self.contents, pivot, None))

    def add(self, item):
        if item.name in self:
            raise ValueError('Child already exists: %r.' % item.name)
        elif item.folder:
            raise ValueError('Child already in folder: %r' % item.folder)
        self.contents.append(item.key())
        item.folder = self
        return self

    def child(self, name, default=None):
        if isinstance(name, int):
            try:
                return db.get(self.contents[name])
            except IndexError:
                return default
        return next((c for c in self if c.name == name), default)

class Page(Item):
    description = db.StringProperty()
    content = db.TextProperty()


### Content Tree

def root():
    return Folder.get_by_key_name('root')

def find_root(item):
    while item.parent:
        item = item.parent
    return item

parents = tree.ascend

def walk(item):
    return tree.orself(item, tree.descend)

def add_child(folder, child):
    if not child.is_saved():
        child.put()
    return (folder.add(child), child)

def path(item):
    return '/%s' % '/'.join(reversed(list(i.name for i in parents(item))))

def resolve(expr, top=None):
    top = top or root()
    for name in expr.strip('/').split('/'):
        probe = top.child(name)
        if not probe:
            raise ValueError('Bad expr: %r (%r has no child %r).' % (
                expr, path(top), name
            ))
        top = probe
    return top


### Utilities

SLUG = re.compile(r'[^a-z0-9]+')
def make_slug(name):
    return SLUG.sub('-', name.lower()).strip('-')

def make_title(name):
    return name.replace('-', ' ').title()

def put(items):
    db.put(items)
    return items

def update(data, *args, **kw):
    data.update(*args, **kw)
    return data

def setdefault(data, **kw):
    for (key, val) in kw.iteritems():
        data.setdefault(key, val)
    return data

def dumps(obj):
    return db.model_to_protobuf(obj).Encode()

loads = db.model_to_protobuf

kind = db.class_for_kind


### Persist

def init(path, app_id):
    os.environ['APPLICATION_ID'] = app_id
    data = os.path.join(path, '%s.data' % app_id)
    created = not os.path.exists(data)

    apiproxy_stub_map.apiproxy.RegisterStub(
        'datastore_v3',
        datastore_file_stub.DatastoreFileStub(app_id, data)
    )

    return import_yaml(path) if created else root()

def import_yaml(path):
    root = built_root(os.path.basename(path))
    for name in glob.iglob('%s/*.yaml' % path):
        with ctx.closing(open(name, 'r')) as port:
            build_item(root, os.path.basename(name), yaml.load(port))
    return put(root)

def built_root(name):
    return Folder(name=name, key_name='root')

def build_item(root, name, data):
    model = kind(data.pop('kind', 'Item'))
    names = os.path.splitext(name)[0].split('--')
    (_, item) = put(add_child(
        build_folders(root, names[0:-1]),
        model(**setdefault(data, name=names[-1]))
    ))
    return item

def build_folders(top, names):
    for name in names:
        probe = top.child(name)
        if not probe:
            (_, probe) = put(add_child(top, Folder(name=name)))
        top = probe
    return top
