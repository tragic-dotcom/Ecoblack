# EcoBlack V20 — bienvenida pro, globo mundial y geolocalización

EcoBlack conserva su estructura Flask. En Render, `app.py` selecciona MongoDB Atlas mediante `MONGODB_URI`; en local, si esa variable no existe, usa SQLite.

## Acceso por plan

- Cada cuenta nueva comienza **Sin plan**. La tarjeta de inicio muestra el plan actual y el estado de acceso.
- Una cuenta normal debe comprar un plan antes de iniciar una carga. Puede consultar el mapa y los paquetes, pero el servidor rechaza conexiones sin un plan activo.
- Los planes **Básico, Rápido, Power y Personalizado** incluyen una sesión. Se pagan antes de conectar; al iniciar esa sesión, el plan se consume y vuelve a quedar la cuenta en **Sin plan**.
- No se vuelve a descontar saldo al conectar una sesión que ya fue comprada.
- Una cuenta no puede comprar otro plan estándar mientras conserve uno listo para usar.
- El servidor verifica el plan vigente y el tipo de módulo en cada conexión. No basta con cambiar el selector del navegador.

## Bmax Pro: acceso VIP exclusivo

- Bmax Pro solo se puede comprar desde su apartado limitado y solo puede utilizarse en módulos que tengan `module_type: "bmax"`.
- Un plan normal no puede abrir un módulo Bmax. Bmax Pro tampoco puede abrir un módulo normal.
- Hay 10 cupos iniciales. El precio inicial es **$99 MXN**, editable desde el panel de administrador.
- Antes de confirmar, el usuario aparta un lugar durante **5 minutos**. El servidor libera los apartados vencidos y controla el inventario en Atlas para evitar sobreventas.
- Al confirmar la compra, Bmax Pro queda permanente en la cuenta y el usuario puede realizar sesiones Bmax posteriores sin volver a comprar el plan.
- Si no hay cupos, el servicio aparece como **Agotado**. El administrador puede aumentar o reducir el total, pero no por debajo de los cupos vendidos o apartados.
- Bmax Pro tiene un límite máximo de paquete de **100 W**. La potencia efectiva es el menor valor entre el límite Bmax, la capacidad estimada del teléfono, la potencia registrada del módulo y el límite del conector.
- La sesión estima el tiempo hasta 100% usando el porcentaje inicial y la capacidad del dispositivo. Cuando el navegador admite `navigator.getBattery()`, intenta leer la batería; si no, el usuario puede ajustarla manualmente.

## Módulos y mapa

- Desde **Administración → Añadir módulo**, el admin puede crear módulos EcoBlack normales o módulos `Bmax · negro / morado`.
- Cada módulo nuevo requiere nombre, una ubicación y sus coordenadas. Usa **Elegir punto en el mapa** para fijar la posición; ciudad, estado y país se completan automáticamente cuando el servicio de geocodificación responde. Si pulsas **Añadir al mapa** sin coordenadas, la aplicación abre automáticamente el modo de selección.
- Los módulos Bmax tienen carcasa negra y detalles violetas; cuando están ocupados muestran su halo especial.
- Los módulos permanecen anclados a las coordenadas guardadas. El marcador no se desplaza por animaciones de escala cuando se acerca o aleja el mapa.
- El mapa cambia de nivel de detalle: **vista regional/estatal** con nombre del estado y número de módulos; **vista de ciudad** con nombre de ciudad y conteo; y, al acercarse, **marcadores individuales** en su ubicación guardada.
- El admin puede usar el botón **Ciudad/estado/país** para completar metadatos de módulos antiguos que todavía no tengan esos campos y **Reubicar** para corregir su posición exacta.
- Para los módulos predeterminados de Cancún, la aplicación completa automáticamente `Cancún, Quintana Roo` en registros antiguos que no tengan esos valores. No reemplaza nombres geográficos que ya estén configurados.

## Apariencia por plan y animación Bmax

- Cada plan cambia el color de acento de la interfaz y de los marcadores normales.
- Bmax Pro aplica una apariencia VIP morada a toda la interfaz.
- Al conectar un módulo Bmax aparece una animación exclusiva con núcleo luminoso, aura espectral violeta, niebla, destellos y anillos de energía. Respeta la preferencia de movimiento reducido del dispositivo.

## Persistencia en MongoDB Atlas

La aplicación crea las colecciones e índices que necesita al iniciar. Bmax usa:

- `bmax_config`: cupos totales, vendidos, apartados y precio.
- `bmax_reservations`: apartados temporales y su vencimiento.
- `bmax_purchases`: compras y acceso permanente del usuario.

Los QR promocionales usan la colección `package_qr_campaigns`, con un token estable por paquete; cada cupón reclamado se guarda en el documento del usuario y se marca como usado al confirmar la compra. Los planes estándar guardan el plan activo y su estado en el documento del usuario (`active_plan`, `active_plan_status`, `active_plan_minutes` y campos de compra/consumo). Los módulos guardan `module_type`, `city` y `state`; el perfil admin puede guardar `admin_service_theme`. No hace falta crear estas colecciones o campos manualmente.

## Variables de entorno en Render

Conserva las variables actuales del servicio:

- `MONGODB_URI`: cadena de conexión de MongoDB Atlas.
- `MONGODB_DB`: normalmente `ecoblack`.
- `SECRET_KEY`: clave larga y aleatoria.
- `ADMIN_USERNAME`: usuario administrador ya configurado.
- `ADMIN_PASSWORD`: contraseña segura del administrador.
- `APP_BASE_URL` (opcional): URL pública completa de Render, por ejemplo `https://ecoblack.onrender.com`; se usa para construir los enlaces QR.

No subas `.env`, contraseñas ni cadenas de MongoDB a GitHub. Esta versión no requiere cambiar `MONGODB_URI` ni `MONGODB_DB`.

## Pruebas recomendadas tras desplegar

1. Crea una cuenta normal y confirma que Inicio muestre **Sin plan**.
2. Intenta conectar cualquier módulo sin comprar: el servidor debe rechazarlo.
3. Compra un plan estándar, conecta un módulo normal y confirma que la sesión se incluye sin un segundo cargo; al comenzar, la cuenta debe volver a **Sin plan**.
4. Intenta conectar un módulo Bmax con un plan estándar: debe rechazarlo.
5. Compra Bmax Pro con una cuenta distinta, usando el apartado de 5 minutos, y confirma que se vea el acceso VIP morado.
6. Con Bmax Pro, conecta un módulo Bmax: debe funcionar. Intenta conectar un módulo normal: debe rechazarlo.
7. Prueba el mapa a escala estatal, de ciudad y de calle. Revisa nombres y conteos; abre un pin y confirma que la ubicación coincide con las coordenadas guardadas.
8. Desde el admin, completa ciudad/estado de módulos antiguos, crea un módulo nuevo y confirma que persista en Atlas.
9. Prueba dos cuentas intentando apartar el último cupo Bmax; solo una debe obtenerlo.

## Nota técnica sobre carga real

Esta versión implementa planes, reservas, compras, autorizaciones, mapa y estimaciones dentro de la aplicación web. **No controla eléctricamente un cargador ni puede garantizar una carga física de 100 W o una batería al 100%** sin integrar el hardware, los protocolos de carga y telemetría real. La potencia y los minutos mostrados son estimaciones de software.


## V17 · Reparación de mapa y panel admin

- El formulario ya no acepta coordenadas vacías ni el punto accidental `0, 0`; exige una ubicación real antes de guardar.
- El admin puede reubicar módulos existentes desde el mapa, útil para corregir módulos guardados anteriormente en una esquina o con coordenadas incompletas.
- Los módulos sin coordenadas válidas ya no generan pines fantasma ni agrupaciones falsas; aparecen marcados como `Ubicación pendiente` en el panel admin.
- Al guardar un módulo, la app cambia primero a la vista del mapa, espera que el mapa esté visible/listo, lo redimensiona y centra el nuevo pin en sus coordenadas reales.
- El panel de administrador inicia con tema vino. Se agregó un selector de vista para los temas Básico (verde), Rápido (azul), Power (naranja), Personalizado (turquesa) y Bmax Pro (violeta). La preferencia se guarda en el perfil del admin en Atlas/SQLite. El selector solo cambia el aspecto del panel admin, no cambia planes ni permisos de clientes.
- Las validaciones se aplican tanto al backend MongoDB Atlas como al backend local SQLite.
- Se corrigió el posicionamiento de MapLibre: el pin ahora usa un contenedor geográfico independiente del botón visual, de modo que las reglas CSS de animación no anulan la transformación de coordenadas del mapa.


## V19 · Experiencia pública, paquetes y promoción QR

- Cuando una persona abre EcoBlack sin iniciar sesión, ve una presentación pública con el propósito de la app, beneficios y catálogo de **Paquetes**. No ve el mapa ni puede utilizar módulos, perfil, sesiones o administración. Las rutas API de módulos, paquetes privados, perfil, compras y sesiones requieren autenticación; el catálogo público y los enlaces QR solo muestran información comercial.
- El texto visible **Servicios** se reemplazó por **Paquetes**.
- Cada paquete tiene un botón con símbolo QR. El código abre una página pública de EcoBlack con el nombre del paquete, lo que incluye, precio de referencia y oferta del 50%. El QR no contiene datos privados: solo una URL de la aplicación publicada.
- Al crear una cuenta nueva desde el enlace de ese QR, el servidor asigna un cupón del 50% ligado exclusivamente al paquete de ese código. El descuento se consume solo cuando la compra del paquete se confirma; no se aplica a otro paquete ni vuelve a utilizarse después. Iniciar sesión con una cuenta existente no genera el cupón.
- El catálogo sin sesión solo permite conocer los paquetes y crear/iniciar sesión. Para consultar el mapa y utilizar el resto de la aplicación hay que crear una cuenta e iniciar sesión.
- Se añadió un destello con partículas que sigue el ratón o el dedo. En el perfil se puede personalizar como aura violeta, chispa eléctrica, destello dorado, luz hielo o desactivarlo. La preferencia se guarda en ese navegador.
- Los códigos QR se generan desde el servidor mediante la biblioteca `qrcode` y abren páginas públicas en la URL de Render. La app usa `APP_BASE_URL` cuando está configurada; si no, construye la dirección con los encabezados del proxy de Render.

### Cómo funciona el descuento QR

1. El visitante pulsa el botón QR de un paquete o escanea un código impreso.
2. La página QR muestra «¡Gracias por escanear!» y el 50% asociado a ese paquete.
3. El visitante crea una cuenta nueva desde esa página. El cupón queda guardado en su registro de usuario en Atlas.
4. La cuenta muestra el paquete con el descuento. Al comprarlo, el servidor valida que el cupón corresponda al mismo paquete y que todavía no se haya usado.
5. Una cuenta existente que inicia sesión no recibe una promoción nueva. La sesión del navegador también recuerda que ya se utilizó EcoBlack.

**Límite de identidad:** como EcoBlack todavía no verifica correo, teléfono ni identidad personal, la protección actual es por cuenta y por sesión/navegador. No puede demostrar que una persona no tenga otra cuenta creada en otro dispositivo o navegador. Para impedirlo de forma sólida habría que añadir verificación de correo o teléfono.

### URL pública de los QR en Render

`APP_BASE_URL` es opcional. Si se configura, debe contener la URL pública completa, por ejemplo `https://ecoblack.onrender.com` (sin una barra final). Si no se configura, EcoBlack utiliza el host/protocolo reenviado por Render. El generador rechaza `localhost`, `127.0.0.1` y HTTP para evitar imprimir un QR que no abra desde otro teléfono. En local, configura `APP_BASE_URL` con tu dominio público HTTPS de Render para probar los códigos.

### Verificación V19

- Abrir el sitio sin sesión: deben verse paquetes y explicación, pero no mapa ni herramientas privadas.
- Abrir `/api/modules` sin sesión: debe responder `401`.
- Escanear el QR de un paquete: debe abrir `/qr/<token>` en la URL pública de Render y mostrar 50% para cuentas nuevas.
- Crear una cuenta desde el QR: el cupón debe aparecer solo para el paquete enlazado.
- Intentar comprar otro paquete: el cupón no debe aplicarse.
- Comprar el paquete asociado: el 50% se debe aplicar una vez y el cupón quedar marcado como usado.
- Iniciar sesión con una cuenta existente desde un QR: no debe recibir un cupón.
- Probar los efectos del cursor en escritorio y pantalla táctil; cambiar de preferencia en Perfil.


## V20 · Experiencia pro, vuelo desde el globo y autoubicación de módulos

- Animación cinematográfica de globo mundial al abrir el mapa. El mapa inicia en una vista global y hace un vuelo hasta la ubicación del usuario cuando este concede el permiso de geolocalización. Si no concede el permiso, utiliza como destino la zona aproximada de los módulos de la red.
- El formulario de alta/reubicación permite elegir un punto directamente en el mapa. Las coordenadas quedan guardadas y la aplicación intenta completar ciudad, estado/provincia y país.
- La búsqueda inversa usa OpenStreetMap Nominatim solo después de que el administrador elige un punto; almacena localmente los resultados para no repetir consultas de coordenadas cercanas y espera al menos 1.2 segundos entre solicitudes en la misma pestaña.
- La información de país se persiste en MongoDB Atlas y SQLite y se utiliza para separar correctamente estados que tengan el mismo nombre en países distintos.
- El cursor sigue el ratón o el dedo con aura personalizable, partículas, destellos en forma de estrella, retícula y ondas al tocar. La preferencia se puede cambiar desde Perfil.
- Inicio incorpora HUD energético, núcleo animado, orbes, indicadores de red, tarjetas con entrada progresiva y brillos en interacción.

**Permisos y precisión:** el vuelo al lugar real requiere aceptar el permiso de ubicación del navegador y utilizar HTTPS (Render ya lo proporciona). La geocodificación inversa depende de Internet y de la cobertura de OpenStreetMap; puede devolver la población o zona más cercana al punto, no necesariamente el nombre exacto de la colonia. Si no responde, conserva las coordenadas y deja los campos editables para completar a mano. Se muestra atribución a OpenStreetMap.

**Uso del servicio geográfico:** la instancia pública de Nominatim limita la aplicación a un máximo de una solicitud por segundo sumando todos sus usuarios, exige identificación del sitio mediante Referer o User-Agent y pide caché y atribución. Para un volumen mayor conviene configurar otro proveedor o alojar un servicio propio. Consulta la [política de uso de Nominatim](https://operations.osmfoundation.org/policies/nominatim/).


### Verificación V20

- Al abrir el mapa, confirmar que aparece el globo y luego el vuelo hacia la ubicación concedida por el navegador. Si se deniega, comprobar que la red se muestra en la vista global/zona de módulos.
- En Administración → Añadir módulo, pulsar Elegir punto en el mapa y seleccionar una ubicación; comprobar que latitud/longitud se guardan y que ciudad, estado y país se rellenan.
- Seleccionar por segunda vez un punto ya consultado y verificar que se utiliza la caché local.
- Repetir en una conexión sin servicio de geocodificación; las coordenadas deben persistir y los campos deben poder editarse manualmente.
- Probar el cursor con ratón y pantalla táctil, cambiar sus efectos en Perfil y comprobar el respeto a `prefers-reduced-motion`.
