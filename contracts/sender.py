"""Strict senders: a request body may use only the fields its pinned schema defines.

The pinned schema is an OpenAPI 3.1 document. Unknown fields are found by walking
the body beside the operation's JSON request schema, following local `$ref`s;
the known fields' types are then checked with jsonschema against the same document.
"""
import json
import re
from urllib.parse import unquote

from jsonschema import Draft202012Validator

from . import pins
from .canonical import ContractError

METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace')
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
OBJECT = ('properties', 'patternProperties', 'additionalProperties')
ARRAY = ('prefixItems', 'items')
COMPOSED = ('allOf', 'anyOf', 'oneOf')


def _pointer(parts):
    return '#/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def _child(where, key):
    if isinstance(key, int):
        return f'{where}[{key}]'
    return f'{where}.{key}' if IDENTIFIER.fullmatch(key) else f'{where}[{json.dumps(key)}]'


class _Document:
    def __init__(self, document):
        self.document = document

    def resolve(self, schema):
        """The schema with its `$ref` chain resolved and sibling keywords kept."""
        seen = set()
        while isinstance(schema, dict) and '$ref' in schema:
            ref = schema['$ref']
            if not isinstance(ref, str) or not ref.startswith('#') or ref in seen:
                raise ContractError(f'unsupported or circular $ref {ref!r}')
            seen.add(ref)
            target = self.document
            for part in filter(None, ref[1:].split('/')):
                part = unquote(part).replace('~1', '/').replace('~0', '~')
                try:
                    target = target[int(part) if isinstance(target, list) else part]
                except (KeyError, IndexError, ValueError, TypeError):
                    raise ContractError(f'$ref {ref!r} does not resolve') from None
            siblings = {k: v for k, v in schema.items() if k != '$ref'}
            schema = {**target, **siblings} if isinstance(target, dict) and siblings else target
        return schema

    def unknown(self, schema, value, where):
        """The JSON paths in `value` that `schema` does not define."""
        found = []
        if isinstance(value, dict):
            for key, item in value.items():
                here = _child(where, key)
                defining = self._defines(schema, value, OBJECT, lambda s: self._property(s, key))
                if not defining:
                    found.append(here)
                for sub in defining:
                    found += self.unknown(sub, item, here)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                for sub in self._defines(schema, value, ARRAY, lambda s: self._item(s, index)):
                    found += self.unknown(sub, item, _child(where, index))
        return list(dict.fromkeys(found))

    def _defines(self, schema, value, keywords, own):
        """The subschemas that define a member, from `own` and composed branches.

        A schema with no member keywords and no composition leaves members free,
        as `{}` and `{"type": "object"}` do in JSON Schema.
        """
        schema = self.resolve(schema)
        if schema is True:
            return [{}]
        if not isinstance(schema, dict):
            return []
        if not any(k in schema for k in (*keywords, *COMPOSED)):
            return [{}]
        result = own(schema)
        for branch in schema.get('allOf', []):
            result += self._defines(branch, value, keywords, own)
        alternatives = schema.get('anyOf', []) + schema.get('oneOf', [])
        for branch in [b for b in alternatives if self._fits(b, value)] or alternatives:
            result += self._defines(branch, value, keywords, own)
        return result

    @staticmethod
    def _property(schema, key):
        found = [schema['properties'][key]] if key in schema.get('properties', {}) else []
        found += [s for p, s in schema.get('patternProperties', {}).items() if re.search(p, key)]
        extra = schema.get('additionalProperties')
        if not found and (isinstance(extra, dict) or extra is True):
            found.append({} if extra is True else extra)
        return found

    @staticmethod
    def _item(schema, index):
        prefix = schema.get('prefixItems', [])
        if index < len(prefix):
            return [prefix[index]]
        items = schema.get('items')
        return [{} if items is True else items] if isinstance(items, dict) or items is True else []

    def _fits(self, schema, value):
        schema = self.resolve(schema)
        if not isinstance(schema, dict) or 'type' not in schema:
            return True
        names = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        kinds = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None)}
        for name in names:
            if name in kinds and isinstance(value, kinds[name]):
                return True
            if name in ('number', 'integer') and isinstance(value, (int, float)) and not isinstance(value, bool):
                return True
        return False


def _operation(document, method, path):
    """The path template and operation for a request; exact templates win."""
    method = method.lower()
    if method not in METHODS:
        raise ContractError(f'unknown method {method.upper()}')
    paths = document.get('paths') if isinstance(document, dict) else None
    if not isinstance(paths, dict):
        raise ContractError('the pinned schema is not an OpenAPI document with paths')
    def matches(template):
        pattern = re.sub(r'\\\{[^/]+?\\\}', '[^/]+', re.escape(template))
        return re.fullmatch(pattern, path)
    for template in sorted(paths, key=lambda t: (t != path, '{' in t)):
        item = paths[template]
        if (template == path or matches(template)) and isinstance(item, dict) and method in item:
            return template, item[method]
    return None, None


def check_document(document, method, path, body):
    """The errors for sending `body` to `method path` under an OpenAPI document."""
    name = f'{method.upper()} {path}'
    template, operation = _operation(document, method, path)
    if operation is None:
        return [f'{name}: the pinned schema has no such operation']
    resolver = _Document(document)
    request = resolver.resolve(operation.get('requestBody') or {})
    media = (request.get('content') or {}).get('application/json') if isinstance(request, dict) else None
    if not isinstance(media, dict) or 'schema' not in media:
        if body is None:
            return []
        return [f'{name}: the pinned schema defines no JSON request body']
    pointer = _pointer(['paths', template, method.lower(), 'requestBody', 'content', 'application/json', 'schema'])
    if '$ref' in (operation.get('requestBody') or {}):
        pointer = operation['requestBody']['$ref'] + '/content/application~1json/schema'
    errors = [f'{name}: {where}: field not defined by the pinned schema'
              for where in resolver.unknown(media['schema'], body, '$')]
    validator = Draft202012Validator({**document, '$ref': pointer})
    for error in sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path)):
        if error.validator != 'additionalProperties' and error.validator != 'unevaluatedProperties':
            errors.append(f'{name}: {error.json_path}: {error.message}')
    return list(dict.fromkeys(errors))


def check(pin_dir, method, path, body):
    """The errors for sending `body`, empty when the pinned schema allows it."""
    return check_document(pins.schema(pin_dir), method, path, body)
