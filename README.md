# ⚡ EcoBlack V13 did

Este paquete está preparado para subir a GitHub y desplegar una aplicación Flask en Render usando MongoDB Atlas como base de datos persistente. **No incluye `ecoblack.db` ni secretos**.

## Qué se incluye

- `app.py`: punto de entrada. En Render selecciona MongoDB Atlas usando `MONGODB_URI`; sin esa variable, funciona localmente con SQLite.
- `app_mongo.py`: backend MongoDB Atlas con usuarios, módulos, paquetes, sesiones activas, saldos, ingresos del administrador y descuentos.
- `app_sqlite.py`: backend SQLite local para desarrollo.
- `templates/` y `static/`: interfaz EcoBlack V13 completa.
- `requirements.txt`: Flask, PyMongo y Gunicorn.
- `render.yaml`: configuración Blueprints de Render.
- `migrate_sqlite_to_mongo.py`: importación opcional de datos de un `ecoblack.db` local existente.
- `.gitignore` y `.env.example`: ayudan a evitar que subas datos/secretos.

## A. Crear la base de datos en MongoDB Atlas

1. Entra a [MongoDB Atlas](https://cloud.mongodb.com/) y crea un proyecto y un cluster.
2. En **Database Access**, crea un **Database User** con contraseña fuerte y permisos para leer/escribir en la base `ecoblack`. Este usuario de base de datos no es necesariamente tu usuario para iniciar sesión en la web de Atlas.
3. En **Network Access**, permite las IP de salida de Render. Después de crear el servicio de Render, abre el servicio → **Connect** → **Outbound** y añade los rangos CIDR que Render muestre a la lista de acceso IP de Atlas. Para probar desde tu propia computadora, añade también tu IP pública.
4. En el cluster pulsa **Connect → Drivers → Python** y copia el connection string `mongodb+srv://...`. No uses la contraseña de tu cuenta personal de Atlas.
5. Si la contraseña del database user contiene caracteres especiales, usa el valor percent-encoded en la URI.

> Evita `0.0.0.0/0` como configuración permanente: permite intentar conexiones desde cualquier dirección IP. Atlas exige una lista de acceso IP y recomienda restringirla a orígenes confiables. Consulta la documentación oficial de [conexión de Atlas](https://www.mongodb.com/docs/atlas/connect-to-database-deployment/) y su [lista de acceso IP](https://www.mongodb.com/docs/atlas/security/ip-access-list/).

## B. Subir el proyecto a GitHub desde Windows

1. Descomprime este ZIP en una carpeta nueva, por ejemplo `C:\Users\TU_USUARIO\Downloads\EcoBlack-V13-Deploy`.
2. Crea un repositorio vacío en [GitHub](https://github.com/new), por ejemplo `ecoblack-v13`. No marques la opción de añadir README porque este paquete ya tiene uno.
3. Abre PowerShell dentro de la carpeta donde están directamente `app.py` y `requirements.txt`.
4. Ejecuta:

```powershell
git init
git add .
git status
git commit -m "EcoBlack V13 deploy"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/ecoblack-v13.git
git push -u origin main
```

Cambia `TU_USUARIO` por tu nombre de GitHub. Revisa `git status` antes del commit: **no debe aparecer `ecoblack.db`, `.env` ni contraseñas**. Si Git dice que `git` no existe, instala Git for Windows y vuelve a abrir PowerShell.

Si ya conectaste `origin` anteriormente, no vuelvas a ejecutar `git remote add origin`; usa `git remote -v` para revisarlo.

## C. Desplegar con Render

Puedes usar el archivo `render.yaml` incluido:

1. Entra a [Render](https://dashboard.render.com/).
2. Selecciona **New → Blueprint** y conecta el repositorio de GitHub `ecoblack-v13`.
3. Render leerá `render.yaml`. Confirma el servicio `ecoblack`.
4. En las variables del servicio, rellena los valores secretos que Render solicite:

| Variable | Qué poner |
|---|---|
| `MONGODB_URI` | La URI de conexión copiada de Atlas, completa y privada |
| `MONGODB_DB` | `ecoblack` |
| `SECRET_KEY` | Déjala generada por Render; no la publiques |
| `ADMIN_USERNAME` | `tragic` |
| `ADMIN_PASSWORD` | Una contraseña fuerte elegida por ti para el admin en producción |

`render.yaml` configura automáticamente:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 120`
- Health check: `/healthz`

Render despliega los cambios cada vez que se suben commits a la rama vinculada. Documentación: [desplegar Flask en Render](https://render.com/docs/deploy-flask) y [servicios web](https://render.com/docs/web-services).

## D. Comprobar que está conectado

Cuando finalice el despliegue, abre estas direcciones sustituyendo el dominio por el que Render te haya asignado:

- `https://TU-SERVICIO.onrender.com/healthz` — debe devolver `{"ok":true,"database":"connected"}`.
- `https://TU-SERVICIO.onrender.com/` — muestra EcoBlack.
- `https://TU-SERVICIO.onrender.com/api/modules` — devuelve módulos iniciales en JSON.

La primera inicialización de un Atlas vacío crea el administrador y los módulos de demostración. En Render el administrador usa la contraseña definida en `ADMIN_PASSWORD`, no una contraseña publicada en el código. Si ya existe `tragic` en Atlas, cambiar esa variable **no cambia** la contraseña del usuario existente.

## E. Si quieres conservar los datos de tu SQLite local

El despliegue en Atlas empieza con su propia base de datos. Si tienes usuarios, módulos, sesiones o contabilidad que quieras importar:

1. Haz una copia de seguridad de tu `ecoblack.db` local.
2. Copia el archivo `ecoblack.db` **temporalmente** junto a `migrate_sqlite_to_mongo.py` en una copia local de esta carpeta. No lo subas a GitHub.
3. Instala las dependencias en tu PC: `py -m pip install -r requirements.txt`.
4. En PowerShell define la URI solo en esa terminal y ejecuta el migrador:

```powershell
$env:MONGODB_URI="PEGA_AQUI_TU_URI_DE_ATLAS"
$env:MONGODB_DB="ecoblack"
$env:ADMIN_USERNAME="tragic"
py migrate_sqlite_to_mongo.py
```

5. Abre Atlas y verifica usuarios, módulos, sesiones e ingresos antes de volver a desplegar.

El migrador no borra tu SQLite y conserva la contraseña del administrador creada en Atlas, para no reemplazarla por el hash local de demostración. Haz backup de Atlas antes de repetir una migración, porque los documentos con IDs coincidentes se reemplazan con los datos locales.

## Probar en local

Sin definir `MONGODB_URI`, la app usa SQLite local:

```powershell
py -m pip install -r requirements.txt
py app.py
```

Visita `http://127.0.0.1:5000`. Cuenta de demostración local: `tragic` / `69`. En producción, usa la contraseña fuerte de `ADMIN_PASSWORD`.

## Notas importantes

- Atlas guarda usuarios, módulos, sesiones y recaudación; el hosting de Render puede recrear sus archivos locales, por eso la app en Render se dirige a Atlas.
- La tarjeta permanece desactivada para cobros reales hasta que integres una pasarela bancaria. Efectivo sigue siendo pendiente hasta confirmación del admin.
- Los paquetes y watts son límites de cálculo de la app; no pueden controlar la potencia física de un cargador sin integración de hardware.
- Protege siempre `MONGODB_URI`, `ADMIN_PASSWORD`, `SECRET_KEY` y tu `ecoblack.db`. No los pegues en el chat ni dentro del código fuente.
