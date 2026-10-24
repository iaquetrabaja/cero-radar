# CERO · Radar de chollos

Panel local que busca **productos físicos a 0 € y descuentos de al menos el 80 %**, con imágenes reales, filtros, vigilancia, búsqueda continua y puntuación opcional con Gemini.

El buscador descubre candidatos. La ficha determina precio y variante. Una cesta anónima comprueba los ceros en las plataformas compatibles. Gemini interpreta las evidencias y puntúa: no inventa precios ni confirma compras.

## Instalar

Python 3.12 o superior. En Windows:

```powershell
git clone https://github.com/iaquetrabaja/cero-radar.git
cd cero-radar
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python configure.py --country ES
.venv\Scripts\python run.py
```

Abre **http://127.0.0.1:8765/**. No necesitas activar el entorno ni cambiar políticas de PowerShell. En Linux/macOS sustituye `.venv\Scripts\python` por `.venv/bin/python` y usa `cp .env.example .env`.

## Gemini y gasto

Añade tu propia `GEMINI_API_KEY` en `.env`. Sin clave continúa el rastreo, con puntuaciones etiquetadas como reglas.

Usa **Gemini 2.5 Flash-Lite**, análisis por lotes, caché y razonamiento desactivado. No usa búsqueda de pago para puntuar. Límite predeterminado: **3 €/día**, reducible con `GEMINI_DAILY_BUDGET_EUR`. Se reserva el coste antes de cada llamada mediante una transacción; los tiempos de espera conservan su reserva. La estimación incluye margen y no sustituye la factura del proveedor. Consulta la [tarifa oficial](https://ai.google.dev/gemini-api/docs/pricing).

El límite se reinicia a medianoche de `BUDGET_TIMEZONE`, incluyendo cambios de hora. Alcanzarlo pausa la IA, no las fuentes gratuitas. No cambia a un modelo más caro automáticamente.

## Tu país y tus tiendas

La instalación de referencia está probada en **España**. Incluye más de 1.300 dominios. **Los contadores de análisis empiezan en cero** y aumentan con lecturas reales. Una tienda registrada, una web analizada y una compra comprobada son estados distintos.

Antes del primer arranque puedes elegir ES, PT, FR, DE, IT, GB, US o MX:

```powershell
.venv\Scripts\python configure.py --country FR --store "Mi tienda|https://mitienda.fr/"
```

La configuración queda en `config/market.local.json`, ignorado por Git. Puedes cambiar país, moneda, idioma, zona horaria, dominio de Amazon y tiendas. **Otros países son perfiles de configuración: sus comercios y adaptadores necesitan validación local; no se promete la misma cobertura.** Para otro país con datos existentes, utiliza otra carpeta de instalación. CERO impide mezclar mercados en la misma base.

En **Fuentes de rastreo → Añadir una tienda** registra comercios sin modificar código. En las siguientes pasadas se descubren su plataforma, precios y secciones de ofertas. Los bloqueos quedan identificados.

## Panel y fiabilidad

- Filtros por país, tienda, categoría, subcategoría, tipo, precio, descuento, score, stock y favoritos.
- Calas, sillines y frenos en **Deporte → Ciclismo**, con tipos propios.
- Imagen real descargada y validada obligatoria; las fichas sin foto quedan retenidas.
- **0 € con portes sí es válido**. Precio, gastos y total se separan; destino o gastos desconocidos se indican como pendientes.
- Ceros realmente agotados permanecen tanto en el radar general como en Ceros sin stock, con prioridad menor, y se revisan **cada 12 h**. Un 404, una página vacía con HTTP 200 o un precio interno no cuenta como reposición comprobada.
- Las ofertas interesantes se conservan aunque falle una lectura o cambie el precio. El radar distingue activas, agotadas, pendientes de renovar y finalizadas, y muestra el mejor precio observado.

El PVP tachado **no es un histórico independiente**. Referencias sospechosas quedan pendientes de contraste. No se tramitan pedidos ni se facilitan direcciones; la tienda decide si acepta y entrega un error de precio.

El score del radar expresa interés. Un cero físico comprobado en cesta tiene prioridad mínima de 96; uno real sin stock tiene 60. Si esta prioridad corrige una valoración baja de Gemini, se etiqueta como **Prioridad**, conservando la puntuación original de IA en los detalles. Los portes desconocidos y no haber tramitado un pedido no convierten un cero comprobado en un mal hallazgo.

## Cómo descubre productos

Catálogos públicos WooCommerce y Shopify, páginas de ofertas, schema.org, Amazon por ASIN, el catálogo público de Deporvillage en España y consultas rotativas en varios motores. Incluye miles de combinaciones por tienda y CMS: `0,00 €`, `0,00€`, `0.00€`, botones y porcentajes con distintos signos.

Las consultas descubren URLs; el cero del carrito vacío nunca se convierte en precio. El panel registra errores y resultados. No hay cobertura total de Internet ni resultados garantizados. No resuelve CAPTCHAs ni compra proxies. Scrapling realiza lecturas HTTP; el motor principal no abre un navegador por producto.

## Funcionar continuamente

Encadena exploraciones con pausa de 60 segundos, vigilancia cada 15 minutos y rastreo profundo diario. Rota fuentes y aplica pausas tras errores. Ajusta la programación en Configuración. **Detener** cancela la pasada y pausa la programación hasta reactivarla.

Inicio de sesión de Windows y reinicio si el proceso termina:

```powershell
.venv\Scripts\python scripts/install_startup.py
.venv\Scripts\python scripts/supervisor.py
```

La segunda orden lo inicia ahora; después se ejecuta oculto al iniciar sesión. Evita duplicados y no termina otros programas que ocupen el puerto. Para quitarlo elimina `CERO Radar.vbs` de la carpeta Inicio de Windows. Datos en `data/`; imágenes temporales en `cero/static/cache/`.

Necesita ordenador encendido, conectado y sin suspensión. Para funcionar con el PC apagado, instálalo en un servidor con un gestor de procesos. Mantén el panel privado: no incorpora autenticación para exposición pública.

## Amazon

Configura **tu propio ID** en `AMAZON_ASSOCIATE_TAG`. Los enlaces de salida lo incluyen; las URLs internas se guardan limpias para deduplicar. La interfaz identifica la afiliación. El parámetro de descuento de Amazon sirve para descubrir, nunca para probar una rebaja.

## Telegram preparado y desactivado

Sin opciones en el panel y sin envíos automáticos. Bandeja local y transporte con foto, precio, gastos y enlace. Inspección sin enviar:

```powershell
.venv\Scripts\python -m cero.notify
```

Para una futura activación crea tu bot y destino, configura `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ENABLED=true`, reinicia y ejecuta `python -m cero.notify --send`. Antes de enviar revisa estado, imagen y antigüedad; no manda ofertas caducadas. No publiques tokens. La programación de envíos es independiente del rastreo.

## Desarrollo

```powershell
.venv\Scripts\python -m unittest test_cero -q
.venv\Scripts\python hunt.py --profile normal --wait
```

Las regresiones cubren carrito vacío, productos relacionados, variantes, botones deshabilitados, compra oculta, referencias, fotos, afiliación, categorías, enlaces rotos, reposición, cambio de hora y presupuesto. No llaman a Gemini ni tramitan pedidos.

Los adaptadores nuevos devuelven candidatos que pasan por `hunter.check_url`, `verification` e `images`. No publiques directamente resultados de buscador. Se bloquean redes privadas y se comprueban las redirecciones. Los cambios del panel se aceptan desde su origen local.

## Casos observados

El 24 de octubre de 2026 mantuvieron precio cero, por separado y en cesta anónima, una **turmalina en Lozano Gemólogos** y una **bolsa física Dr.Grandel en être belle**. La primera cesta mostraba 6,05 € de gastos sin seleccionar destino. Son observaciones fechadas, no ofertas permanentes ni pedidos entregados. Se descartaron falsos positivos: una variante Origins no comprable y compra oculta en Cuatro Rayas.

## Créditos

MIT para este código. [Scrapling](https://github.com/D4Vinci/Scrapling) conserva su licencia. Se estudió [omkarcloud/amazon-scraper](https://github.com/omkarcloud/amazon-scraper); este proyecto implementa su propio adaptador. Los dominios españoles proceden de información pública de ecomNinja y ExpoTienda; los registros conservan origen. Marcas e imágenes pertenecen a sus titulares.
