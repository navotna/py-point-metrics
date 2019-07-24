import atexit
import datetime
import logging
import uuid
import weakref
from functools import wraps
from typing import List, Optional, Callable

__all__ = [
    "get_metr",
    "add_metr",
    "LoggingHandler",
    "RDSHandler",
    "Handler",
    "NullHandler",
    "ray_id",
    "propagate_exceptions",
]

try:
    import threading
except ImportError:
    threading = None

_lock = threading.RLock() if threading else None

ray_id = None
propagate_exceptions = False

logger = logging.getLogger("metrics")


def _acquire_lock():
    """
    Acquire the module-level lock
    """
    if _lock:
        _lock.acquire()


def _release_lock():
    """
    Release the module-level lock
    """
    if _lock:
        _lock.release()


def _make_ray_id():
    global ray_id
    if ray_id is None:
        ray_id = str(uuid.uuid4())
    return ray_id


_ray_id_factory = _make_ray_id


class Record:
    def __init__(self, tag: str, value: int, created: Optional[datetime.datetime] = None):
        self.created = created or datetime.datetime.utcnow()
        self.ray_id = _ray_id_factory()
        self.tag = tag
        self.value = value
        if threading:
            self.thread = threading.get_ident()
            self.thread_name = threading.current_thread().name
        else:
            self.thread = None
            self.thread_name = None

    def __str__(self) -> str:
        v = (
            f"[ray:{self.ray_id}]"
            f"[created:{str(self.created)}]"
            f"[tag:{self.tag}]"
            f"[value:{self.value}]"
        )
        if threading:
            v = f"[thread:{self.thread}][thread_name:{self.thread_name}]" + v
        return v

    __repr__ = __str__


_record_factory = Record


class Formatter:
    pass


class SQLRecordFormatter(Formatter):
    """
    Used to convert a Record to SQL query values list.
    """

    def format(self, record: Record):
        return f"'{str(record.created)}', '{record.tag}', {int(record.value)}, '{record.ray_id}'"


class TextFormatter(Formatter):
    """
    Used to convert a Record to text.
    """

    def format(self, record: Record) -> str:
        return str(record)


_handler_list = []  # added to allow handlers to be removed in reverse of order initialized


def _remove_handler_ref(wr):
    """
    Remove a handler reference from the internal cleanup list.
    """
    acquire, release, handlers = _acquire_lock, _release_lock, _handler_list
    if acquire and release and handlers:
        acquire()
        try:
            if wr in handlers:
                handlers.remove(wr)
        finally:
            release()


def _add_handler_ref(handler):
    """
    Add a handler to the internal cleanup list using a weak reference.
    """
    _acquire_lock()
    try:
        _handler_list.append(weakref.ref(handler, _remove_handler_ref))
    finally:
        _release_lock()


class Handler:
    def __init__(self):
        self.formatter = None
        _add_handler_ref(self)
        self.lock = None
        self.create_lock()

    def emit(self, record: Record):
        raise NotImplementedError("emit must be implemented by Handler subclasses")

    def acquire_lock(self):
        if self.lock:
            self.lock.acquire()

    def release_lock(self):
        if self.lock:
            self.lock.release()

    def format(self, record):
        return self.formatter.format(record)

    def handle(self, record: Record) -> Record:
        self.acquire_lock()
        try:
            self.emit(record)
        finally:
            self.release_lock()
        return record

    def flush(self):
        pass

    def close(self):
        pass

    def handle_error(self, record: Record, error: Exception):
        """Handle errors which occur during an emit() call."""
        if propagate_exceptions:
            raise error
        else:
            logger.exception(
                f"Error in handler: {self.__class__.__name__}, for record: {record}", exc_info=True
            )

    def create_lock(self):
        if threading:
            self.lock = threading.RLock()


class NullHandler(Handler):
    def emit(self, record: Record):
        pass


class RDSHandler(Handler):
    table = "some_table"

    def __init__(self, connection, table: Optional[str] = None):
        super().__init__()
        self.formatter = SQLRecordFormatter()
        self.connection = connection
        self.table = table or self.__class__.table

    def emit(self, record: Record):
        try:
            values = self.format(record)
            with self.connection.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {self.table} (timestamp, tag, value, ray_id) VALUES ({values});"
                )
            self.flush()
        except Exception as e:
            self.handle_error(record, e)

    def flush(self):
        self.connection.commit()

    def close(self):
        _acquire_lock()
        try:
            self.connection.close()
        finally:
            _release_lock()

    def handle_error(self, record: Record, error: Exception):
        self.connection.rollback()
        super().handle_error(record, error)


class LoggingHandler(Handler):
    def __init__(self, level, name):
        super().__init__()
        self.formatter = TextFormatter()
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.level = level

    def emit(self, record: Record):
        self.logger.log(self.level, self.format(record))


class Recorder:
    def __init__(self, metr: Optional["Metr"] = None):
        self.metr = metr

    def __get__(self, instance: "Metr", owner):
        return self.__class__(instance)

    def finalize(self, value):
        self.metr.handle_value(value)


class IntRecorder(Recorder):
    """
    record single int value
    """

    def __call__(self, value: int):
        self.finalize(value)


class CounterRecorder(Recorder):
    """
    accumulate value
    """

    def __call__(self) -> "CounterRecorder":
        self._value = 0
        return self

    def __enter__(self) -> "CounterRecorder":
        return self

    def add(self, value):
        self._value += value

    def close(self):
        self.finalize(self._value)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class ExceptionRecorder(Recorder):
    def decorator(self, function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except self._exceptions as e:
                self.finalize(1)
                raise e

        return wrapper

    def __call__(self, *exceptions: Exception):
        self._exceptions = exceptions
        return self.decorator


class Metr:
    rec = IntRecorder()
    rec_counter = CounterRecorder()
    rec_exception = ExceptionRecorder()

    def __init__(self, tag: str, handlers: Optional[List[Handler]] = None):
        self.handlers: List[Handler] = handlers or []
        self.tag = tag

    @property
    def _parent(self) -> Optional["Metr"]:
        tag_crumbs = self.tag.split(".")
        parents_count = len(tag_crumbs) - 1
        if parents_count == 0:
            # if it is root tag
            return None
        for i in range(parents_count, 0, -1):
            parent_tag = ".".join(tag_crumbs[:i])
            parent_metr = _metrs.get(parent_tag)
            if parent_metr is not None:
                return parent_metr
        else:
            return None

    def call_handlers(self, record: Record):
        for hdlr in self.handlers:
            try:
                hdlr.handle(record)
            except Exception as e:
                if propagate_exceptions:
                    raise e
        parent = self._parent
        if parent is not None:
            parent.call_handlers(record)

    def handle_value(self, value: int):
        record = self.create_record(value)
        self.call_handlers(record)

    def create_record(
        self, value, record_factory: Optional[Callable[[str, int], Record]] = None
    ) -> Record:
        return (record_factory or _record_factory)(self.tag, value)

    def add_handler(self, hdlr):
        _acquire_lock()
        try:
            if not (hdlr in self.handlers):
                self.handlers.append(hdlr)
        finally:
            _release_lock()

    def get_metr(self, tag: str) -> "Metr":
        return get_metr(f"{self.tag}.{tag}")


@atexit.register
def shutdown_handlers():
    for wr in reversed(_handler_list[:]):
        try:
            h: Handler = wr()
            if h:
                try:
                    h.acquire_lock()
                    h.flush()
                    h.close()
                except (OSError, ValueError):
                    # Ignore errors which might be caused
                    # because handlers have been closed but
                    # references to them are still around at
                    # application exit.
                    pass
                finally:
                    h.release_lock()
        except:  # ignore everything, as we're shutting down
            if propagate_exceptions:
                raise


_metrs = {}  # map of metrs
_metr_factory: Callable[[str, Optional[List[Handler]]], Metr] = Metr


def add_metr(metr: Metr):
    _metrs[metr.tag] = metr


def get_metr(tag: str) -> Metr:
    """
    Get or create metr
    :param tag:
    :return:

    """
    return _metrs.setdefault(tag, _metr_factory(tag))
