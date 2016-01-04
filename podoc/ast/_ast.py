# -*- coding: utf-8 -*-

"""Markup AST."""


#------------------------------------------------------------------------------
# Imports
#------------------------------------------------------------------------------

import json
import logging

from six import string_types

from podoc.tree import Node, TreeTransformer
from podoc.plugin import IPlugin

logger = logging.getLogger(__name__)


#------------------------------------------------------------------------------
# AST
#------------------------------------------------------------------------------

# List of allowed Pandoc block names.
PANDOC_BLOCK_NAMES = (
    'Plain',
    'Para',
    'Header',
    'CodeBlock',
    'BlockQuote',
    'BulletList',
    'OrderedList',
    # The following are not supported yet in podoc.
    # 'RawBlock',
    # 'DefinitionList',
    # 'HorizontalRule',
    # 'Table',
    # 'Div',
)


# List of allowed Pandoc inline names.
PANDOC_INLINE_NAMES = (
    # 'Str',
    'Emph',
    'Strong',
    'Code',
    'Link',
    'Image',
    # The following are not supported yet in podoc.
    # 'LineBreak',
    # 'Math',
    # 'Strikeout',
    # 'Space',
)


class ASTNode(Node):
    def is_block(self):
        return self.name in PANDOC_BLOCK_NAMES

    def is_inline(self):
        return self.name in PANDOC_INLINE_NAMES

    def validate(self):
        if self.is_inline():
            # The children of an Inline node cannot be blocks.
            for child in self.children:
                if hasattr(child, 'is_block'):
                    assert not child.is_block()

    def to_pandoc(self):
        return PodocToPandoc().transform(self)


#------------------------------------------------------------------------------
# AST <-> pandoc
#------------------------------------------------------------------------------

def _node_dict(node, children=None):
        return {'t': node.name,
                'c': children or node.inner_contents}


class PodocToPandoc(object):
    def __init__(self):
        self.transformer = TreeTransformer()
        self.transformer.set_fold(lambda _: _)
        for m in dir(self):
            if m.startswith('transform_'):
                self.transformer.register(getattr(self, m))

    def transform_Node(self, node):
        return _node_dict(node)

    def transform_str(self, text):
        return {'t': 'Str', 'c': text}

    def transform_Header(self, node):
        children = [node.level, ['', [], []], node.inner_contents]
        return _node_dict(node, children)

    def transform_CodeBlock(self, node):
        children = [['', [node.lang], []], node.inner_contents]
        return _node_dict(node, children)

    def transform_OrderedList(self, node):
        children = [[node.start,
                    {"t": node.style, "c": []},
                    {"t": node.delim, "c": []}], node.inner_contents]
        return _node_dict(node, children)

    def transform_Link(self, node):
        children = [node.inner_contents, [node.url, '']]
        return _node_dict(node, children)

    def transform_Image(self, node):
        children = [node.inner_contents, [node.url, '']]
        return _node_dict(node, children)

    def transform_Code(self, node):
        children = [['', [], []], node.inner_contents]
        return _node_dict(node, children)

    def transform(self, ast):
        blocks = self.transformer.transform(ast)['c']
        return [{'unMeta': {}}, blocks]


def tree_from_pandoc(d):
    return PandocToPodoc().transform(d)


class PandocToPodoc(object):
    def transform(self, obj):
        if isinstance(obj, list):
            # Check that this is really the root.
            assert len(obj) == 2
            assert 'unMeta' in obj[0]
            # Special case: the root.
            # Process the root: obj is a list, and the second item
            # is a list of blocks to process.
            children = [self.transform(block) for block in obj[1]]
            return Node('root', children=children)
        # For normal nodes, obj is a dict.
        name, c = obj['t'], obj['c']
        # The transform_* functions take the 'c' attribute and the newly-
        # created node, and return the list of children dicts to process.
        func = getattr(self, 'transform_%s' % name, self.transform_Node)
        node = Node(name)
        # Create the node and return the list of children that have yet
        # to be processed.
        children = func(c, node)
        # Handle string nodes.
        if isinstance(children, string_types):
            return children
        assert isinstance(children, list)
        # Recursively transform all children and assign them to the node.
        node.children = [self.transform(child) for child in children]
        return node

    def transform_Node(self, c, node):
        # By default, obj['c'] is the list of children to process.
        return c

    def transform_Header(self, c, node):
        node.level, _, children = c
        return children

    def transform_CodeBlock(self, c, node):
        node.lang = c[0][1][0]
        return c[1]

    def transform_OrderedList(self, c, node):
        (node.start, style, delim), children = c[0]
        node.style = style['t']
        node.delim = delim['t']
        return children

    def transform_Code(self, c, node):
        return c[1]

    def transform_Image(self, c, node):
        return self.transform_Link(c, node)

    def transform_Link(self, c, node):
        assert len(c) == 2
        node.url = c[1][0]
        children = c[0]
        return children


#------------------------------------------------------------------------------
# AST plugin
#------------------------------------------------------------------------------

class ASTPlugin(IPlugin):
    """The file format is JSON, same as the pandoc json format."""
    def attach(self, podoc):
        # An object in the language 'ast' is an instance of AST.
        podoc.register_lang('ast', file_ext='.json',
                            open_func=self.open, save_func=self.save)

    def open(self, path):
        """Open a .json file and return an AST instance."""
        logger.debug("Open JSON file `%s`.", path)
        with open(path, 'r') as f:
            ast_obj = json.load(f)
        assert isinstance(ast_obj, list)
        # ast = AST.from_dict(ast_obj)
        # assert isinstance(ast, AST)
        # return ast

    def save(self, path, ast):
        """Save an AST instance to a JSON file."""
        # assert isinstance(ast, AST)
        ast_obj = ast.to_dict()
        assert isinstance(ast_obj, list)
        logger.debug("Save JSON file `%s`.", path)
        # with open(path, 'w') as f:
        #     json.dump(ast_obj, f, sort_keys=True, indent=2)
        #     # Add a new line at the end.
        #     f.write('\n')
