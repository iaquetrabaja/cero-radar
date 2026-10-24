"""Consultas rotativas de descubrimiento. Ninguna consulta verifica una oferta."""
from itertools import zip_longest
from cero.market import PROFILE,LANGUAGE

ZERO=['"0,00 €"','"0,00€"','"0.00 €"','"0.00€"','"€0,00"','"€0.00"','"0,00 EUR"','"0.00 EUR"','"0 €"','"0€"']
ACTIONS=['"añadir al carro"','"añadir al carrito"','"añadir a la cesta"','"comprar"','"agregar al carrito"']
CMS=[('WooCommerce','inurl:producto'),('Shopify','inurl:products'),('PrestaShop','inurl:html "añadir al carrito"'),('Magento','inurl:html "añadir al carro"'),('WP EasyCart','inurl:store "añadir al carro"'),('Schema','"priceCurrency" "EUR" "price"')]
EXCLUDE='-inurl:carrito -inurl:cart -inurl:cesta -inurl:checkout -muestra -billete -pdf -descargable'


def restock_queries(domains=()):
    states={'es':['"agotado"','"sin stock"','"sin existencias"','"avísame"'],
            'en':['"sold out"','"out of stock"','"notify me"'],
            'fr':['"épuisé"','"rupture de stock"'],
            'de':['"ausverkauft"','"nicht auf Lager"'],
            'pt':['"esgotado"','"sem stock"'],
            'it':['"esaurito"','"non disponibile"']}.get(LANGUAGE,['"out of stock"'])
    # No buy-button requirement: merchants often remove it for sold-out items.
    queries=[f'{zero} {state} site:.{PROFILE["tld"]} {EXCLUDE}' for zero in ZERO for state in states]
    if LANGUAGE=='es':
        queries += [f'{zero} {state} {kind} {EXCLUDE}' for zero in ZERO[:4] for state in states[:2]
                    for kind in ('bicicleta','"robot aspirador"','portátil','zapatillas')]
    for i,domain in enumerate(dict.fromkeys(domains)):
        queries.append(f'site:{domain} {ZERO[i%len(ZERO)]} {states[i%len(states)]} {EXCLUDE}')
    symbol={'EUR':'€','USD':'$','GBP':'£','MXN':'$'}.get(PROFILE['currency'],PROFILE['currency'])
    return [q.replace('€',symbol).replace('EUR',PROFILE['currency']) for q in dict.fromkeys(queries)]


def promotion_queries():
    terms={'es':['paga solo el envío','paga sólo el envío','gratis pagando envío','paga únicamente el envío'],
           'en':['just pay shipping','free product pay shipping'],
           'fr':['payez uniquement les frais de port'],
           'de':['nur Versandkosten bezahlen'],
           'pt':['pague apenas o envio'],
           'it':['paga solo la spedizione']}.get(LANGUAGE,['just pay shipping'])
    return [f'"{term}" "{PROFILE["name"]}" -muestra -muestras -sample -samples -inurl:cart -pdf' for term in terms]


def generate(domains=()):
    actions={'en':['"add to cart"','"add to basket"','"buy"'],'fr':['"ajouter au panier"','"acheter"'],'de':['"in den Warenkorb"','"kaufen"'],'it':['"aggiungi al carrello"','"comprare"'],'pt':['"adicionar ao carrinho"','"comprar"']}.get(LANGUAGE,ACTIONS)
    general=[f'{price} {action} site:.es {EXCLUDE}' for price in ZERO for action in actions]
    cms=[f'{footprint} {price} site:.es {EXCLUDE}' for _,footprint in CMS for price in ZERO]
    # Muchas tiendas españolas usan .com o .shop. El país se valida en la ficha.
    if LANGUAGE=='es':
        cms += [f'{price} {action} "envío a España" {EXCLUDE}' for price in ZERO for action in actions[:2]]
        cms += [f'{price} "IVA incluido" "en stock" {EXCLUDE}' for price in ZERO]
        cms += [f'inurl:products {price} "EUR" {EXCLUDE}' for price in ZERO]
    shops=[]
    for domain in dict.fromkeys(domains):
        for signal in ZERO+['"-80%"','"-85%"','"-90%"','"-95%"','"-99%"','"80% de descuento"','"90% de descuento"','"99%"']:
            shops.append(f'site:{domain} {signal} comprar {EXCLUDE}')
    discounts=[f'"{sign}{percent}%" {action} site:.es {EXCLUDE}' for percent in [80,81,85,90,91,95,99] for sign in ['','-','−'] for action in ['comprar','"añadir al carrito"']]
    # Intercalar familias: miles de combinaciones por tienda no impiden explorar otros CMS.
    result=[]
    for group in zip_longest(general,cms,shops,discounts):
        result.extend(q for q in group if q)
    buy={'en':'buy','fr':'acheter','de':'kaufen','it':'comprare','pt':'comprar'}.get(LANGUAGE,'comprar')
    symbol={'EUR':'€','USD':'$','GBP':'£','MXN':'$'}.get(PROFILE['currency'],PROFILE['currency'])
    result=[q.replace('site:.es','site:.'+PROFILE['tld']).replace('€',symbol).replace('EUR',PROFILE['currency']).replace('comprar',buy) for q in result]
    return list(dict.fromkeys(result+PROFILE.get('queries',[])))
