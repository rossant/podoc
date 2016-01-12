# -*- coding: utf-8 -*-

"""Markdown plugin."""


#------------------------------------------------------------------------------
# Imports
#------------------------------------------------------------------------------

import logging

from CommonMark import Parser
from six import string_types

from podoc.plugin import IPlugin
from podoc.tree import TreeTransformer
from podoc.ast import ASTNode
from podoc.markdown.renderer import MarkdownRenderer

logger = logging.getLogger(__name__)


#------------------------------------------------------------------------------
# Markdown reader (using CommonMark-py)
#------------------------------------------------------------------------------

def _iter_child(cm):
    child = cm.first_child
    while child is not None:
        yield child
        child = child.nxt


class CommonMarkToAST(TreeTransformer):
    _name_mapping = {
        'Paragraph': 'Para',
        'Heading': 'Header',
        'Softbreak': 'LineBreak',
        'Item': 'ListItem',
    }

    def get_node_name(self, obj):
        # Convert from CommonMark name to Pandoc
        return self._name_mapping.get(obj.t, obj.t)

    def get_node_children(self, obj):
        return list(_iter_child(obj))

    def transform_main(self, cm):
        # TODO: should be def transform() for consistency with the other way
        children = [self.transform(block)
                    for block in self.get_node_children(cm)]
        return ASTNode('root', children=children)

    def transform(self, obj):
        if isinstance(obj, string_types):
            return obj
        # obj is a CommonMark.Node instance.
        name = self.get_node_name(obj)

        # The transform_* functions take the 'c' attribute and the newly-
        # created node, and return the list of children objects to process.
        if name == 'List':
            # Special treatment for lists. In CommonMark, there is a single
            # node type, List, and the type (Bullet or Ordered) is found
            # in list_data['type']
            # The name is BulletList or OrderedList.
            name = obj.list_data['type'] + 'List'
            func = (self.transform_BulletList
                    if obj.list_data['type'] == 'Bullet'
                    else self.transform_OrderedList)
        else:
            func = getattr(self, 'transform_%s' % name, self.transform_Node)

        node = ASTNode(name)
        children = func(obj, node)
        if isinstance(children, string_types):
            return children
        assert isinstance(children, list)
        # Recursively transform all children and assign them to the node.
        node.children = [self.transform(child) for child in children]
        return node

    def transform_Node(self, obj, node):
        return list(_iter_child(obj))

    def transform_Code(self, obj, node):
        return [obj.literal]

    def transform_Text(self, obj, node):
        return obj.literal

    def transform_Link(self, obj, node):
        node.url = obj.destination
        return list(_iter_child(obj))

    def transform_Image(self, obj, node):
        node.url = obj.destination
        return list(_iter_child(obj))

    def transform_CodeBlock(self, obj, node):
        node.lang = obj.info
        return [obj.literal]

    def transform_BlockQuote(self, obj, node):
        return list(_iter_child(obj))

    def transform_Header(self, obj, node):
        node.level = obj.level
        return list(_iter_child(obj))

    def transform_BulletList(self, obj, node):
        node.bullet_char = obj.list_data['bullet_char']
        node.delimiter = obj.list_data['delimiter'] or ' '
        return list(_iter_child(obj))

    def transform_OrderedList(self, obj, node):
        node.start = obj.list_data['start']
        assert node.start >= 0
        node.delimiter = obj.list_data['delimiter'] or ' '
        return list(_iter_child(obj))


#------------------------------------------------------------------------------
# Markdown renderer
#------------------------------------------------------------------------------

class ASTToMarkdown(TreeTransformer):
    """Read an AST and render a Markdown string."""

    def __init__(self):
        self.renderer = MarkdownRenderer()
        # Nested lists.
        self._lists = []

    def fold(self, transformed_children, node=None):
        delim = '\n\n' if node.name == 'root' else ''
        return delim.join(transformed_children)

    def get_inner_contents(self, node):
        return self.fold(self.transform_children(node), node)

    def transform_str(self, text):
        return text

    def transform_Node(self, node):
        return self.get_inner_contents(node)

    # Block nodes
    # -------------------------------------------------------------------------

    def transform_Plain(self, node):
        return self.renderer.text(self.get_inner_contents(node))

    def transform_Para(self, node):
        return self.transform_Plain(node)

    def transform_Header(self, node):
        return self.renderer.heading(self.get_inner_contents(node),
                                     level=node.level)

    def transform_CodeBlock(self, node):
        return self.renderer.code(self.get_inner_contents(node),
                                  lang=node.lang)

    def transform_BlockQuote(self, node):
        return self.renderer.quote(self.get_inner_contents(node))

    def _write_list(self, node, list_type):
        assert list_type in ('bullet', 'ordered')
        if list_type == 'bullet':
            bullet = node.bullet_char
            suffix = node.delimiter
        elif list_type == 'ordered':
            bullet = node.start
            suffix = node.delimiter
            if not suffix.endswith(' '):
                suffix += ' '
        # This is a list of processed items.
        items = self.transform_children(node)
        out = []
        for item in items:
            # We indent all lines in the item.
            item_lines = item.splitlines()
            item = '\n'.join((('  ' if i else '') + line)
                             for i, line in enumerate(item_lines))
            # We add the bullet and suffix to the first line in the item.
            out.append(str(bullet) + suffix + item)
            # We increase the current ordered list number.
            if list_type == 'ordered':
                bullet += 1
        return '\n'.join(out)

    def transform_BulletList(self, node):
        return self._write_list(node, 'bullet')

    def transform_OrderedList(self, node):
        return self._write_list(node, 'ordered')

    def transform_ListItem(self, node):
        out = self.get_inner_contents(node)
        return out

    # Inline nodes
    # -------------------------------------------------------------------------

    def transform_Emph(self, node):
        return self.renderer.emph(self.get_inner_contents(node))

    def transform_Strong(self, node):
        return self.renderer.strong(self.get_inner_contents(node))

    def transform_Code(self, node):
        return self.renderer.inline_code(
            self.get_inner_contents(node))

    def transform_LineBreak(self, node):
        return self.renderer.linebreak()

    def transform_Link(self, node):
        return self.renderer.link(self.get_inner_contents(node),
                                  node.url)

    def transform_Image(self, node):
        return self.renderer.image(self.get_inner_contents(node),
                                   node.url)


#------------------------------------------------------------------------------
# Markdown plugin
#------------------------------------------------------------------------------

class Markdown(IPlugin):
    def attach(self, podoc):
        podoc.register_lang('markdown', file_ext='.md')
        podoc.register_func(source='markdown', target='ast',
                            func=self.read_markdown)
        podoc.register_func(source='ast', target='markdown',
                            func=self.write_markdown)

    def read_markdown(self, contents):
        parser = Parser()
        cm = parser.parse(contents)
        ast = CommonMarkToAST().transform_main(cm)
        return ast

    def write_markdown(self, ast):
        return ASTToMarkdown().transform(ast)