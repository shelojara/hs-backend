import random

JOKES_ES = [
    "¿Por qué los programadores confunden Halloween con Navidad? Porque oct 31 == dec 25.",
    "Un SQL entra a un bar, se acerca a dos mesas y pregunta: ¿puedo unirme?",
    "Hay 10 tipos de personas: las que entienden binario y las que no.",
    "Mi código no tiene bugs, solo desarrolla características no documentadas.",
    "Git commit -m 'arreglo' — el clásico.",
]


def random_joke() -> str:
    return random.choice(JOKES_ES)
