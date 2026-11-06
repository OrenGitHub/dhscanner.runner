import http
import time
import typing
import aiohttp
import asyncio
import aiofiles
import dataclasses

from datetime import timedelta

from common.language import Language
from coordinator.interface import Status
from storage.models import FactsMetadata
from logger.models import Context, LogMessage
from workers.interface import AbstractWorker

TO_QUERY_ENGINE_URL_UPLOAD_ONLY = 'http://queryengine:3000/uploadkb'

# queryengine answers once the kb is written and sorted : minutes for a large
# repo ( Discourse ), so no total timeout, only connect / read bounds.
UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=3600)

# facts files deleted concurrently after the upload ( ~50k for Discourse,
# one by one took ~4 minutes )
DELETE_CONCURRENCY = 64

@dataclasses.dataclass(frozen=True)
class Queryengine(AbstractWorker):

    @typing.override
    async def run(self, job_id: str) -> None:
        files = self.the_storage_guy.load_facts_metadata_from_db(job_id)
        try:
            await self.upload_kb(job_id, files)
        finally:
            await self.delete_facts_files(files)

    async def delete_facts_files(self, files: list[FactsMetadata]) -> None:
        semaphore = asyncio.Semaphore(DELETE_CONCURRENCY)

        async def delete(f: FactsMetadata) -> None:
            async with semaphore:
                await self.the_storage_guy.delete_knowledge_base_facts(f)

        await asyncio.gather(*(delete(f) for f in files))

    # The body is the json array of every fact of the job, streamed from the
    # facts files ( one json array per callable ) : one file in memory at a
    # time. Building the whole array first held the kb in memory ( 4.4 GB for
    # Discourse's 1.6M facts ), and queryengine parses it as a stream too.
    @staticmethod
    async def facts_json_array(files: list[FactsMetadata]) -> typing.AsyncIterator[bytes]:
        yield b'['
        first = True
        for f in files:
            async with aiofiles.open(f.facts_unique_id, 'rb') as fl:
                content = (await fl.read()).strip()
            elements = content[1:-1].strip() if content.startswith(b'[') and content.endswith(b']') else b''
            if elements:
                if not first:
                    yield b','
                yield elements
                first = False
        yield b']'

    # The kb is the only output : the agent loop queries it through
    # queryengine's /api ( kbapi ), there are no built-in queries.
    async def upload_kb(self, job_id: str, files: list[FactsMetadata]) -> None:
        emessage = 'no exception'
        start = time.monotonic()

        async with aiohttp.ClientSession(timeout=UPLOAD_TIMEOUT) as session:
            try:
                facts = self.facts_json_array(files)
                async with session.post(
                    TO_QUERY_ENGINE_URL_UPLOAD_ONLY, data=facts, headers={'Content-Type': 'application/json'}
                ) as response:
                    if response.status == http.HTTPStatus.OK:
                        result_json: dict[str, str] = await response.json()
                        if kb_location := result_json.get('kb_location', None):
                            self.the_coordinator.set_kb_location(job_id, kb_location)
                            end = time.monotonic()
                            delta = end - start
                            await self.the_logger_dude.info(
                                LogMessage(
                                    file_unique_id=f'queries_{job_id}',
                                    job_id=job_id,
                                    context=Context.KBGEN_UPLOADED_FOR_AGENT,
                                    original_filename='*',
                                    language=Language.ALL,
                                    duration=timedelta(seconds=delta)
                                )
                            )
                            return

                        # probably unreachable code since an ok response
                        # means everything went well on the server side
                        emessage = 'invalid json response without kb location'
                    else:
                        # Non-200 (413 Payload Too Large, 500, ...) used to
                        # fall through with emessage='no exception', which
                        # made the KBGEN_UPLOAD_FOR_AGENT_FAILED row useless
                        # for diagnosis. Capture status + a short body slice
                        # so the log row actually explains why the kb never
                        # made it. Body is truncated because /uploadkb can
                        # echo back big error pages on 413.
                        try:
                            body = await response.text()
                        except (aiohttp.ClientError, UnicodeDecodeError) as _read_err:
                            body = f'<body unreadable: {_read_err}>'
                        emessage = f'HTTP {response.status} from /uploadkb: {body[:500]}'

            except aiohttp.ClientError as e:
                emessage = f'aiohttp.ClientError: {e}'
            except TimeoutError as e:
                emessage = f'TimeoutError: {e}'
            # Anything else ( OSError, MemoryError, ... ) still propagates up on purpose:
            # those are the "worker is genuinely broken" cases and we want
            # them to surface as a container crash rather than be logged as
            # a normal per-job failure.

            end = time.monotonic()
            delta = end - start
            await self.the_logger_dude.info(
                LogMessage(
                    file_unique_id=f'queries_{job_id}',
                    job_id=job_id,
                    context=Context.KBGEN_UPLOAD_FOR_AGENT_FAILED,
                    original_filename='*',
                    language=Language.ALL,
                    duration=timedelta(seconds=delta),
                    more_details=f'exception(s): {emessage}'
                )
            )

    @typing.override
    async def mark_jobs_finished(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self.the_coordinator.set_status(
                job_id,
                Status.Finished
            )
