# Guia para que una IA se conecte al CIPC Trading Challenge

Esta guia esta pensada para un agente de IA o asistente de codigo que necesita
conectarse a `https://outliers.progcomp.cl/`, consultar datos, operar con el
SDK local y dejar trazabilidad. No escribas credenciales reales en archivos,
mensajes, commits ni logs compartidos.

## Resumen rapido

- Host por defecto: `outliers.progcomp.cl`
- Puerto por defecto: `443`
- API base: `https://outliers.progcomp.cl`
- Market data publico: WebSocket `wss://outliers.progcomp.cl:443/ws/market`
- Canal privado: WebSocket `wss://outliers.progcomp.cl:443/ws/private?token=...`
- SDK local principal: `cipc.py`
- Bot actual: `zanni_quant_bot.py`
- Supervisor: `run_bot_forever.py`
- Panel local de riesgo: `risk_control_server.py`
- Estado de cuenta: `account_status.py`
- Cancelacion/cierre de emergencia: `emergency_sell.py`
- Historial local del bot: `trade_history.jsonl`
- Analisis de historial local: `analyze_trade_history.py`

## Reglas de seguridad para otra IA

1. Nunca hardcodees `CIPC_USER` ni `CIPC_PASS`.
2. Antes de operar, consulta `account()` y confirma `position`, `open_orders`,
   `equity`, `pnl`, `busted` y `mark`.
3. Para detener riesgo, primero cancela ordenes abiertas con `cancel_all()`.
4. Si el bot esta vivo y quieres detenerlo, usa pausa/detencion controlada o
   `systemctl --user stop cipc-zanni-bot.service`; despues vuelve a consultar
   la cuenta.
5. Despues de cancelar, verifica otra vez `open_orders`: una orden puede haber
   sido recreada por un proceso aun vivo en el ultimo ciclo.
6. No asumas que estar conectado al sitio significa que el bot esta operando.
   Son estados distintos: sitio/API, WebSocket de datos, WebSocket privado,
   proceso del bot y ordenes abiertas.
7. Si hay `position > 0`, cancelar ordenes no cierra la posicion. Hay que vender
   o esperar liquidacion segun el objetivo.
8. Si hay `position < 0`, cancelar ordenes no cierra el short. Hay que comprar
   para cubrir.

## Variables de entorno

El challenge y los scripts usan estas variables. La IA debe pedirlas al entorno,
no escribir valores reales en codigo.

```bash
CIPC_HOST=outliers.progcomp.cl
CIPC_PORT=443
CIPC_USER=tu_usuario
CIPC_PASS=tu_password
```

Parametros del bot:

```bash
CIPC_ORDER_QTY=1
CIPC_MIN_EDGE=90
CIPC_TAKE_PROFIT=140
CIPC_MAX_POSITION=1
CIPC_MAX_OPEN_ORDERS=1
CIPC_BOOK_DEPTH=3
CIPC_TREND_WEIGHT=8.0
CIPC_IMBALANCE_WEIGHT=0.35
CIPC_FLOW_WEIGHT=0.20
CIPC_VOL_EDGE_MULT=1.2
CIPC_INVENTORY_SKEW=0.9
CIPC_TORCH_WEIGHT=0.45
CIPC_TORCH_MAX_ADJUST=45
CIPC_POSITION_EDGE_STEP=1.5
CIPC_MIN_REPRICE=80
CIPC_STALE_EDGE_RATIO=0.65
CIPC_MIN_PROFIT=18
CIPC_EXIT_TAKE_PROFIT=35
CIPC_STOP_LOSS=260
CIPC_MIN_EQUITY_STOP=89500
CIPC_MAX_LOSS_STOP=11000
CIPC_MAX_SPREAD_ENTER=90
CIPC_MAX_VOLATILITY_ENTER=120
CIPC_ALLOW_SHORT=0
CIPC_ALLOW_BUY_TAKE=0
CIPC_FAIR_VALUE=
CIPC_RISK_CONFIG=risk_config.json
CIPC_HISTORY_PATH=trade_history.jsonl
```

## Instalacion minima

El repo ya incluye `.venv` en esta maquina. Si se prepara desde cero:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Para usar solo el SDK oficial hacen falta:

```bash
.venv/bin/python -m pip install requests websocket-client
```

## Conexion con el SDK

Usa `cipc.py`. Tiene dos clases:

- `MarketDataConnection`: datos publicos de mercado por WebSocket.
- `TradingConnection`: login, ordenes, cuenta y execution reports privados.

Ejemplo minimo de conexion:

```python
import os
import time

from cipc import MarketDataConnection, TradingConnection

HOST = os.environ.get("CIPC_HOST", "outliers.progcomp.cl")
PORT = int(os.environ.get("CIPC_PORT", "443"))
USER = os.environ["CIPC_USER"]
PASSWORD = os.environ["CIPC_PASS"]


class MD(MarketDataConnection):
    def on_book(self, book):
        print("book", book["bids"][:1], book["asks"][:1])

    def on_trade(self, trade):
        print("market trade", trade)

    def on_news(self, news):
        print("news", news)


class TR(TradingConnection):
    def on_execution_report(self, report):
        print("execution", report)

    def on_fill(self, report):
        print("fill", report)

    def on_cancelled(self, report):
        print("cancelled", report)

    def on_pnl(self, report):
        print("pnl", report)


md = MD(HOST, PORT)
trading = TR(HOST, PORT)

trading.login(USER, PASSWORD)
trading.connect()
md.connect()
md.wait_ready()

while True:
    account = trading.account()
    print("bid", md.best_bid(), "ask", md.best_ask(), "pos", account["position"])
    time.sleep(1)
```

## Endpoints HTTP conocidos

El SDK encapsula estos endpoints:

- `POST /api/login`: devuelve token y datos de usuario.
- `GET /api/c2/account`: cash, posicion, PnL, equity y ordenes abiertas.
- `GET /api/c2/status`: estado de la ronda trading.
- `GET /api/c2/book?depth=N`: libro de ordenes.
- `POST /api/c2/orders`: crea orden limite.
- `DELETE /api/c2/orders/{id}`: cancela una orden.
- `PATCH /api/c2/orders/{id}`: replace/cambio de precio o cantidad.
- `DELETE /api/c2/orders`: cancela todas las ordenes abiertas.
- `GET /api/c2/leaderboard`: tabla publica de trading.
- `GET /api/c2/kit.zip`: SDK oficial descargable.
- `GET /api/c2/kit/README.md`: instrucciones oficiales.

Tambien existen endpoints del frontend:

- `GET /api/me`
- `GET /api/teams`
- `POST /api/teams`
- `POST /api/teams/join`
- `GET /api/c1/info`
- `GET /api/c1/leaderboard`
- `POST /api/c1/submissions`
- `POST /api/c1/submit`

El frontend muestra "Mis mensajes" con fills y cancelaciones a partir del canal
privado; en el SDK documentado no hay un endpoint REST historico de fills. Para
historial confiable, mantener conectado `trading.connect()` y registrar los
execution reports localmente.

## Estructura de datos importante

`trading.account()` devuelve un diccionario con campos como:

```python
{
    "cash": 100000.0,
    "position": 0,
    "avg_price": 0.0,
    "equity": 100000.0,
    "pnl": 0.0,
    "realized": 0.0,
    "unrealized": 0.0,
    "busted": False,
    "pos_limit": 100,
    "initial_cash": 100000.0,
    "mark": 10100,
    "open_orders": []
}
```

Orden abierta:

```python
{
    "id": 123,
    "side": "buy",
    "price": 10000,
    "qty": 1,
    "filled": 0,
    "remaining": 1,
    "status": "open",
    "ts": 1784843552.0
}
```

Execution reports privados:

```python
{"type": "fill", "order_id": 1, "side": "buy", "price": 10000, "qty": 1, "remaining": 0, "order_status": "filled"}
{"type": "cancelled", "order_id": 1, "side": "buy", "price": 10000, "remaining": 1, "reason": "user"}
{"type": "pnl", "pnl": 0.0, "realized": 0.0, "unrealized": 0.0, "position": 0, "equity": 100000.0}
{"type": "settled", "price": 10000, "pnl": 0.0}
{"type": "busted", "equity": 0.0, "realized": -100000.0}
```

Razones de cancelacion conocidas:

- `user`: cancelada por usuario/bot.
- `replaced`: cancel-replace.
- `settle`: liquidacion.
- `disconnect`: desconexion privada.
- `bust`: cuenta quebrada.

## Reglas operativas del exchange

- Todas las ordenes son limite DAY.
- Si se pierde la conexion privada `trading.connect()` por mas de unos segundos,
  el exchange puede cancelar todas las ordenes abiertas.
- Los execution reports privados llegan antes que el trade publico.
- El market data publico llega agrupado, aproximadamente una vez por segundo.
- Posicion maxima documentada: `±100`.
- Cantidad maxima por orden documentada: `50`.
- Maximo documentado de ordenes abiertas: `25`.
- Banda de precio documentada: `±20%` del ultimo precio.
- Rate limit documentado: `4` operaciones por segundo con burst `8`.
- Cambiar precio o subir cantidad hace cancel-replace y pierde prioridad.
- Bajar cantidad al mismo precio conserva prioridad.

## Comandos de diagnostico

Ver si el sitio responde:

```bash
curl -I https://outliers.progcomp.cl/
```

Ver estado de cuenta y libro:

```bash
env PYTHONUNBUFFERED=1 CIPC_USER="$CIPC_USER" CIPC_PASS="$CIPC_PASS" \
  .venv/bin/python account_status.py
```

Ver procesos vivos del bot:

```bash
pgrep -af '[z]anni_quant_bot|[r]un_bot_forever'
```

Ver servicio del bot si fue lanzado por systemd:

```bash
systemctl --user status cipc-zanni-bot.service --no-pager
```

Ver panel de riesgo si fue lanzado por systemd:

```bash
systemctl --user status cipc-risk-panel.service --no-pager
```

Ver logs recientes del bot:

```bash
journalctl --user -u cipc-zanni-bot.service -n 120 --no-pager
```

Analizar historial local:

```bash
.venv/bin/python analyze_trade_history.py
```

## Arrancar componentes

Bot directo:

```bash
env PYTHONUNBUFFERED=1 CIPC_USER="$CIPC_USER" CIPC_PASS="$CIPC_PASS" \
  .venv/bin/python zanni_quant_bot.py
```

Bot con supervisor simple:

```bash
env PYTHONUNBUFFERED=1 CIPC_USER="$CIPC_USER" CIPC_PASS="$CIPC_PASS" \
  .venv/bin/python run_bot_forever.py
```

Panel local:

```bash
env PYTHONUNBUFFERED=1 RISK_SERVER_HOST=127.0.0.1 RISK_SERVER_PORT=8765 \
  CIPC_RISK_CONFIG=risk_config.json \
  .venv/bin/python risk_control_server.py
```

Abrir panel local:

```text
http://127.0.0.1:8765/
```

El panel escribe `risk_config.json`. El bot lee ese archivo en caliente en cada
ciclo. Acciones del panel:

- `Pausar bot`: cancela ordenes abiertas, mantiene conexion viva y no crea nuevas
  ordenes.
- `Reanudar`: vuelve a permitir trading.
- `Detener bot`: cancela ordenes y hace que el bot termine en el siguiente ciclo.

## Detener y dejar cuenta limpia

Parar servicio:

```bash
systemctl --user stop cipc-zanni-bot.service
```

Cancelar ordenes y cerrar posicion larga si existe:

```bash
env PYTHONUNBUFFERED=1 CIPC_USER="$CIPC_USER" CIPC_PASS="$CIPC_PASS" \
  .venv/bin/python emergency_sell.py
```

Despues de cualquier stop:

```bash
env PYTHONUNBUFFERED=1 CIPC_USER="$CIPC_USER" CIPC_PASS="$CIPC_PASS" \
  .venv/bin/python account_status.py
```

La condicion deseada para "limpio" es:

```text
position = 0
open_orders = []
```

## Historial de compra y venta

El bot guarda eventos en `trade_history.jsonl`:

- `snapshot`: estado periodico de mercado/cuenta.
- `pnl`: reportes privados de PnL.
- `execution`: cualquier execution report privado.
- `fill`: compra/venta ejecutada real.
- `cancelled`: cancelacion real.
- `settled`: liquidacion final.
- `busted`: cuenta quebrada.

Para ver fills y cancelaciones:

```bash
rg -n '"event": "fill"|"type": "fill"|"event": "cancelled"|"event": "execution"' trade_history.jsonl
```

Para resumir round trips:

```bash
.venv/bin/python analyze_trade_history.py
```

Limitacion importante: si el bot o la IA no estaban conectados al WebSocket
privado cuando ocurrio un evento, puede faltar en el historial local. La cuenta
actual (`account()`) sigue siendo la fuente para posicion, equity y ordenes
abiertas.

## Como opera `zanni_quant_bot.py`

Flujo principal:

1. Lee `CIPC_HOST`, `CIPC_PORT`, `CIPC_USER`, `CIPC_PASS`.
2. Crea `MyMarketData` y `MyTrading`.
3. Hace `trading.login()`.
4. Abre WebSocket privado con `trading.connect()`.
5. Abre WebSocket publico con `md.connect()`.
6. Espera snapshot inicial con `md.wait_ready()`.
7. Cada segundo, si `md.market_open()`, llama `strategy(md, trading)`.

Senales usadas:

- EMA de fair value local.
- Microprice del libro.
- Tendencia.
- Volatilidad.
- Imbalance de libro.
- Flujo de trades.
- Sesgo por noticias.
- Ajuste opcional online con PyTorch si `torch` esta disponible.

Controles de riesgo:

- `MAX_POSITION`
- `MAX_OPEN_ORDERS`
- `STOP_LOSS`
- `MIN_EQUITY_STOP`
- `MAX_LOSS_STOP`
- `MAX_SPREAD_ENTER`
- `MAX_VOLATILITY_ENTER`
- `PAUSE_TRADING`
- `STOP_BOT`
- `ALLOW_SHORT`
- `ALLOW_BUY_TAKE`

El bot intenta:

- Comprar con edge suficiente si esta flat o bajo capacidad.
- Si tiene posicion larga, cancela compras y prioriza salida.
- Vender con ganancia minima si el bid permite realizar.
- Colocar una venta target si aun no se cumple salida agresiva.
- Aplicar stop-loss si el bid cae demasiado contra `avg_price`.
- Cancelar duplicados y ordenes obsoletas.

## Checklist para una IA antes de operar

1. Confirmar que el host responde.
2. Confirmar que existen credenciales por entorno.
3. Ejecutar `account_status.py`.
4. Si hay ordenes abiertas no deseadas, `cancel_all()` o `emergency_sell.py`.
5. Confirmar que no hay otro proceso `zanni_quant_bot.py` vivo.
6. Definir parametros de riesgo.
7. Arrancar bot o conectar script propio.
8. Registrar fills en `trade_history.jsonl` o archivo equivalente.
9. Durante la sesion, monitorear `pnl`, `equity`, `position`, `open_orders`.
10. Al terminar, detener proceso, cancelar ordenes, revisar cuenta dos veces.

## Estado observado en esta maquina al crear esta guia

Ultima verificacion local conocida:

```text
API: https://outliers.progcomp.cl/ respondia HTTP 200
Bot systemd: cipc-zanni-bot.service no estaba activo
Panel systemd: cipc-risk-panel.service no estaba activo
Cuenta: position=0, open_orders=[], realized=-1978.0, equity=98022.0
```

Este bloque es solo una referencia historica. Una IA debe volver a ejecutar las
consultas porque el estado del mercado y de la cuenta cambia.
