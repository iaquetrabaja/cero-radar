# Radar compartido en un servidor

Dos procesos comparten SQLite y las fotos: `worker` rastrea y controla el presupuesto; `public` consulta los resultados en modo de solo lectura. El visor no recibe la clave de Gemini, no muestra gastos y no ofrece controles administrativos. El panel local habitual sigue disponible para instalaciones personales.

El ejemplo `compose.yaml` está preparado para la red Docker `lara_default` del servidor de Tools. **No publica puertos en el host.** Adapta esa red y tu proxy al instalarlo en otra infraestructura. No publiques directamente el puerto del worker.

1. Copia el código y prepara `data/` y `cache/`, con permisos para UID 10001. La base `data/cero.db` debe estar inicializada por el worker. Su copia debe incluir las observaciones y el gasto del día si migras desde otro equipo.
2. Crea `.env.server`, fuera de Git, con `GEMINI_API_KEY`, `GEMINI_DAILY_BUDGET_EUR`, `BUDGET_TIMEZONE` y tu `AMAZON_ASSOCIATE_TAG`. Restringe sus permisos. El visor solo recibe el identificador de afiliado.
3. Inicia los servicios:

   ```sh
   docker compose --env-file ../.env.server -f compose.yaml up -d --build
   ```

4. El proxy debe exigir una sesión de usuario verificado **en todas las rutas** de `/cero/radar/`, incluidas API, JavaScript, CSS y fotografías. En Tools se reutiliza `auth_request /_cuenta_auth` y la redirección de acceso a cuentas existente. El visor no gestiona contraseñas ni sustituye esa autenticación.
5. Elimina el prefijo `/cero/radar/` al reenviar a `cero-public:8000`. La aplicación genera sus enlaces con ese prefijo; se puede cambiar con `CERO_PUBLIC_PREFIX`.
6. Comprueba sin sesión que HTML, API y fotos solicitan acceso. Con una cuenta verificada deben verse productos y filtros. Las rutas administrativas no existen en el visor y todos los verbos de escritura devuelven 405.

Conserva copias de seguridad de SQLite mediante su API de backup, junto con las fotos. No copies capturas privadas de pedidos al directorio público. Los ejemplos históricos del visor solo reutilizan fotografías públicas de productos ya guardadas en caché.

Ejecuta un único rastreador por instalación. Al migrar, pausa la programación anterior antes de activar la nueva: dos bases independientes no comparten las reservas del presupuesto diario. `restart: unless-stopped` mantiene los servicios tras reiniciar el servidor; la búsqueda sigue mientras este permanezca disponible.
