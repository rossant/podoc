# -*- coding: utf-8 -*-

"""Test core functionality."""


#------------------------------------------------------------------------------
# Imports
#------------------------------------------------------------------------------

import os.path as op

from ..core import open_text, save_text
from ..plugin import IPlugin


#------------------------------------------------------------------------------
# Tests
#------------------------------------------------------------------------------

def test_open_save_text(tempdir, hello_markdown):
    path = op.join(tempdir, 'test.txt')

    save_text(path, hello_markdown)
    assert open_text(path) == hello_markdown


def test_podoc_trivial(tempdir, podoc, hello_markdown):
    # In-memory
    assert podoc.convert_contents(hello_markdown) == hello_markdown

    # Convert from file to file
    from_path = op.join(tempdir, 'test_from.txt')
    to_path = op.join(tempdir, 'test_to.txt')
    save_text(from_path, hello_markdown)
    podoc.convert_file(from_path, to_path)
    assert open_text(to_path) == hello_markdown


def test_podoc_complete(podoc):
    podoc.set_file_opener(lambda path: (path + ' open'))
    podoc.add_preprocessor(lambda x: x[0].upper() + x[1:])
    podoc.set_reader(lambda x: x.split(' '))
    podoc.add_filter(lambda x: (x + ['filter']))
    podoc.set_writer(lambda x: ' '.join(x))
    podoc.add_postprocessor(lambda x: x[:-1] + x[-1].upper())
    podoc.set_file_saver(lambda path, contents: (contents + ' in ' + path))

    contents = 'abc'
    assert podoc.convert_contents(contents) == 'Abc filteR'
    assert podoc.convert_file(contents, 'path') == 'Abc open filteR in path'


def test_podoc_plugins(podoc):

    class MyPlugin1(IPlugin):
        def register(self, podoc):
            podoc.set_file_opener(lambda path: (path + ' open'))
            podoc.add_preprocessor(lambda x: x[0].upper() + x[1:])

    class MyPlugin2(IPlugin):
        def register(self, podoc):
            podoc.add_postprocessor(lambda x: x[:-1] + x[-1].upper())
            podoc.set_file_saver(lambda path, contents: (contents +
                                                         ' in ' +
                                                         path))

    class MyPluginFrom(IPlugin):
        def register_from(self, podoc):
            podoc.set_reader(lambda x: x.split(' '))
            podoc.add_filter(lambda x: (x + ['filter']))

    class MyPluginTo(IPlugin):
        def register_to(self, podoc):
            podoc.set_writer(lambda x: ' '.join(x))

    plugins = (MyPlugin1, MyPlugin2)
    plugins_from = (MyPluginFrom,)
    plugins_to = (MyPluginTo,)
    podoc.set_plugins(plugins, plugins_from, plugins_to)

    contents = 'abc'
    assert podoc.convert_contents(contents) == 'Abc filteR'
    assert podoc.convert_file(contents, 'path') == 'Abc open filteR in path'
