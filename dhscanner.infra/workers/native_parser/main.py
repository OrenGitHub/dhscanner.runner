import ast
import re
import http
import json
import time
import typing
import asyncio
import aiohttp
import dataclasses

from datetime import timedelta

from common.language import Language
from coordinator.interface import Status
from storage.models import FileMetadata
from logger.models import Context, LogMessage
from workers.interface import AbstractWorker

# The default aiohttp timeout ( 300s total ) also counts the wait for a
# pooled connection, and run() posts every file of the job at once : on a big
# repo ( Discourse, runner #138 ) queued requests timed out before they were
# ever sent. So : no total budget, but a bound on a single front answering.
FRONT_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=300)

# each in flight file holds its source and its native ast in memory ; the
# same bound as codegen ( an unbounded gather over 19k Discourse files )
MAX_NUM_CONCURRENT_FILES = 8

AST_BUILDER_URL = {
    Language.JS: 'http://frontjs:3000/to/esprima/js/ast',
    Language.TS: 'http://frontts:3000/to/native/ts/ast',
    Language.TSX: 'http://frontts:3000/to/native/ts/ast',
    Language.PHP: 'http://frontphp:5000/to/php/ast',
    Language.PY: 'http://frontpy:5000/to/native/py/ast',
    Language.RB: 'http://frontrb:3000/to/native/cruby/ast',
    Language.CS: 'http://frontcs:8080/to/native/cs/ast',
    Language.GO: 'http://frontgo:8080/to/native/go/ast',
    Language.JAVA: 'http://frontjava:5000/to/native/java/ast',
}

# the global names a ruby file defines ( runner #146 )
RUBY_GLOBALS_URL = 'http://frontrb:3000/to/native/cruby/globals'

def _zeitwerk_basename(name: str) -> str:
    '''`MiniSqlMultisiteConnection` -> `mini_sql_multisite_connection.rb`'''
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', '_', name).lower() + '.rb'


def _defining_file(name: str, files: set[str]) -> typing.Optional[str]:
    '''
    The file a global name binds to : its only defining file, else the one
    file zeitwerk would load it from ( `class ::Post` reopened in a plugin
    vs `app/models/post.rb` ), else none.
    '''
    if len(files) == 1:
        return next(iter(files))
    basename = _zeitwerk_basename(name.lstrip('$'))
    candidates = [f for f in files if f.rsplit('/', 1)[-1] == basename]
    return candidates[0] if len(candidates) == 1 else None


@dataclasses.dataclass(frozen=True)
class RubyGlobals:
    '''
    What the ruby front reports of a file : the global names it `defines`,
    each with the location of its top level class ( else None ), the
    `constants` it defines at any depth and the constant names it `uses`.
    '''
    defines: list[tuple[str, typing.Any]] = dataclasses.field(default_factory=list)
    constants: list[str] = dataclasses.field(default_factory=list)
    uses: list[str] = dataclasses.field(default_factory=list)

    @staticmethod
    def of(reported: typing.Any) -> 'RubyGlobals':
        '''the front's json, anything malformed dropped'''
        if not isinstance(reported, dict):
            return RubyGlobals()

        def names(key: str) -> list[str]:
            value = reported.get(key)
            return [n for n in value if isinstance(n, str)] if isinstance(value, list) else []

        defines = reported.get('defines')
        return RubyGlobals(
            defines=[
                (d[0], d[1]) for d in defines
                if isinstance(d, list) and len(d) == 2 and isinstance(d[0], str)
            ] if isinstance(defines, list) else [],
            constants=names('constants'),
            uses=names('uses')
        )


@dataclasses.dataclass(frozen=True)
class NativeParser(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        files = self.the_storage_guy.load_files_metadata_from_db(job_id)
        limit = asyncio.Semaphore(MAX_NUM_CONCURRENT_FILES)
        async with aiohttp.ClientSession(timeout=FRONT_TIMEOUT) as session:
            # extra form fields per language, sent with each of its files
            fields = {
                Language.PY: await self._python_fields(files),
                Language.RB: await self._ruby_fields(session, files, limit)
            }
            tasks = [self.run_single_file_bounded(session, f, fields.get(f.language, {}), limit) for f in files]
            await asyncio.gather(*tasks)

    async def run_single_file_bounded(
        self,
        session: aiohttp.ClientSession,
        f: FileMetadata,
        fields: dict[str, str],
        limit: asyncio.Semaphore
    ) -> None:
        async with limit:
            await self.run_single_file(session, f, fields)

    async def _python_fields(self, files: list[FileMetadata]) -> dict[str, str]:
        '''
        The python front rewrites dotted 1st party accesses
        ( `weblate.accounts.views.hosting` ) into `from` imports of the exact
        file, so it needs the scanned `.py` files, and the top level class /
        function names per file : a dotted access on a class
        ( `StatsView.as_view()` ) goes through a local subclass, so it
        resolves as a method of a class, and a function passed as an argument
        ( `path("hosting/", views.hosting)` ) is called ( runner #131 ).
        '''
        python_files = [f for f in files if f.language == Language.PY]
        classes: dict[str, list[str]] = {}
        functions: dict[str, list[str]] = {}
        for f in python_files:
            if code := await self.the_storage_guy.load_file(f):
                try:
                    tree = ast.parse(code)
                except (SyntaxError, ValueError):
                    continue
                classes[f.original_filename] = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
                functions[f.original_filename] = [
                    n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
        return {
            'python_files': json.dumps([f.original_filename for f in python_files]),
            'python_classes': json.dumps(classes),
            'python_functions': json.dumps(functions)
        }

    async def _ruby_fields(
        self,
        session: aiohttp.ClientSession,
        files: list[FileMetadata],
        limit: asyncio.Semaphore
    ) -> dict[str, str]:
        '''
        Ruby has no imports : `DB.exec(sql)` reaches
        `::DB = MiniSqlMultisiteConnection.instance` in
        `config/initializers/000-mini_sql.rb` with nothing in between. So the
        ruby front first reports the global names each file defines
        ( `::X = e`, top level `X = e`, `$x = e`, top level `class X` /
        `module X` ), and then binds each name, in every file that uses it,
        to its file ( runner #146 ). See `_defining_file` for a name that
        several files define. A constant some file uses and no file defines,
        at any depth, is `external` ( `MiniSql`, a gem ).
        '''
        ruby_files = [f for f in files if f.language == Language.RB]
        # name -> { file -> the location of its class there ( or None ) }
        defined_in: dict[str, dict[str, typing.Any]] = {}
        constants: set[str] = set()
        uses: set[str] = set()

        async def collect(f: FileMetadata) -> None:
            async with limit:
                found = await self._ruby_globals_of(session, f)
            for name, location in found.defines:
                defined_in.setdefault(name, {})[f.original_filename] = location
            constants.update(found.constants)
            uses.update(found.uses)

        await asyncio.gather(*[collect(f) for f in ruby_files])
        globals_ = {
            name: [file, fs[file]] for name, fs in sorted(defined_in.items())
            if (file := _defining_file(name, set(fs))) is not None
        }
        external = sorted(uses - constants - set(defined_in))
        fields = {}
        if globals_:
            fields['ruby_globals'] = json.dumps(globals_)
        if external:
            fields['ruby_external'] = json.dumps(external)
        return fields

    async def _ruby_globals_of(self, session: aiohttp.ClientSession, f: FileMetadata) -> RubyGlobals:
        '''what the ruby front reports of `f`, nothing when it fails'''
        if (code := await self.read_source_file(f)) is None:
            return RubyGlobals()
        form = aiohttp.FormData()
        form.add_field('source', code['source'][1], filename=code['source'][0], content_type='application/octet-stream')
        try:
            async with session.post(RUBY_GLOBALS_URL, data=form) as response:
                if response.status != http.HTTPStatus.OK:
                    return RubyGlobals()
                reported = json.loads(await response.text(errors='replace'))
        except (aiohttp.ClientError, UnicodeDecodeError, TimeoutError, ValueError):
            return RubyGlobals()
        return RubyGlobals.of(reported)

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.WaitingForDhscannerParsing
            )

    async def run_single_file(
        self,
        session: aiohttp.ClientSession,
        f: FileMetadata,
        fields: dict[str, str]
    ) -> None:

        if code := await self.read_source_file(f):
            if content := await self.parse(session, code, f, fields):
                await self.the_storage_guy.save_native_ast(content, f)

            # either way - delete the source file ...
            await self.the_storage_guy.delete_file(f)

    async def parse(
        self,
        session: aiohttp.ClientSession,
        code: dict[str, typing.Tuple[str, bytes]],
        f: FileMetadata,
        fields: dict[str, str]
    ) -> typing.Optional[str]:
        start = time.monotonic()

        # YAML / YML have no separate native-parser front. HsYAML inside the
        # dhscanner parsers service does the real structural parsing later,
        # so the "native ast" here is just the raw source text. Skipping the
        # HTTP roundtrip keeps the surrounding save_native_ast / delete_file
        # flow uniform without inventing a placeholder front-end.
        if f.language in (Language.YAML, Language.YML):
            return code['source'][1].decode('utf-8', errors='replace')

        url = AST_BUILDER_URL[f.language]
        try:
            form = aiohttp.FormData()
            form.add_field(
                'source',
                code['source'][1],
                filename=code['source'][0],
                content_type='application/octet-stream'
            )
            for field in fields.items():
                form.add_field(*field)
            async with session.post(url, data=form) as response:
                if response.status == http.HTTPStatus.OK:
                    # `errors='replace'` so a single non-utf-8 byte from a
                    # native front-end can't take the whole worker down via
                    # an unhandled UnicodeDecodeError (a single bad file will
                    # at worst fail dhscanner-parsing later in a structured
                    # way, instead of crashing the asyncio.gather and exiting
                    # the entrypoint).
                    native_ast = await response.text(errors='replace')
                    context = Context.NATIVE_PARSING_SUCCEEDED
                    received_native_ast_is_empty = (len(native_ast) == 0)
                    if received_native_ast_is_empty:
                        context = Context.NATIVE_PARSING_EMPTY_AST
                    end = time.monotonic()
                    delta = end - start
                    await self.the_logger_dude.info(
                        LogMessage(
                            file_unique_id=f.file_unique_id,
                            job_id=f.job_id,
                            context=context,
                            original_filename=f.original_filename,
                            language=f.language,
                            duration=timedelta(seconds=delta)
                        )
                    )

                    if received_native_ast_is_empty:
                        return None

                    return native_ast

        # `UnicodeDecodeError` is a defensive catch even though `text(errors=
        # 'replace')` above shouldn't raise it -- if a future aiohttp change
        # or a different read path re-introduces the issue, we still log the
        # file as NATIVE_PARSING_FAILED instead of toppling the worker.
        # `TimeoutError` ( a slow front ) is not an `aiohttp.ClientError` :
        # uncaught, it ended the asyncio.gather and the worker with it, and
        # the job hung at WaitingForNativeParsing.
        except (aiohttp.ClientError, UnicodeDecodeError, TimeoutError):
            pass

        end = time.monotonic()
        delta = end - start
        await self.the_logger_dude.info(
            LogMessage(
                file_unique_id=f.file_unique_id,
                job_id=f.job_id,
                context=Context.NATIVE_PARSING_FAILED,
                original_filename=f.original_filename,
                language=f.language,
                duration=timedelta(seconds=delta)
            )
        )
        return None

    async def read_source_file(
        self, f: FileMetadata
    ) -> typing.Optional[dict[str, typing.Tuple[str, bytes]]]:
        if code := await self.the_storage_guy.load_file(f):
            return { 'source': (f.original_filename, code) }

        return None
