# -*- coding: utf-8 -*-

"""Test core functionality."""


#------------------------------------------------------------------------------
# Imports
#------------------------------------------------------------------------------

import logging
import os.path as op

from pytest import raises
from six import string_types

from ..core import Podoc, _find_path, _get_annotation, create_podoc
from ..utils import open_text

logger = logging.getLogger(__name__)


#------------------------------------------------------------------------------
# Testing utils
#------------------------------------------------------------------------------

def get_test_file_path(podoc, lang, filename):
    curdir = op.realpath(op.dirname(__file__))
    file_ext = podoc.get_file_ext(lang)
    # Construct the directory name for the language and test filename.
    dirname = op.realpath(op.join(curdir, '../', lang))
    path = op.join(dirname, 'test_files', filename + file_ext)
    assert op.exists(path)
    return path


def assert_equal(p0, p1):
    if isinstance(p0, string_types) and op.exists(p0):
        # TODO: non text files
        # NOTE: included text files have a trailing `\n`.
        assert_equal(open_text(p0), open_text(p1))
        return
    if isinstance(p0, string_types):
        assert p0.rstrip('\n') == p1.rstrip('\n')
        return
    assert p0 == p1


#------------------------------------------------------------------------------
# Tests utils
#------------------------------------------------------------------------------

def test_get_annotation():
    assert _get_annotation(lambda: None, 'a') is None


def test_find_path():
    assert _find_path([(1, 2), (2, 3)], 1, 2) == [1, 2]
    assert _find_path([(1, 2), (2, 3)], 1, 3) == [1, 2, 3]
    assert _find_path([(1, 2), (2, 3)], 1, 4) is None
    assert _find_path([(1, 2), (2, 3), (3, 4), (4, 5)], 1, 5) == \
        [1, 2, 3, 4, 5]
    assert _find_path([(1, 2), (2, 3), (1, 4), (4, 5)], 1, 5) == [1, 4, 5]


#------------------------------------------------------------------------------
# Tests podoc
#------------------------------------------------------------------------------

def test_podoc_fail():
    p = Podoc()
    with raises(ValueError):
        p.convert('hello', lang_list=['a', 'b'])


def test_podoc_convert_1(tempdir):
    p = Podoc()

    p.register_lang('lower', file_ext='.low')
    p.register_lang('upper', file_ext='.up')

    @p.register_func(source='lower', target='upper')
    def toupper(text):
        return text.upper()

    @p.register_func(source='upper', target='lower')
    def tolower(text):
        return text.lower()

    # Conversion with explicit path.
    assert p.conversion_pairs == [('lower', 'upper'), ('upper', 'lower')]
    assert p.convert('Hello', lang_list=['lower', 'upper', 'lower']) == 'hello'

    # Conversion with shortest path between source and target.
    assert p.convert('hello', source='lower', target='upper') == 'HELLO'

    with raises(ValueError):
        p.convert('hello', source='lower', target='unknown')

    # Convert a file.
    path = op.join(tempdir, 'test.up')
    path2 = op.join(tempdir, 'test.low')
    with open(path, 'w') as f:
        f.write('HELLO')
    assert p.convert(path, output=path2) == 'hello'
    with open(path2, 'r') as f:
        assert f.read() == 'hello'


def test_podoc_file(tempdir):
    p = Podoc()

    p.register_lang('a', file_ext='.a',
                    open_func=lambda path: 'a',
                    save_func=lambda path, contents: None,
                    )
    assert p.languages == ['a']

    assert p.get_lang_for_file_ext('.a') == 'a'
    with raises(ValueError):
        p.get_lang_for_file_ext('.b')

    fn = op.join(tempdir, 'aa.a')
    open(fn, 'w').close()
    open(op.join(tempdir, 'bb.b'), 'w').close()

    with raises(AssertionError):
        p.get_files_in_dir('')
    files = p.get_files_in_dir(tempdir, lang='a')
    assert len(files) == 1
    assert fn in files[0]


def test_podoc_open_save(tempdir):
    p = Podoc()
    p.register_lang('txt', file_ext='.txt')
    filename = 'test.txt'
    path = op.join(tempdir, filename)
    p.save(path, 'hello world')
    assert p.open(path) == 'hello world'


def test_create_podoc():
    podoc = create_podoc()
    assert 'ast' in podoc.languages


#------------------------------------------------------------------------------
# Tests all languages
#------------------------------------------------------------------------------

def test_all_open_save(tempdir, podoc, lang, test_file):
    """For all languages and test files, check round-tripping of open
    and save."""
    path = get_test_file_path(podoc, lang, test_file)
    contents = podoc.open(path)
    to_path = op.join(tempdir, test_file + podoc.get_file_ext(lang))
    podoc.save(to_path, contents)
    if lang == 'ast':
        assert_equal(podoc.open(path), podoc.open(to_path))
    else:
        # TODO: non-text formats
        assert_equal(path, to_path)


def test_all_convert(tempdir, podoc, source_target, test_file):
    source, target = source_target
    # Get the source and target file names.
    source_path = get_test_file_path(podoc, source, test_file)
    target_path = get_test_file_path(podoc, target, test_file)
    # Output file.
    # path = op.join(tempdir, op.basename(target_path))
    converted = podoc.convert(source_path, target=target)
    expected = podoc.open(target_path)
    # TODO: non-text formats
    # assert_text_files_equal(path, target_path)
    assert_equal(converted, expected)
    # logger.debug("{} and {} are equal.".format(path, target_path))
