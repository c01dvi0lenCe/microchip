"""Recording-only sequential SDK producer, latest preview slot and bounded raw FIFO."""
from collections import deque
from dataclasses import dataclass
from threading import Condition, Event, Thread
import time


@dataclass(frozen=True)
class RawFrame:
    # Owned immutable memory. No ctypes objects from the SDK pool may cross this boundary.
    pixels: bytes
    metadata: dict
    encode_width: int
    encode_height: int


class RecordingPump:
    """One SDK buffer reader; one encoder; no SDK start/stop calls from either.

    The byte and frame caps include the current encoder input. At 5472x3648
    Bayer8, 128 MiB holds at most six owned inputs. The producer and latest-only
    preview can temporarily retain another frame each; preview conversion is
    outside the FIFO. Full FIFO rejects the arriving frame, never evicts an
    accepted one and never blocks the SDK reader on encoder/disk latency.
    """
    def __init__(self, grab, encode, journal, byte_limit, frame_limit):
        self.grab, self.encode, self.journal = grab, encode, journal
        self.byte_limit, self.frame_limit = byte_limit, frame_limit
        self.condition = Condition()
        self.stop = Event()
        self.pending = deque()
        self.nbytes = self.nframes = 0
        self.latest = None
        self.input_closed = False
        self.encoder_error = self.audit_error = self.capture_error = ''
        self.reader = Thread(target=self._capture, name='mvs-record-capture', daemon=True)
        self.writer = Thread(target=self._write, name='mvs-record-encoder', daemon=True)

    def start(self):
        self.writer.start()
        self.reader.start()

    def _capture(self):
        try:
            while not self.stop.is_set():
                try:
                    frame = self.grab(.10, self.journal)
                except TimeoutError:
                    continue
                with self.condition:
                    replaced = self.latest is not None
                    self.latest = frame
                    if self.encoder_error:
                        loss = 'encoder_unavailable'
                    elif (self.nbytes + len(frame.pixels) > self.byte_limit or
                          self.nframes >= self.frame_limit):
                        loss = 'raw_queue_overflow'
                    else:
                        loss = None
                        self.pending.append(frame)
                        self.nbytes += len(frame.pixels)
                        self.nframes += 1
                    self.condition.notify_all()
                if loss:
                    self.journal.record_loss(frame.metadata, loss)
                if replaced:
                    self.journal.record_preview_replacement()
                del frame
        except Exception as exc:
            with self.condition:
                self.capture_error = str(exc) or type(exc).__name__
                self.condition.notify_all()

    def _write(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending or self.input_closed)
                if not self.pending:
                    return
                frame = self.pending.popleft()
            try:
                if self.encoder_error:
                    self.journal.record_loss(frame.metadata, 'encoder_unavailable')
                else:
                    try:
                        self.encode(frame)
                    except Exception as exc:
                        with self.condition:
                            self.encoder_error = str(exc) or type(exc).__name__
                        self.journal.record_loss(frame.metadata, 'encoder_input_failed')
                    else:
                        # A journal failure here is NOT a missing encoder input.
                        self.journal.add_frame(dict(frame.metadata,
                            input_completed_monotonic_ns=time.monotonic_ns()))
            except Exception as exc:
                self.audit_error = self.audit_error or str(exc) or type(exc).__name__
            finally:
                with self.condition:
                    self.nbytes -= len(frame.pixels)
                    self.nframes -= 1
                del frame

    def preview(self, timeout_s):
        with self.condition:
            self.condition.wait_for(
                lambda: self.latest is not None or self.capture_error or self.input_closed,
                timeout=max(0, timeout_s))
            if self.capture_error:
                raise RuntimeError(self.capture_error)
            if self.latest is None:
                raise TimeoutError('MVS recording has not delivered a new preview frame')
            frame, self.latest = self.latest, None
            return frame

    def finish(self):
        # A Get already in flight is resolved before the capture boundary closes.
        self.stop.set()
        if self.reader.ident is not None:
            self.reader.join()
        with self.condition:
            self.latest = None
            self.input_closed = True
            self.condition.notify_all()
        if self.writer.ident is not None:
            self.writer.join()
        return '; '.join(filter(None, (self.capture_error, self.encoder_error, self.audit_error)))
