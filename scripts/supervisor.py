"""Mantiene el servicio local disponible y lo reinicia si el proceso termina."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent.parent
LOGS=ROOT/'data'/'logs';LOGS.mkdir(parents=True,exist_ok=True)


def main():
    lock=(LOGS/'supervisor.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:return
    while True:
        try:
            with urlopen('http://127.0.0.1:8765/api/status',timeout=8) as response:
                if 'phase' in json.load(response):time.sleep(15);continue
        except Exception:pass
        # Un puerto ocupado por otra aplicación no se libera ni se termina.
        import socket
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',8765))==0:time.sleep(15);continue
        log_path=LOGS/'server.log'
        if log_path.exists() and log_path.stat().st_size>20*1024*1024:log_path.replace(LOGS/'server.previous.log')
        with log_path.open('ab') as output:
            process=subprocess.Popen([sys.executable,'-m','uvicorn','cero.api:app','--host','127.0.0.1','--port','8765','--no-access-log'],cwd=ROOT,stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            process.wait()
        time.sleep(10)


if __name__=='__main__':main()
