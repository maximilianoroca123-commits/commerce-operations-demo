# Gestión comercial: demostración funcional

[Español](README.es.md) · [English](README.en.md)

Aplicación de portafolio para un negocio pequeño: catálogo e inventario, ventas, caja, pedidos online, entregas, devoluciones, atención al cliente y abastecimiento. Incluye una demostración de reposición automática con presupuesto reservado, aprobación manual de pago simulado y despacho automático del proveedor ficticio.

La web ofrece las mismas funciones en español e inglés mediante el selector del encabezado. Un único backend y una única base conservan las reglas, cantidades, saldos e historial. No son dos aplicaciones independientes.

**Todos los pagos, QR y procesos del proveedor automático son de demostración. No se conectan bancos ni se realizan transferencias reales. Los comprobantes no tienen validez fiscal.**

## Funcionalidades

- Catálogo paginado, búsqueda, filtros, ficha de producto y movimientos de inventario.
- Creación y edición de productos para administración.
- Venta presencial: carrito, apertura de caja, recibido, vuelto, movimientos y cierre por conteo.
- Compra online: reserva temporal, pago simulado, pedidos propios y seguimiento de entrega.
- Devolución física y reintegro separados, con respuesta final visible para el cliente.
- Catálogo del proveedor, vínculo de ofertas, pedidos, avisos y remitos parciales o completos.
- Reposición de muestra: regla general, fondo ficticio, reserva del importe, pago aprobado y despacho automático; recepción manual.
- Autenticación por cuenta, permisos por rol y restricciones de pertenencia de pedidos.
- Auditoría, pruebas de regresión y respaldos verificados.
- Comprobantes HTML de ventas en ES/EN y conservación de datos de la operación.

## Tecnologías y organización

Python, FastAPI, Pydantic, SQLite y JavaScript sin framework de frontend. HTML y CSS se sirven desde la misma aplicación que la API. La web no requiere compilación ni Node para funcionar. Node se utiliza en las pruebas de JavaScript y DOM.

Los identificadores de la API, nombres de tablas y buena parte de las funciones mantienen sus nombres originales en español para conservar compatibilidad. La documentación técnica y los comentarios principales de esta edición utilizan lenguaje formal; el selector traduce la presentación, no el esquema de datos.

## Instalación local

Usar una carpeta nueva. El paquete no incluye bases privadas, contraseñas personales, respaldos ni capturas personales. La preparación agrega el esquema y los productos iniciales si la base está vacía; no es una orden para reiniciar datos existentes.

Entorno verificado durante esta entrega: **Python 3.12.14 y Node 24.22.3** para las pruebas. La aplicación original también se utilizó en Windows con un entorno Python 3.14. Las dependencias de Python están fijadas en los archivos requirements.

### Windows / PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-pruebas.txt
.\.venv\Scripts\python.exe demo_setup.py --language es
.\.venv\Scripts\python.exe -m uvicorn servidor:app --host 127.0.0.1 --port 8000
```

### Linux / macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-pruebas.txt
.venv/bin/python demo_setup.py --language es
.venv/bin/python -m uvicorn servidor:app --host 127.0.0.1 --port 8000
```

Abrir **http://127.0.0.1:8000/interfaz/**. La API debe permanecer encendida. Elegir **Español** o **English** en el encabezado; el idioma se conserva localmente. No se guardan credenciales en el almacenamiento local.

La preparación pide una contraseña, sin mostrarla, para las cuentas ficticias nuevas. Debe tener 10–128 caracteres ASCII. Las cuatro cuentas nuevas comparten esa contraseña sólo para facilitar esta demostración local. Repetir la preparación no cambia contraseñas ni cuentas ya existentes.

| Cuenta ficticia | Rol |
| --- | --- |
| `demo_admin` | Administrador |
| `demo_staff` | Empleado |
| `demo_customer` | Cliente |
| `demo_supplier` | Proveedor asociado a Demo |

Si se usa una copia de una base existente, se conservan sus cuentas y contraseñas. No es necesario ejecutar la preparación de cuentas para utilizar el selector de idioma.

## Demostración y pruebas

El recorrido más corto está en [docs/DEMO.es.md](docs/DEMO.es.md). El administrador puede preparar el ejemplo automático desde la web, agregar fondos ficticios, aprobar el pago y observar el despacho antes de confirmar la recepción.

```bash
python -m unittest discover -q
npm ci
npm test
```

Usar el intérprete del entorno virtual para la primera orden. `npm ci` instala únicamente dependencias de desarrollo; no es necesario para ejecutar la aplicación. Las herramientas QR de consola son opcionales y sus dependencias están en `requirements-qr.txt`.

La descripción de los casos, niveles de comprobación y limitaciones de las pruebas se encuentra en [docs/TESTING.es.md](docs/TESTING.es.md).

## Idiomas, datos y compatibilidad

Cambiar el idioma no duplica pedidos ni reinicia la sesión, el carrito o los campos de formulario. Las confirmaciones y operaciones en curso bloquean temporalmente el cambio para conservar un resumen coherente. Fechas e importes se presentan según el idioma; la moneda sigue siendo ARS.

Los nombres de productos, marcas, referencias, correos, notas y respuestas redactadas por usuarios conservan su texto original. Los avisos generados por el proveedor simulado se localizan. El idioma modifica etiquetas y mensajes, no los datos del negocio.

Las herramientas históricas de consola conservan su interfaz original en español. La web de presentación y la preparación de cuentas son ES/EN; las operaciones adicionales se documentan en ambos idiomas y también se pueden invocar por la API. No se afirma que todos los menús de consola estén traducidos ni que todas las herramientas administrativas tengan pantalla web.

## Alcance y límites

Este es un prototipo personal de demostración, desarrollado de forma iterativa con asistencia de IA y validación mediante pruebas. No representa un encargo comercial ni una instalación de producción.

No incluye pasarela bancaria real, webhook de pagos real, logística física automatizada, facturación fiscal ni despliegue público endurecido. La recepción de mercadería sigue siendo una decisión del negocio. El proveedor automático opera dentro del simulador local, no en una plataforma externa.

El acceso HTTP Basic está previsto para la prueba local; Base64 no es cifrado. Una instalación pública requiere revisar transporte, autenticación, configuración y operación. La restauración de respaldos exige detener el servidor.

El motor anterior de reglas individuales permanece disponible en API/consola. La demostración final mantiene una regla general fija para evitar complejidad innecesaria. Administración completa de cuentas, compras de emergencia y algunas herramientas de respaldo siguen principalmente en consola/API.
