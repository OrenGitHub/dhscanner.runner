import typing
import sqlalchemy

from sqlalchemy.orm import sessionmaker

# How long a write waits for the sqlite lock before `database is locked`.
# The app runs several uvicorn processes and the cli uploads a batch of
# files at once : every upload commits a row, one writer at a time. The
# default 5 sec ran out under such a batch and the upload answered 500.
SQLITE_BUSY_TIMEOUT_SECONDS: typing.Final[int] = 20

engine = sqlalchemy.create_engine(
    'sqlite:///transient_storage/dhscanner.db',
    connect_args={'check_same_thread': False, 'timeout': SQLITE_BUSY_TIMEOUT_SECONDS}
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
