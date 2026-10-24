"""Perfil de instalación. Los datos de mercados distintos no se mezclan."""
import json
import os
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
PROFILE_PATH=ROOT/'config'/'market.local.json'
DEFAULT={'country':'ES','name':'España','currency':'EUR','language':'es','tld':'es','timezone':'Europe/Madrid','amazon_domain':'amazon.es','stores':[]}
PROFILE={**DEFAULT,**(json.loads(PROFILE_PATH.read_text(encoding='utf-8')) if PROFILE_PATH.exists() else {})}
for key,pattern in [('country',r'[A-Z]{2}'),('currency',r'[A-Z]{3}'),('language',r'[a-z]{2}'),('tld',r'[a-z]{2,10}')]:
    if not re.fullmatch(pattern,str(PROFILE[key])):raise ValueError('Perfil de mercado inválido: '+key)
COUNTRY=PROFILE['country'];CURRENCY=PROFILE['currency'];LANGUAGE=PROFILE['language']
CUSTOM_STORES=PROFILE.get('stores',[])
