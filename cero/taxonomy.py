"""Clasificación común de productos; no utiliza la consulta que los encontró."""
import re
import unicodedata


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(text or '').lower()) if not unicodedata.combining(c))


# Las piezas se evalúan antes que el vehículo al que pertenecen.
RULES=[
 ('Equipamiento comercial','Expositores y cartelería','expositor',r'\bexpositor(?:es)?\b'),
 ('Equipamiento comercial','Expositores y cartelería','cartelería',r'\bposters?\b'),
 ('Jardín y agricultura','Riego','riego',r'\b(?:hidrante|riego|irriwise|galcon|nmc-pro|skygreen)\b'),
 ('Jardín y agricultura','Herramientas agrícolas','herramienta agrícola',r'atadora.*(?:vid|frutal)'),
 ('Deporte','Ciclismo','calas',r'\bcalas?\b'),
 ('Deporte','Ciclismo','sillín',r'\bsillin(?:es)?\b|\bbicycle saddle\b'),
 ('Deporte','Ciclismo','frenos de bicicleta',r'pastillas de freno|zapatas.*(?:road|llanta|carbono)|carbonstop|disco de freno.*(?:bici|mtb)'),
 ('Deporte','Ciclismo','ruedas y neumáticos',r'cushcore|antipinchazos|camara de aire|cubierta.*(?:mtb|bici|tubeless)|\b(?:tubeless|tannus|cassette|piñon|pinon|bielas?|pedales?|manillar|tija|potencia de manillar)\b'),
 ('Deporte','Ciclismo','ropa de ciclismo',r'\b(?:maillot|culotte|ciclismo)\b'),
 ('Deporte','Ciclismo','accesorios de bicicleta',r'(?:limpiador|lubricante|desengrasante|bomba|candado|portabidon|casco|cadena).*\b(?:bici|bicicleta|ciclismo|mtb)\b|\bweldtite\b'),
 ('Deporte','Ciclismo','bicicleta',r'\b(?:bicicleta|bicicletas|e-bike|ebike|bici)\b'),
 ('Deporte','Movilidad','patinete',r'\b(?:patinete|scooter)\b'),
 ('Deporte','Ropa deportiva','ropa deportiva',r'\b(?:mallas?|leggings?|running|fitness|training|yoga|chandal|camiseta tecnica|pantalon tecnico)\b'),
 ('Deporte','Calzado deportivo','zapatillas deportivas',r'\bzapatilla|\bbotas de futbol\b'),
 ('Deporte','Material deportivo','material deportivo',r'\b(?:raqueta|pala de padel|balon|mancuerna|natacion|gafas de buceo|aletas|esqui|senderismo)\b'),
 ('Tecnología','Audio','auriculares',r'\b(?:auriculares?|headset|earbuds|true wireless)\b'),
 ('Tecnología','Audio','altavoces',r'\b(?:altavoz|altavoces|barra de sonido)\b'),
 ('Tecnología','Imagen y seguridad','cámara',r'\b(?:camara|camera|webcam|videovigilancia)\b'),
 ('Tecnología','Imagen y seguridad','detector',r'detector de (?:metales|cartas|explosivos)|\b(?:garrett|mailex|pulsedive)\b|rayos[- ]x'),
 ('Hogar y cocina','Limpieza','robot aspirador',r'robot aspirador|friegasuelos|\b(?:conga|roomba|roborock)\b'),
 ('Tecnología','Informática','informática',r'\b(?:portatil|laptop|monitor|ssd|teclado|raton|pendrive|memoria usb|procesador|tarjeta grafica)\b'),
 ('Tecnología','Telefonía','móvil',r'\b(?:iphone|smartphone|movil|galaxy|pixel)\b'),
 ('Tecnología','Televisión','televisor',r'\b(?:televisor|smart tv|oled|qled)\b'),
 ('Hogar y cocina','Electrodomésticos','electrodoméstico',r'\b(?:cafetera|freidora|airfryer|nevera|frigorifico|lavadora|horno|microondas|batidora|aspirador)\b'),
 ('Belleza y salud','Cuidado personal','secador',r'\b(?:secador|plancha de pelo|cepillo electrico)\b'),
 ('Belleza y salud','Cosmética','cosmética',r'\b(?:perfume|crema|champu|locion|lotion|serum|maquillaje|cosmetica)\b'),
 ('Joyería','Gemas y joyas','gema',r'\b(?:turmalina|rubelita|diamante|zafiro|esmeralda|rubi|gema)\b'),
 ('Joyería','Gemas y joyas','joyería',r'\b(?:pendientes|anillo|pulsera|collar de oro|collar de plata)\b'),
 ('Alimentación','Alimentos y bebidas','alimentación',r'\b(?:bombon(?:es)?|queso|aceite|vino|chocolate|alimento|galleta|caramelo|fruta|frutas|manzana|platano|naranja)\b'),
 ('Hogar y cocina','Muebles y decoración','hogar',r'\b(?:sofa|colchon|lampara|mesa|silla|sabanas|toalla|vajilla|sarten|cacerola)\b'),
 ('Moda','Ropa','ropa',r'\b(?:camiseta|vestido|chaqueta|pantalon|sudadera|abrigo|cazadora|gabardina|botas|falda|polo)\b'),
 ('Viaje','Equipaje','maleta',r'\b(?:maleta|equipaje|trolley)\b'),
 ('Accesorios','Bolsas y complementos','bolsa',r'\b(?:bolsa|bolso|mochila)\b'),
 ('Mascotas','Accesorios para mascotas','mascotas',r'\b(?:perro|gato|mascota|pienso|arenero)\b'),
 ('Juguetes','Juegos y juguetes','juguete',r'\b(?:juguete|muneca|peluche|lego|puzzle|juego de mesa)\b'),
 ('Bricolaje','Herramientas','herramienta',r'\b(?:taladro|atornillador|destornillador|amoladora|lijadora)\b'),
]
CATEGORY_NAMES={row[0] for row in RULES}|{'Otros'}


def classify(title,context=''):
    text=normalize(title)
    for category,subcategory,product_type,pattern in RULES:
        if re.search(pattern,text):return {'category':category,'subcategory':subcategory,'product_type':product_type}
    # El breadcrumb sólo resuelve títulos que no contienen un tipo reconocible.
    context=normalize(context)
    for category,subcategory,product_type,pattern in RULES:
        if re.search(pattern,context):return {'category':category,'subcategory':subcategory,'product_type':product_type}
    return {'category':'Otros','subcategory':'Sin clasificar','product_type':'otros'}
