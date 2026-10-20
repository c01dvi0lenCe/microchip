"""Mode-gated AM adapter; electrical ACK and visual confirmation stay separate."""
from dataclasses import dataclass
import threading
import time
from controllers.electrode_transaction import ElectrodeTransactionClient


class DeadlineTransactionClient(ElectrodeTransactionClient):
    """Reuse protocol semantics while bounding the entire experiment command."""
    def __init__(self,*args,deadline_provider,cancelled,**kwargs):
        super().__init__(*args,**kwargs)
        self.deadline_provider=deadline_provider;self.cancelled=cancelled

    def _wait_for(self,cursor,predicate):
        deadline=min(time.monotonic()+self.ack_timeout_s,self.deadline_provider())
        with self._condition:
            while True:
                if self.cancelled():return None
                remaining=deadline-time.monotonic()
                if remaining<=0:return None
                for index in range(cursor,len(self._messages)):
                    line=self._messages[index]
                    if predicate(line):
                        self._matched_time=self._message_times[index]
                        return line
                self._condition.wait(min(remaining,.05))


class SerialTransport:
    def __init__(self,config):
        import serial
        cfg=config['serial'];self.config=cfg;self.closed=False;self.deadline=None;self.error=''
        self.last_command_sent=False;self.releasing=False
        self.emergency=config.get('_emergency',lambda:False)
        self.port=serial.Serial(cfg['port'],cfg['baudrate'],timeout=.05,write_timeout=cfg['ack_timeout_s'])
        self.client=DeadlineTransactionClient(self._send,ack_timeout_s=cfg['ack_timeout_s'],max_retries=cfg['max_retries'],
            event_observer=config.get('_transaction_observer'),
            deadline_provider=lambda:self.deadline or float('inf'),
            cancelled=lambda:not self.releasing and (self.emergency() or bool(self.error)))
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        # Establish a known released state before submitting any new drive command.
        if not self.release():
            self.close();raise RuntimeError('startup ALL_OFF was not acknowledged')

    def _read(self):
        try:
            while not self.closed:
                raw=self.port.readline()
                if raw:self.client.feed_line(raw.decode('ascii',errors='replace').strip())
        except Exception as exc:self.error=str(exc);self.client.feed_line('ERR:SERIAL_DISCONNECTED')

    def _send(self,line):
        if line!='ALL_OFF' and (self.emergency() or self.error):return False
        if self.deadline is not None and time.monotonic()>self.deadline:return False
        try:
            remaining=self.deadline-time.monotonic() if self.deadline is not None else self.config['ack_timeout_s']
            if remaining<=0:return False
            self.port.write_timeout=min(self.config['ack_timeout_s'],remaining)
            payload=(line+'\n').encode('ascii')
            written=self.port.write(payload)
            self.last_command_sent=self.last_command_sent or written>0
            return written==len(payload)
        except Exception as exc:self.error=str(exc);return False

    def apply(self,changes):
        self.last_command_sent=False;self.releasing=False
        self.deadline=time.monotonic()+self.config['command_timeout_s']
        r=self.client.apply_changes(changes)
        return r.sequence,r.applied,r.error or self.error

    def release(self):
        self.last_command_sent=False;self.releasing=True
        self.deadline=time.monotonic()+self.config['command_timeout_s']
        try:return self.client.all_off()
        finally:self.releasing=False

    def close(self):
        self.closed=True
        if self.port.is_open:self.port.close()


@dataclass(frozen=True)
class CommandResult:
    command_id: int | str = ''
    sent: bool = False
    accepted: bool = True
    error: str = ''
    changes: dict | None = None


class AMActuator:
    def __init__(self,mode,config,transport_factory=SerialTransport):
        if mode not in {'offline','dry_run','experiment'}:raise ValueError('invalid mode')
        if mode=='experiment' and config.get('enable_am_output') is not True:raise ValueError('AM output is not explicitly enabled')
        self.mode=mode;self.active=None;self.counter=0
        self.transport=transport_factory(config) if mode=='experiment' else None

    def execute(self,decision):
        if decision.target is None:return CommandResult()
        target=decision.target
        if type(target) is not int or not 1<=target<=400:raise ValueError('invalid core target')
        changes={target:1}
        if self.active is not None and self.active!=target:changes[self.active]=0
        self.counter+=1;cid=self.counter;accepted=True;error=''
        if self.transport:cid,accepted,error=self.transport.apply(changes)
        if accepted:self.active=target
        sent=bool(getattr(self.transport,'last_command_sent',True)) if self.transport else False
        return CommandResult(cid,sent,accepted,error,changes)

    def close(self):
        if self.transport:
            try:ok=self.transport.release()
            finally:self.transport.close()
            return CommandResult('ALL_OFF',bool(getattr(self.transport,'last_command_sent',True)),bool(ok),'' if ok else 'ALL_OFF acknowledgement failed',{})
        return CommandResult('ALL_OFF',False,True,'',{})
