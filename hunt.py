"""Cliente del motor del panel; no abre un segundo rastreador."""
import argparse
import json
import time
from urllib.request import Request,urlopen
from urllib.error import URLError

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',choices=['normal','deep','watch'],default='normal');p.add_argument('--wait',action='store_true');args=p.parse_args()
    root='http://127.0.0.1:8765'
    try:
        body=json.dumps({'profile':args.profile}).encode()
        with urlopen(Request(root+'/api/scan',data=body,headers={'Content-Type':'application/json'}),timeout=15) as r:print(json.load(r))
        previous=''
        while args.wait:
            with urlopen(root+'/api/status',timeout=15) as r:state=json.load(r)
            if state['message']!=previous:print(state['message'],flush=True);previous=state['message']
            if not state['running']:break
            time.sleep(3)
    except URLError:raise SystemExit('Abre primero el servicio con python run.py')

if __name__=='__main__':main()
