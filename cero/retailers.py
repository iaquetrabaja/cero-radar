"""Tiendas grandes que venden en España, con la URL de búsqueda de cada una."""

RAW = """
Decathlon | bicicleta eléctrica | https://www.decathlon.es/es/search?Ntt={q}
Deporvillage | bicicleta eléctrica;maillot | https://www.deporvillage.com/catalogsearch/result/?q={q}
PcComponentes | robot aspirador;bicicleta eléctrica | https://www.pccomponentes.com/buscar/?query={q}
MediaMarkt | robot aspirador;televisor | https://www.mediamarkt.es/es/search.html?query={q}
El Corte Inglés | bicicleta eléctrica;robot aspirador | https://www.elcorteingles.es/search/?s={q}
Hipercor | robot aspirador | https://www.hipercor.es/search/?s={q}
Fnac | robot aspirador;auriculares | https://www.fnac.es/SearchResult/ResultList.aspx?Search={q}&sft=1&sa=0
Worten | robot aspirador;televisor | https://www.worten.es/search?query={q}
Carrefour | robot aspirador;bicicleta eléctrica | https://www.carrefour.es/search?q={q}
Alcampo | robot aspirador;cafetera | https://www.alcampo.es/compra-online/search/?text={q}
Eroski | cafetera | https://supermercado.eroski.es/es/search/results/?q={q}
Dia | cafetera | https://www.dia.es/compra-online/search?q={q}
Lidl | robot aspirador;bicicleta | https://www.lidl.es/q/search?q={q}
Miravia | bicicleta eléctrica;robot aspirador;camiseta | https://www.miravia.es/catalog/?q={q}
Sprinter | zapatillas;bicicleta | https://www.sprintersports.com/es/search?q={q}
Forum Sport | zapatillas;bicicleta | https://www.forumsport.com/on/demandware.store/Sites-ForumSport-Site/es_ES/Search-Show?q={q}
Sport Zone | zapatillas | https://www.sportzone.es/search?q={q}
Intersport | zapatillas;bicicleta | https://www.intersport.es/search?q={q}
Base | zapatillas | https://www.base.net/es/search?q={q}
Privé Sport | zapatillas | https://www.privesport.com/buscar?q={q}
Tradeinn | bicicleta eléctrica | https://www.tradeinn.com/es/search?query={q}
Bikeinn | bicicleta eléctrica | https://www.bikeinn.com/es/buscar?q={q}
Runnerinn | zapatillas | https://www.runnerinn.com/es/buscar?q={q}
Trekkinn | zapatillas | https://www.trekkinn.com/es/buscar?q={q}
Snowinn | zapatillas | https://www.snowinn.com/es/buscar?q={q}
Swiminn | zapatillas | https://www.swiminn.com/es/buscar?q={q}
Smashinn | pala de padel | https://www.smashinn.com/es/buscar?q={q}
Goalinn | zapatillas | https://www.goalinn.com/es/buscar?q={q}
Traininn | zapatillas | https://www.traininn.com/es/buscar?q={q}
Xtremeinn | patinete eléctrico | https://www.xtremeinn.com/es/buscar?q={q}
Techinn | auriculares | https://www.techinn.com/es/buscar?q={q}
Dressinn | camiseta | https://www.dressinn.com/es/buscar?q={q}
Diveinn | neopreno | https://www.diveinn.com/es/buscar?q={q}
Motardinn | casco moto | https://www.motardinn.com/es/buscar?q={q}
Kidinn | bicicleta | https://www.kidinn.com/es/buscar?q={q}
Zalando | zapatillas;camiseta | https://www.zalando.es/catalogo/?q={q}
About You | camiseta | https://www.aboutyou.es/buscar?term={q}
ASOS | camiseta | https://www.asos.com/es/search/?q={q}
Zara | camiseta | https://www.zara.com/es/es/search?searchTerm={q}
Mango | camiseta | https://shop.mango.com/es/search?kw={q}
Pull and Bear | camiseta | https://www.pullandbear.com/es/q/{q}
Bershka | camiseta | https://www.bershka.com/es/q/{q}
Stradivarius | camiseta | https://www.stradivarius.com/es/q/{q}
H&M | camiseta | https://www2.hm.com/es_es/search-results.html?q={q}
Uniqlo | camiseta | https://www.uniqlo.com/es/es/search?q={q}
Lefties | camiseta | https://www.lefties.com/es/search?searchTerm={q}
Kiabi | camiseta | https://www.kiabi.es/search.html?q={q}
C&A | camiseta | https://www.c-and-a.com/es/es/shop/search?q={q}
Springfield | camiseta | https://www.springfield.com/es/es/search?q={q}
Cortefiel | camiseta | https://www.cortefiel.com/es/es/search?q={q}
Women Secret | camiseta | https://womensecret.com/es/es/search?q={q}
Desigual | camiseta | https://www.desigual.com/es_ES/search?q={q}
Scalpers | camiseta | https://scalperscompany.com/es/es/search?q={q}
El Ganso | camiseta | https://www.elganso.com/es/search?q={q}
Nike | zapatillas | https://www.nike.com/es/w?q={q}&vst={q}
Adidas | zapatillas | https://www.adidas.es/search?q={q}
Puma | zapatillas | https://eu.puma.com/es/es/search?q={q}
New Balance | zapatillas | https://www.newbalance.es/search?q={q}
Asics | zapatillas | https://www.asics.com/es/es-es/search?q={q}
Salomon | zapatillas | https://www.salomon.com/es-es/shop/search?q={q}
The North Face | zapatillas | https://www.thenorthface.es/search?q={q}
Columbia | zapatillas | https://www.columbiasportswear.es/search?q={q}
JD Sports | zapatillas | https://www.jdsports.es/search/{q}/
Foot Locker | zapatillas | https://www.footlocker.es/es/search?query={q}
Snipes | zapatillas | https://www.snipes.es/search?q={q}
Footdistrict | zapatillas | https://footdistrict.com/catalogsearch/result/?q={q}
Spartoo | zapatillas | https://www.spartoo.es/busqueda.php?recherche={q}
La Redoute | camiseta;cafetera | https://www.laredoute.es/psrch/psrch.aspx?kwrd={q}
Shein | camiseta | https://es.shein.com/pdsearch/{q}/
AliExpress | bicicleta eléctrica;robot aspirador | https://es.aliexpress.com/w/wholesale-{q}.html
Temu | robot aspirador | https://www.temu.com/search_result.html?search_key={q}&search_method=user
eBay | bicicleta eléctrica;robot aspirador | https://www.ebay.es/sch/i.html?_nkw={q}&_sop=15&LH_BIN=1&rt=nc
Back Market | auriculares;portátil | https://www.backmarket.es/es-es/search?q={q}
CeX | auriculares | https://es.webuy.com/search?stext={q}&sortBy=priceAsc
Cash Converters | bicicleta | https://www.cashconverters.es/es/es/search?q={q}
Refurbed | portátil | https://www.refurbed.es/search/?query={q}
Swappie | iphone | https://swappie.com/es/search/?q={q}
Vinted | bicicleta;camiseta | https://www.vinted.es/catalog?search_text={q}&order=price_low_to_high&currency=EUR
Milanuncios | bicicleta eléctrica | https://www.milanuncios.com/anuncios/?palabras={q}&demanda=n&orden=baratos
Wallapop | bicicleta eléctrica | https://es.wallapop.com/search?keywords={q}&order_by=price_low_to_high
Leroy Merlin | taladro percutor;robot aspirador | https://www.leroymerlin.es/search?q={q}
Obramat | taladro percutor | https://www.obramat.es/search?q={q}
Brico Depot | taladro percutor | https://www.bricodepot.es/search?text={q}
Bauhaus | taladro percutor | https://www.bauhaus.es/buscar?text={q}
AKI | taladro | https://www.aki.es/search?q={q}
ManoMano | taladro percutor | https://www.manomano.es/buscar/{q}
IKEA | sofá | https://www.ikea.com/es/es/search/products/?q={q}
Conforama | sofá | https://www.conforama.es/buscar?controller=search&s={q}
Maisons du Monde | sofá | https://www.maisonsdumonde.com/ES/es/search/{q}
Kave Home | sofá | https://kavehome.com/es/es/search?q={q}
Sklum | sofá | https://www.sklum.com/es/buscar?controller=search&s={q}
Westwing | sofá | https://www.westwing.es/search/?q={q}
Banak Importa | sofá | https://www.banakimporta.com/catalogsearch/result/?q={q}
Coolmod | portátil | https://www.coolmod.com/buscar?controller=search&s={q}
PcBox | portátil | https://www.pcbox.com/buscar?query={q}
App Informática | portátil | https://www.appinformatica.com/catalogsearch/result/?q={q}
Neobyte | portátil | https://www.neobyte.es/buscar?controller=search&s={q}
Beep | portátil | https://www.beep.es/buscar?q={q}
Aussar | portátil | https://www.aussar.es/buscar?controller=search&s={q}
Life Informática | portátil | https://www.lifeinformatica.com/catalogsearch/result/?q={q}
Alternate | portátil | https://www.alternate.es/html/search.html?query={q}
LDLC | portátil | https://www.ldlc.com/es-es/buscar/{q}/
Senetic | portátil | https://www.senetic.es/search?q={q}
Pixmania | auriculares | https://www.pixmania.com/es/s?q={q}
Radio Popular | robot aspirador | https://www.radiopopular.es/buscar?q={q}
Mi electro | robot aspirador | https://www.mielectro.es/buscar?controller=search&s={q}
Electrocosto | robot aspirador | https://www.electrocosto.com/buscar?q={q}
Tien21 | robot aspirador | https://www.tien21.es/buscar?q={q}
Expert | robot aspirador | https://www.expert.es/buscar?q={q}
Euronics | robot aspirador | https://www.euronics.es/es/search?query={q}
Phone House | auriculares | https://www.phonehouse.es/buscar?q={q}
Samsung | robot aspirador | https://www.samsung.com/es/search/?searchvalue={q}
Xiaomi | robot aspirador | https://www.mi.com/es/search/{q}
Cecotec | robot aspirador;bicicleta | https://cecotec.es/buscar?controller=search&s={q}
Game | lego | https://www.game.es/buscar?q={q}
Juguettos | lego | https://www.juguettos.com/catalogsearch/result/?q={q}
Dideco | lego | https://www.dideco.com/buscar?q={q}
Imaginarium | lego | https://www.imaginarium.es/buscar?q={q}
Drim | lego | https://www.drim.es/buscar?q={q}
Eurekakids | lego | https://www.eurekakids.es/buscar?q={q}
Zooplus | transportín | https://www.zooplus.es/search/results?q={q}
Tiendanimal | transportín | https://www.tiendanimal.es/catalogsearch/result/?q={q}
Kiwoko | transportín | https://www.kiwoko.com/busqueda?controller=search&s={q}
Miscota | transportín | https://www.miscota.es/buscar?q={q}
Bitiba | transportín | https://www.bitiba.es/search/results?q={q}
Notino | perfume | https://www.notino.es/search.asp?exps={q}
Douglas | perfume | https://www.douglas.es/es/search?q={q}
Sephora | perfume | https://www.sephora.es/buscar?q={q}
Primor | perfume | https://www.primor.eu/es/catalogsearch/result/?q={q}
Druni | perfume | https://www.druni.es/catalogsearch/result/?q={q}
Arenal | perfume | https://www.arenal.com/es/catalogsearch/result/?q={q}
Lookfantastic | perfume | https://www.lookfantastic.es/search/?q={q}
Perfumes Club | perfume | https://www.perfumesclub.com/es/busqueda/?q={q}
Maquillalia | perfume | https://www.maquillalia.com/buscar?q={q}
PromoFarma | crema | https://www.promofarma.com/es/search?q={q}
Dosfarma | crema | https://www.dosfarma.com/catalogsearch/result/?q={q}
Atida | crema | https://www.atida.com/es-es/catalogsearch/result/?q={q}
Planeta Huerto | robot aspirador | https://www.planetahuerto.es/buscar?q={q}
Verdecora | taladro | https://www.verdecora.es/catalogsearch/result/?q={q}
Fronda | maceta | https://www.fronda.com/buscar?q={q}
Norauto | batería coche | https://www.norauto.es/search?q={q}
Feu Vert | batería coche | https://www.feuvert.es/buscar?q={q}
Oscaro | batería coche | https://www.oscaro.es/es/buscar?q={q}
Autodoc | batería coche | https://www.autodoc.es/search?keyword={q}
Mister Auto | batería coche | https://www.mister-auto.es/buscar/{q}/
Endado | batería coche | https://www.endado.com/es/buscar?q={q}
Trodo | batería coche | https://www.trodo.es/buscar?q={q}
Futbol Emotion | zapatillas | https://www.futbolemotion.com/buscar?q={q}
Soloporteros | zapatillas | https://www.soloporteros.com/es/buscar?query={q}
Padel Nuestro | pala de padel | https://www.padelnuestro.com/catalogsearch/result/?q={q}
Street Padel | pala de padel | https://www.streetpadel.com/buscar?q={q}
Tennis Point | zapatillas | https://www.tennis-point.es/search?q={q}
i-Run | zapatillas | https://www.i-run.es/search?q={q}
Alltricks | bicicleta eléctrica | https://www.alltricks.es/search?q={q}
Probikeshop | bicicleta eléctrica | https://www.probikeshop.es/buscar?controller=search&s={q}
Sanferbike | bicicleta eléctrica | https://www.sanferbike.com/buscar?controller=search&s={q}
Mammoth | bicicleta eléctrica | https://www.mammothbikes.com/buscar?controller=search&s={q}
Wiggle | bicicleta eléctrica | https://www.wiggle.com/es/search?q={q}
Canyon | bicicleta | https://www.canyon.com/es-es/search.html?q={q}
Rose Bikes | bicicleta | https://www.rosebikes.es/search?q={q}
Orbea | bicicleta | https://www.orbea.com/es-es/search?q={q}
BH | bicicleta | https://www.bhbikes.com/es_ES/catalogsearch/result/?q={q}
Conor | bicicleta | https://www.conorbikes.com/buscar?q={q}
Banggood | robot aspirador | https://www.banggood.com/search/{q}.html
Geekbuying | robot aspirador | https://www.geekbuying.com/search?keyword={q}
Rakuten | robot aspirador | https://www.rakuten.es/search/{q}/
Showroomprivé | camiseta | https://www.showroomprive.es/search?q={q}
Veepee | camiseta | https://www.veepee.es/gr/search?q={q}
Groupon | bicicleta | https://www.groupon.es/search?query={q}
"""


def load_stores() -> list[dict]:
    stores = []
    for line in RAW.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, queries, url = [part.strip() for part in line.split("|")]
        stores.append(
            {
                "name": name,
                "queries": [q.strip() for q in queries.split(";") if q.strip()],
                "url": url,
            }
        )
    return stores


STORES = load_stores()
