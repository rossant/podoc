# -*- coding: utf-8 -*-

"""Core functionality."""


#-------------------------------------------------------------------------------------------------
# Imports
#-------------------------------------------------------------------------------------------------

from collections import defaultdict
import glob
import inspect
import logging
import os.path as op

from .utils import Bunch, load_text, dump_text, _create_dir_if_not_exists
from .plugin import get_plugins

logger = logging.getLogger(__name__)


#-------------------------------------------------------------------------------------------------
# Graph routines
#-------------------------------------------------------------------------------------------------

def _graph_from_edges(edges):
    """Return the adjacency list of a graph defined by a list of edges."""
    g = defaultdict(set)
    for a, b in edges:
        g[a].add(b)
    return g


def _bfs_paths(graph, start, target):
    """Generate paths from start to target."""
    # http://eddmann.com/posts/depth-first-search-and-breadth-first-search-in-python/  # noqa
    queue = [(start, [start])]
    while queue:
        (vertex, path) = queue.pop(0)
        for next in graph[vertex] - set(path):
            if next == target:
                yield path + [next]
            else:
                queue.append((next, path + [next]))


def _bfs_component(graph, start):
    visited, queue = set(), [start]
    while queue:
        vertex = queue.pop(0)
        if vertex not in visited:
            visited.add(vertex)
            queue.extend(graph[vertex] - visited)
    return visited


def _find_path(edges, start, target):
    """Return a shortest path in a graph defined by a list of edges."""
    graph = _graph_from_edges(edges)
    try:
        return next(_bfs_paths(graph, start, target))
    except StopIteration:
        return None


def _connected_component(edges, start):
    graph = _graph_from_edges(edges)
    # We remove the start from the component.
    return sorted(_bfs_component(graph, start) - set([start]))


#-------------------------------------------------------------------------------------------------
# Main class
#-------------------------------------------------------------------------------------------------

def _get_annotation(func, name):
    return getattr(func, '__annotations__', {}).get(name, None)


class Podoc(object):
    """Conversion pipeline for markup documents.

    This class implements the core conversion functionality of podoc.

    Parameters
    ----------

    plugins : list of str (None)
        List of plugins to load. By default, load all plugins found.
    with_pandoc : bool (True)
        Whether to load all pandoc conversion paths.

    """

    def __init__(self, plugins=None, with_pandoc=True):
        self._funcs = {}  # mapping `(lang0, lang1) => func`
        self._langs = {}  # mapping `lang: Bunch()`
        self._load_plugins(plugins, with_pandoc)

    def _load_plugins(self, plugins=None, with_pandoc=True):
        """Load plugins. By default (None), all plugins found are loaded."""
        # Load plugins.
        plugins = plugins if plugins is not None else get_plugins()
        for p in plugins:
            # Skip pandoc plugin.
            if not with_pandoc and p.__name__ == 'PandocPlugin':
                continue
            p().attach(self)

    # Main methods
    # --------------------------------------------------------------------------------------------

    def register_func(self, func=None, source=None, target=None,
                      pre_filter=None, post_filter=None,
                      ):
        """Register a conversion function between two languages."""
        if func is None:
            return lambda _: self.register_func(_, source=source,
                                                target=target)
        assert func
        assert 'context' in inspect.getargspec(func).args
        source = source or _get_annotation(func, 'source')
        target = target or _get_annotation(func, 'target')
        assert source
        assert target
        if (source, target) in self._funcs:
            logger.debug("Conversion `%s -> %s` already registered, skipping.",
                         source, target)
            return
        logger.log(5, "Register conversion `%s -> %s`.", source, target)
        self._funcs[(source, target)] = Bunch(func=func,
                                              pre_filter=pre_filter,
                                              post_filter=post_filter,
                                              )

    def register_lang(self, name, file_ext=None,
                      load_func=None, dump_func=None,
                      loads_func=None, dumps_func=None,
                      eq_filter=None,
                      **kwargs):
        """Register a language with a file extension and load/dump
        functions."""
        if file_ext:
            assert file_ext.startswith('.')
        if name in self._langs:
            logger.log(5, "Language `%s` already registered, skipping.", name)
            return
        logger.log(5, "Register language `%s`.", name)
        # Default parameters.
        load_func = load_func or load_text
        dump_func = dump_func or dump_text
        loads_func = loads_func or (lambda _: _)
        dumps_func = dumps_func or (lambda _: _)
        self._langs[name] = Bunch(file_ext=file_ext,
                                  load_func=load_func,
                                  dump_func=dump_func,
                                  loads_func=loads_func,
                                  dumps_func=dumps_func,
                                  eq_filter=eq_filter,
                                  **kwargs)

    def _create_context(self, path=None, source=None, target=None, lang_chain=None,
                        output=None, output_dir=None,
                        ):

        # Infer source and target from lang_chain.
        if lang_chain is not None:
            assert len(lang_chain) >= 2
            source = lang_chain[0]
            target = lang_chain[-1]

        # Use real paths.
        if path is not None:
            path = op.realpath(path)
        if output is not None:
            output = op.realpath(output)
        if output_dir is not None:
            output_dir = op.realpath(output_dir)

        # NOTE: 'json' is an alias for 'ast', to match with pandoc's terminology.
        source = source if source != 'json' else 'ast'
        target = target if target != 'json' else 'ast'

        # If the output is specified and not the target, infer the target
        # from the file extension.
        if target is None and output is not None:
            target = self.get_lang_for_file_ext(op.splitext(output)[1])
        assert target

        # NOTE: decide whether the object is a path or contents string.
        if path is not None:
            if not op.exists(path):
                raise ValueError("File %s does not exist.", path)
            # Get the source from the file extension
            if source is None and lang_chain is None:
                source = self.get_lang_for_file_ext(op.splitext(path)[1])
        assert source

        # At this point, we should have a non-empty object.
        if lang_chain is None:
            # Find the shortest path from source to target in the conversion graph.
            assert source and target
            lang_chain = _find_path(self.conversion_pairs,
                                    source, target)
            if not lang_chain:
                raise ValueError("No path found from `{}` to `{}`.".format(
                                 source, target))
        assert isinstance(lang_chain, (tuple, list))

        # Process output_dir.
        if path and output_dir:
            _create_dir_if_not_exists(output_dir)
            extension = self.get_file_ext(target)
            # Construct the output filename.
            output = op.join(output_dir, op.splitext(op.basename(path))[0] + extension)

        return Bunch(path=path, source=source, target=target,
                     lang_chain=lang_chain, output=output)

    def _make_conversion(self, obj, context):
        # Iterate over all successive pairs.
        for t0, t1 in zip(context.lang_chain, context.lang_chain[1:]):
            # Get the function registered for t0, t1.
            fd = self._funcs.get((t0, t1), None)
            if not fd:
                raise ValueError("No function registered for `{}` => `{}`.".
                                 format(t0, t1))
            f = fd.func
            # Pre-filter.
            obj = fd.pre_filter(obj, context=context) if fd.pre_filter else obj
            # Perform the conversion.
            obj = f(obj, context=context)
            # Post-filter.
            obj = fd.post_filter(obj, context=context) if fd.post_filter else obj
        return obj

    def _convert_from_context(self, obj_or_path, context, is_path=None, do_append=None):
        # Load the object from disk if necessary.
        obj = self.load(obj_or_path, context.source, context=context) if is_path else obj_or_path
        # Make the conversion in memory.
        obj = self._make_conversion(obj, context)
        # Save the file, unless the conversion function did it (output_file_required).
        if context.output and not context.get('output_file_required', None):
            output_dir = op.dirname(context.output)
            _create_dir_if_not_exists(output_dir)
            self.dump(obj, context.output, lang=context.target,
                      context=context, do_append=do_append)
        return obj

    def convert_text(self, text, source=None, target=None, lang_chain=None,
                     output=None, output_dir=None,
                     return_context=False):
        # Create the context object.
        context = self._create_context(source=source, target=target, lang_chain=lang_chain,
                                       output=output, output_dir=output_dir,)
        obj = self._convert_from_context(text, context, is_path=False)
        if return_context:
            return obj, context
        return obj

    def convert_files(self, paths, source=None, target=None, lang_chain=None,
                      output=None, output_dir=None):
        """Convert a file by passing it through a chain of conversion functions."""
        objs = []
        for i, path in enumerate(paths):
            # Create the context object.
            context = self._create_context(path=path, source=source, target=target,
                                           lang_chain=lang_chain,
                                           output=output, output_dir=output_dir,
                                           )
            logger.debug("Converting `%s` from %s to %s.", op.basename(context.path),
                         context.source, context.target)
            obj = self._convert_from_context(context.path, context,
                                             is_path=True, do_append=i >= 1)
            objs.append(obj)
        return objs[0] if objs and len(objs) else objs

    def convert_file(self, path, source=None, target=None, lang_chain=None,
                     output=None, output_dir=None, return_context=False):
        # Create the context object.
        context = self._create_context(path=path, source=source, target=target,
                                       lang_chain=lang_chain,
                                       output=output, output_dir=output_dir,
                                       )
        logger.debug("Converting `%s` from %s to %s.", op.basename(context.path),
                     context.source, context.target)
        obj = self._convert_from_context(context.path, context, is_path=True)
        if return_context:
            return obj, context
        return obj

    def pre_filter(self, obj, source, target):
        fd = self._funcs.get((source, target), None)
        if fd and fd.pre_filter:
            return fd.pre_filter(obj)
        else:
            return obj

    # Properties
    # --------------------------------------------------------------------------------------------

    @property
    def languages(self):
        """List of all registered languages."""
        return sorted(self._langs)

    @property
    def file_extensions(self):
        """List of all registered file extensions."""
        return sorted(set(lang.file_ext for lang in self._langs.values()
                          if lang.file_ext))

    @property
    def conversion_pairs(self):
        """List of registered conversion pairs."""
        return sorted(self._funcs.keys())

    # File-related methods
    # --------------------------------------------------------------------------------------------

    def get_target_languages(self, lang):
        """List of languages to which a given language can be converted to."""
        return _connected_component(self.conversion_pairs, lang)

    def get_files_in_dir(self, path, lang=None):
        """Return the list of files of a given language in a directory."""
        assert path
        path = op.realpath(op.expanduser(path))
        assert op.exists(path)
        assert op.isdir(path)
        # Find the file extension for the given language.
        file_ext = (self._langs[lang].file_ext or '') if lang else ''
        filenames = glob.glob(op.join(path, '*' + file_ext))
        return [op.join(path, fn) for fn in filenames]

    def get_lang_for_file_ext(self, file_ext):
        """Get the language registered with a given file extension."""
        for name, b in self._langs.items():
            if b.file_ext == file_ext:
                return name
        raise ValueError(("The file extension `{}` hasn't been "
                          "registered.").format(file_ext))

    def get_file_ext(self, lang):
        """Return the file extension registered for a given language."""
        return self._langs[lang].file_ext

    def load(self, path, lang=None, context=None):
        """Load a file which has a registered file extension."""
        # Find the language corresponding to the file's extension.
        file_ext = op.splitext(path)[1]
        lang = lang or self.get_lang_for_file_ext(file_ext)
        func = self._langs[lang].load_func
        kwargs = {'context': context} if 'context' in inspect.getargspec(func).args else {}
        # Load the file using the function registered for the language.
        return func(path, **kwargs)

    def dump(self, contents, path, lang=None, context=None, do_append=None):
        """Dump an object to a file."""
        # Find the language corresponding to the file's extension.
        file_ext = op.splitext(path)[1]
        lang = lang or self.get_lang_for_file_ext(file_ext)
        func = self._langs[lang].dump_func
        kwargs = {'context': context} if 'context' in inspect.getargspec(func).args else {}
        if 'do_append' in inspect.getargspec(func).args:
            kwargs.update({'do_append': do_append})
        # Dump the file using the function registered for the language.
        return func(contents, path, **kwargs)

    def loads(self, s, lang=None):
        """Load an object from its string representation."""
        assert lang
        # Load the string using the function registered for the language.
        return self._langs[lang].loads_func(s)

    def dumps(self, contents, lang=None):
        """Dump an object to a string."""
        assert lang
        # Dump the string using the function registered for the language.
        return self._langs[lang].dumps_func(contents)

    def assert_equal(self, obj0, obj1, lang=None):
        """Assert that two objects are equal."""
        assert lang
        f = self._langs[lang].eq_filter
        if not f:
            assert obj0 == obj1
            return
        assert f(obj0) == f(obj1)
