# Domain and persistence exception types used across application modules.


class ProductoDuplicadoError(Exception):
    pass


class ProductoNoEncontradoError(Exception):
    pass


class ErrorPersistencia(Exception):
    pass
