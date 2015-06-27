import _ast
import ast
import collections
import flask
import json

app = flask.Flask(__name__)


class Error(Exception):
    pass


class UnrecognizedKeyError(Error):
    pass


@app.route("/")
def hello():
    return flask.render_template('home.html')


@app.route('/key_event', methods=['POST'])
def key_event():
    key = flask.request.data
    try:
        return json.dumps(get_global_context().do_action(key))
    except UnrecognizedKeyError:
        return ''


# TODO: Generalize this to use contexts properly
@app.route('/get_current')
def get_current():
    ast_context = get_global_context().contexts[0]
    return json.dumps(ast_context.get_display_dict())


class DisplayContainer(object):

    def __init__(self, node):
        self.node = node
        self.name = type(node).__name__
        self.display_nodes = collections.OrderedDict()
        for field_name, value in ast.iter_fields(node):
            # TODO: Actually determine the None case better.
            if isinstance(value, list) or value is None:
                self.display_nodes[field_name] = ListFieldNode(node, field_name)
            elif isinstance(value, _ast.AST):
                self.display_nodes[field_name] = FieldNode(node, field_name)
            else:
                self.display_nodes[field_name] = PrimativeFieldNode(
                    node, field_name)

    def to_dict(self):
        children = [display_node.to_dict() 
                    for display_node in self.display_nodes.values()]
        return {
            'name': type(self.node).__name__,
            'children': children
        }

    def get_node_with_id(self, id_):
        for display_node in self.display_nodes:
            child_with_id = display_node.get_node_with_id(id_)
            if child_with_id:
                return child_with_id


class DisplayComponent(object):

    def __init__(self, field_node):
        self._field_node = field_node

    def to_dict(self):
        return {}


class CursorComponent(DisplayComponent):

    def __init__(self, field_node):
        super(CursorComponent, self).__init__(field_node)
        self.cursor = False

    def to_dict(self):
        return {'cursor': self.cursor}

    def get_node_with_cursor(self):
        if self.cursor:
            return self._field_node
        for child_field_node in self._field_node.get_child_field_nodes():
            child_with_cursor = child_field_node.get_component(
                CursorComponent).get_node_with_cursor()
            if child_with_cursor:
                return child_with_cursor


class DisplayNode(object):

    _current_id = 0
    _component_types = [CursorComponent]

    @classmethod
    def _get_id(cls):
        DisplayNode._current_id += 1
        return DisplayNode._current_id

    def __init__(self, node, field_name):
        self.node = node
        self.field_name = field_name
        self.id = self._get_id()

        self._display_components = {
            component_type: component_type(self) 
            for component_type in self._component_types}

    def get_component(self, component_type):
        return self._display_components[component_type]

    def _get_name(self):
        raise NotImplementedError()

    def to_dict(self):
        node_dict = {
            'name': self._get_name(), 
            'id': self.id
        }
        for display_component in self._display_components.values():
            node_dict.update(display_component.to_dict())
        for item_node in self.get_child_field_nodes():
            node_dict.setdefault('children', []).append(item_node.to_dict())
        return node_dict

    def get_child_ast_displays(self):
        raise NotImplementedError()

    def get_child_field_nodes(self):
        child_field_nodes = []
        for ast_display in self.get_child_ast_displays():
            child_field_nodes.extend(ast_display.display_nodes.values())
        return child_field_nodes

    def get_parent_field_node(self, root_field_node):
        parent_candidates = [root_field_node]
        while parent_candidates:
            parent_candidate = parent_candidates.pop()
            candidate_children = parent_candidate.get_child_field_nodes()
            if self in candidate_children:
                return parent_candidate
            parent_candidates.extend(candidate_children)

    def get_node_with_id(self, id_):
        if self.id == id_:
            return self
        for field_node in self.get_child_field_nodes():
            node_with_id = field_node.get_node_with_id(id_)
            if node_with_id:
                return node_with_id


class FieldNode(DisplayNode):

    def get_child_ast_displays(self):
        return [get_display(getattr(self.node, self.field_name))]

    def _get_name(self):
        return '{} = {}'.format(
            self.field_name, self.get_child_ast_displays()[0].name)


class ListFieldNode(DisplayNode):

    def __init__(self, node, field_name):
        super(ListFieldNode, self).__init__(node, field_name)
        self._item_nodes = [ListItemNode(node, field_name, index)
                           for index in xrange(len(getattr(node, field_name)))]

    def get_child_ast_displays(self):
        ast_displays = []
        for item_node in self.get_child_field_nodes():
            ast_displays.extend(item_node.get_child_ast_displays())
        return ast_displays

    def get_child_field_nodes(self):
        # First we have to make sure they're in sync with the node.
        list_value = getattr(self.node, self.field_name)
        if len(list_value) < len(self._item_nodes):
            self._item_nodes = self._item_nodes[:len(list_value)]
        elif len(list_value) > len(self._item_nodes):
            self._item_nodes.extend(
                [ListItemNode(node, field_name, index)
                 for index in xrange(self._item_nodes, self.list_value)])

        return self._item_nodes

    def _get_name(self):
        return '{} = list'.format(self.field_name)

    def to_dict(self):
        node_dict = super(ListFieldNode, self).to_dict()
        if not node_dict.get('children', None):
            node_dict.pop('name')
        return node_dict

    def get_node_with_id(self, id_):
        super_result = super(FieldNode, self).get_node_with_id(id_)
        if super_result:
            return super_result
        for item_node in self.get_child_field_nodes():
            item_with_id = item_node.get_node_with_id(id_)
            if item_with_id:
                return item_with_id


class ListItemNode(DisplayNode):

    def __init__(self, node, field_name, index):
        super(ListItemNode, self).__init__(node, field_name)
        self.index = index

    def get_child_ast_displays(self):
        return [get_display(getattr(self.node, self.field_name)[self.index])]

    def _get_name(self):
        return '{} = {}'.format(
            self.index, self.get_child_ast_displays()[0].name)


class PrimativeFieldNode(DisplayNode):

    def get_child_ast_displays(self):
        return []

    def _get_name(self):
        return '{} = {}'.format(
            self.field_name, getattr(self.node, self.field_name))


def get_display(node):
    if not hasattr(node, 'display'):
        node.display = DisplayContainer(node)
    return node.display


f = """
a = 10
b = a + 4
c = "hello world"
"""


_global_context = None


def get_global_context():
    global _global_context
    if not _global_context:
        _global_context = GlobalContext()
    return _global_context


def clear_global_context():
    global _global_context
    _global_context = None


class Context(object):

    def __init__(self):
        self.contexts = []
        self.modes = []
        self.active_context = None

    def can_perform_action(self, key_combo):
        if (self.active_context and 
            self.active_context.can_perform_action(key_combo)):
            return True
        for mode in self.modes:
            if key_combo in mode.keymap:
                return True

    def do_action(self, key_combo):
        if (self.active_context and 
            self.active_context.can_perform_action(key_combo)):
            return self.active_context.do_action(key_combo)
        for mode in self.modes:
            if key_combo in mode.keymap:
                effect = mode.keymap[key_combo].perform(self)
                return [frontend_effect.to_dict() 
                        for frontend_effect in effect.frontend_effects]
        raise UnrecognizedKeyError(
            'No action associated with "{}"'.format(key_combo))


class GlobalContext(Context):

    def __init__(self):
        super(GlobalContext, self).__init__()
        self.active_context = AstContext()
        self.contexts = [self.active_context]


class AstContext(Context):

    def __init__(self):
        super(AstContext, self).__init__()
        self.modes = [AstMode()]
        self.ast = ast.parse(f)

        # Init the cursor
        self.get_root_field_node().get_component(CursorComponent).cursor = True

    def get_display_dict(self):
        return get_display(self.ast).to_dict()

    def get_root_field_node(self):
        return get_display(self.ast).display_nodes.values()[0]



class Mode(object):

    def __init__(self):
        self.keymap = {}


class AstMode(Mode):

    def __init__(self):
        super(AstMode, self).__init__()
        self.keymap = {
            'h': CursorShallowerAction(),
            'l': CursorDeeperAction(),
            'j': CursorDownAction(),
            'k': CursorUpAction(),
            't': ToggleAction()
        }


class Action(object):

    def perform(self, context):
        pass


class ToggleAction(Action):

    def perform(self, context):
        cursor_node = context.get_root_field_node().get_component(
            CursorComponent).get_node_with_cursor()
        return Effect(
            frontend_effects=(FrontendEffect('toggle', cursor_node.id),)
        )


class CursorDeeperAction(Action):

    def perform(self, context):
        cursor_node = context.get_root_field_node().get_component(
            CursorComponent).get_node_with_cursor()
        if not cursor_node:
            context.get_root_field_node().get_component(
                CursorComponent).cursor = True
        else:
            child_nodes = cursor_node.get_child_field_nodes()
            if child_nodes:
                cursor_node.get_component(CursorComponent).cursor = False
                child_nodes[0].get_component(CursorComponent).cursor = True

        return Effect(
            frontend_effects=(FrontendEffect('refresh_ast'),)
        )


class CursorShallowerAction(Action):

    def perform(self, context):
        cursor_node = context.get_root_field_node().get_component(
            CursorComponent).get_node_with_cursor()
        if not cursor_node:
            context.get_root_field_node().get_component(
                CursorComponent).cursor = True
        else:
            parent_node = cursor_node.get_parent_field_node(
                context.get_root_field_node())
            if parent_node:
                cursor_node.get_component(CursorComponent).cursor = False
                parent_node.get_component(CursorComponent).cursor = True

        return Effect(
            frontend_effects=(FrontendEffect('refresh_ast'),)
        )


class CursorDownAction(Action):

    def perform(self, context):
        cursor_node = context.get_root_field_node().get_component(
            CursorComponent).get_node_with_cursor()
        if not cursor_node:
            context.get_root_field_node().get_component(
                CursorComponent).cursor = True
        else:
            parent_node = cursor_node.get_parent_field_node(
                context.get_root_field_node())
            if parent_node:
                all_children = parent_node.get_child_field_nodes()
                current_index = all_children.index(cursor_node)
                if current_index < len(all_children) - 1:
                    cursor_node.get_component(CursorComponent).cursor = False
                    all_children[current_index+1].get_component(
                        CursorComponent).cursor = True

        return Effect(
            frontend_effects=(FrontendEffect('refresh_ast'),)
        )


class CursorUpAction(Action):

    def perform(self, context):
        cursor_node = context.get_root_field_node().get_component(
            CursorComponent).get_node_with_cursor()
        if not cursor_node:
            context.get_root_field_node().get_component(
                CursorComponent).cursor = True
        else:
            parent_node = cursor_node.get_parent_field_node(
                context.get_root_field_node())
            if parent_node:
                all_children = parent_node.get_child_field_nodes()
                current_index = all_children.index(cursor_node)
                if current_index > 0:
                    cursor_node.get_component(CursorComponent).cursor = False
                    all_children[current_index-1].get_component(
                        CursorComponent).cursor = True

        return Effect(
            frontend_effects=(FrontendEffect('refresh_ast'),)
        )


class Effect(object):

    def __init__(
        self, 
        frontend_effects=(), 
        new_context=None, 
        modes_to_remove=(),
        modes_to_add=()):
      self.frontend_effects = frontend_effects
      self.new_context = new_context
      self.modes_to_remove = modes_to_remove
      self.modes_to_add = modes_to_add


class FrontendEffect(object):

    def __init__(self, action_name, *action_args):
        self.action_name = action_name
        self.action_args = action_args

    def to_dict(self):
        return {'action': self.action_name, 'args': self.action_args}



if __name__ == "__main__":
    app.run(debug=True)