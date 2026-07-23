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

Panel local de riesgo:

```bash
.venv/bin/python risk_control_server.py
```

Abre `http://127.0.0.1:8765`. `Pausar bot` cancela ordenes abiertas, mantiene
la conexion viva y evita ordenes nuevas; `Reanudar` vuelve a operar en el
siguiente ciclo; `Detener bot` cancela ordenes y apaga el proceso del bot.

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

Tambien puedes pausar sin abrir el panel editando `risk_config.json`:

```json
{
  "PAUSE_TRADING": true,
  "STOP_BOT": false
}
```

## Subir al challenge

Sube `zanni_quant_bot.py` en la tarjeta `Ronda quant · API`. El archivo conserva
las lecturas `os.environ.get` que el README exige para que el staff inyecte host,
puerto, usuario y clave.
