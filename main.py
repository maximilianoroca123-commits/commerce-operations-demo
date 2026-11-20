# Entry point of the original console CRUD, separate from the web API.


from menu import menu
from persistencia import conectar_db, crear_tablas

conexion = conectar_db()
crear_tablas(conexion)

menu(conexion)
