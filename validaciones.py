# Interactive input validation for the legacy console CRUD.


def solicitar_id():
    id_producto = pedir_numero("Ingrese ID de producto: ")
    return id_producto


def solicitar_nombre():
    nombre = input("Ingrese el nombre del producto: ").lower().strip()
    return nombre


def pedir_opcion(mensaje, opciones_validas):
    opcion_de_usuario = input(mensaje).lower().strip()

    while opcion_de_usuario not in opciones_validas:
        print("Elegí una de estas opciones: " + ", ".join(opciones_validas))
        opcion_de_usuario = input(mensaje).lower().strip()

    return opcion_de_usuario


def pedir_numero(mensaje):
    while True:
        try:
            num = int(input(mensaje))
            break
        except ValueError:
            print("Ingresá un número entero, sin letras ni decimales.")

    return num
