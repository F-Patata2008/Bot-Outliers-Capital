# Uso del bot CIPC

Archivos preparados:

- `cipc.py`: SDK oficial copiado desde `player_kit.zip`.
- `example_bot.py`: template oficial.
- `zanni_quant_bot.py`: bot listo para correr/subir.

## Correr local

Usa el Python del entorno virtual:

```bash
.venv/bin/python zanni_quant_bot.py
```

Con credenciales manuales:

```bash
CIPC_USER="tu_usuario" CIPC_PASS="tu_password" .venv/bin/python zanni_quant_bot.py
```

Parametros utiles:

```bash
CIPC_MIN_EDGE=50 CIPC_ORDER_QTY=3 CIPC_MAX_POSITION=30 .venv/bin/python zanni_quant_bot.py
```

Si quieres forzar un valor justo propio:

```bash
CIPC_FAIR_VALUE=12000 .venv/bin/python zanni_quant_bot.py
```

## Subir al challenge

Sube `zanni_quant_bot.py` en la tarjeta `Ronda quant · API`. El archivo conserva
las lecturas `os.environ.get` que el README exige para que el staff inyecte host,
puerto, usuario y clave.
