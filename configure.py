"""Configuración inicial sin introducir claves en el código ni en Git."""
import argparse
import json
from pathlib import Path

PROFILES={
 'ES':{'name':'España','currency':'EUR','language':'es','tld':'es','timezone':'Europe/Madrid','amazon_domain':'amazon.es'},
 'PT':{'name':'Portugal','currency':'EUR','language':'pt','tld':'pt','timezone':'Europe/Lisbon','amazon_domain':''},
 'FR':{'name':'France','currency':'EUR','language':'fr','tld':'fr','timezone':'Europe/Paris','amazon_domain':'amazon.fr'},
 'DE':{'name':'Deutschland','currency':'EUR','language':'de','tld':'de','timezone':'Europe/Berlin','amazon_domain':'amazon.de'},
 'IT':{'name':'Italia','currency':'EUR','language':'it','tld':'it','timezone':'Europe/Rome','amazon_domain':'amazon.it'},
 'GB':{'name':'United Kingdom','currency':'GBP','language':'en','tld':'uk','timezone':'Europe/London','amazon_domain':'amazon.co.uk'},
 'US':{'name':'United States','currency':'USD','language':'en','tld':'us','timezone':'America/New_York','amazon_domain':'amazon.com'},
 'MX':{'name':'México','currency':'MXN','language':'es','tld':'mx','timezone':'America/Mexico_City','amazon_domain':'amazon.com.mx'},
}


def main():
    parser=argparse.ArgumentParser(description='Personaliza el país y las tiendas de CERO antes de arrancar.')
    parser.add_argument('--country',choices=PROFILES,help='País de esta instalación')
    parser.add_argument('--store',action='append',default=[],metavar='NOMBRE|URL',help='Se puede repetir para añadir tiendas')
    args=parser.parse_args();country=args.country or input('País ('+', '.join(PROFILES)+') [ES]: ').strip().upper() or 'ES'
    if country not in PROFILES:parser.error('País no incluido. Añade un perfil avanzado en config/market.local.json.')
    root=Path(__file__).resolve().parent;path=root/'config'/'market.local.json'
    previous=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    # No cambiar de mercado sobre una base que contiene los datos de otro país.
    if (root/'data'/'cero.db').exists():
        import sqlite3
        with sqlite3.connect(root/'data'/'cero.db') as c:
            installed=c.execute("SELECT value FROM settings WHERE key='installation_country'").fetchone()
        if installed and json.loads(installed[0])!=country:
            parser.error('Usa una nueva carpeta de instalación para otro país; así conservarás los datos actuales.')
    stores=previous.get('stores',[]) if previous.get('country')==country else []
    from urllib.parse import urlparse
    for entry in args.store:
        try:name,url=entry.split('|',1)
        except ValueError:parser.error('Usa --store "Nombre|https://tienda.example/"')
        if urlparse(url).scheme not in ('http','https') or not urlparse(url).hostname:parser.error('URL de tienda inválida')
        if not any(s['url']==url for s in stores):stores.append({'name':name,'url':url})
    path.parent.mkdir(exist_ok=True);path.write_text(json.dumps({'country':country,**PROFILES[country],'stores':stores},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('País configurado: '+PROFILES[country]['name']+'. Tiendas personales: '+str(len(stores))+'.')
    print('España incluye el catálogo inicial. Otros países empiezan con las tiendas que añadas; sus resultados y adaptadores deben validarse localmente.')


if __name__=='__main__':main()
