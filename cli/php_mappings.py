"""
1st party php classes via the namespace declarations : the cli sends them to the
parsers as X-Path-Mappings ( dotted from, as the parsers bind a use import ).
"""
import pathlib
import re
import typing

PHP_CLASS_NAME: typing.Final[re.Pattern[str]] = re.compile(r'\b[A-Z]\w*\b')
PHP_COMMENT: typing.Final[re.Pattern[str]] = re.compile(r'//[^\n]*|#(?!\[)[^\n]*|/\*.*?\*/', re.DOTALL)
PHP_NAMESPACE: typing.Final[re.Pattern[str]] = re.compile(r'^\s*namespace\s+([\w\\]+)\s*[;{]', re.MULTILINE)
PHP_USE: typing.Final[re.Pattern[str]] = re.compile(r'^\s*use\s+\\?([\w\\]+)(?:\s+as\s+\w+)?\s*;', re.MULTILINE)
PHP_GROUP_USE: typing.Final[re.Pattern[str]] = re.compile(r'^\s*use\s+\\?([\w\\]+?)\\?\{([^}]*)\}\s*;', re.MULTILINE)
PHP_TYPE: typing.Final[re.Pattern[str]] = re.compile(r'(?<![:$\w])(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)')

Mapping = dict[str, str]

def php_dotted(name: str) -> str:
    """ App\\Http\\Controllers\\UserController -> App.Http.Controllers.UserController ( as the parsers bind it ) """
    return name.strip('\\').replace('\\', '.')

def php_namespace(content: str) -> typing.Optional[str]:
    """ the dotted namespace a php file declares, if any """
    namespace = PHP_NAMESPACE.search(content)
    return php_dotted(namespace.group(1)) if namespace is not None else None

def php_uses(content: str) -> list[str]:
    """ the dotted names a php file imports : use A\\B\\C [ as D ] ; and use A\\{B, C\\D} ; """
    uses = [php_dotted(m.group(1)) for m in PHP_USE.finditer(content)]
    for m in PHP_GROUP_USE.finditer(content):
        prefix = php_dotted(m.group(1))
        for item in m.group(2).split(','):
            words = item.split()
            if words:
                uses.append(f'{prefix}.{php_dotted(words[0])}')
    return uses

def php_declared(contents: dict[pathlib.Path, str]) -> dict[str, str]:
    """ namespace.Class -> declaring file, main sources win over tests """
    declared: dict[str, str] = {}
    for f in sorted(contents, key=lambda f: ('test' in f.as_posix().lower(), f.as_posix())):
        namespace = php_namespace(contents[f])
        if namespace is not None:
            for name in sorted({t.group(1) for t in PHP_TYPE.finditer(contents[f])}):
                declared.setdefault(f'{namespace}.{name}', f.as_posix())
    return declared

def php_file_mappings(
    f: pathlib.Path,
    content: str,
    declared: dict[str, str],
    by_namespace: dict[str, dict[str, str]]
) -> list[Mapping]:
    """ the 1st party classes one php file sees : its use imports + the classes of its own namespace it names """
    uses = php_uses(content)
    mappings = [
        {'from': used, 'to': declared[used]}
        for used in dict.fromkeys(uses)
        if used in declared and declared[used] != f.as_posix()
    ]
    namespace = php_namespace(content)
    if namespace is not None:
        used_names = {used.rpartition('.')[2] for used in uses}
        words = set(PHP_CLASS_NAME.findall(content)) - {t.group(1) for t in PHP_TYPE.finditer(content)}
        mappings += [
            {'from': f'{namespace}.{name}', 'to': declaring}
            for name, declaring in sorted(by_namespace.get(namespace, {}).items())
            if name in words and name not in used_names
        ]
    return mappings

def resolve_php_namespace_mappings(
    scan_dirname: pathlib.Path,
    files: list[pathlib.Path]
) -> dict[str, list[Mapping]]:
    """
    Resolve 1st party php classes via the namespace declarations ( as java packages ).
    Returns a dict mapping each php file to its use imports that are declared in the repo,
    plus the classes of its own namespace that it names ( php needs no use for those,
    the parsers turn each into an implicit 1st party import ).
    E.g. {"routes/web.php": [{
        "from": "App.Http.Controllers.UserController",
        "to": "app/Http/Controllers/UserController.php"
    }]}
    """
    contents: dict[pathlib.Path, str] = {}
    for f in files:
        if f.suffix != '.php':
            continue
        try:
            contents[f] = PHP_COMMENT.sub(' ', (scan_dirname / f).read_text(encoding='utf-8', errors='replace'))
        except OSError:
            continue

    declared = php_declared(contents)
    by_namespace: dict[str, dict[str, str]] = {}
    for qualified, declaring in declared.items():
        namespace, _, name = qualified.rpartition('.')
        by_namespace.setdefault(namespace, {})[name] = declaring

    result: dict[str, list[Mapping]] = {}
    for f, content in contents.items():
        mappings = php_file_mappings(f, content, declared, by_namespace)
        if mappings:
            result[f.as_posix()] = mappings
    return result
