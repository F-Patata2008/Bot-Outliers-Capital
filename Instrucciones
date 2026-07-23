# CIPC Trading Challenge — Player Kit

Todo lo que necesitas para conectarte al mercado y tradear por código.

**Entrega para la ronda quant**: sube tu `.py` en la tarjeta "🔌 Ronda quant · API"
de la pestaña Trading (re-subir reemplaza tu entrega). El staff correrá tu bot en
una instancia aislada — no borres las líneas `os.environ.get` del template: por
ahí se inyectan el host y las credenciales de tu instancia.

## Setup (1 minuto)

```bash
pip install requests websocket-client
```

Copia `cipc.py` y `example_bot.py` a tu carpeta, pon tus credenciales en
`example_bot.py` y córrelo. Ya estás conectado.

## Las dos conexiones

Hereda de las clases del SDK y sobreescribe los métodos `on_*` que te interesen:

```python
from cipc import MarketDataConnection, TradingConnection

class MyMarketData(MarketDataConnection):
    def on_news(self, news):
        print("NOTICIA:", news["headline"])

class MyTrading(TradingConnection):
    def on_fill(self, report):
        print("fill:", report["qty"], "@", report["price"])

md = MyMarketData(host, port)               # market data pública
trading = MyTrading(host, port)             # tus órdenes y tu cuenta

trading.login("usuario", "password")
trading.connect()                           # execution reports en tiempo real
md.connect()
md.wait_ready()
```

> ⚠️ **Cancel-on-disconnect**: si tu bot pierde la conexión privada
> (`trading.connect()`) por más de ~5 segundos, el exchange **cancela todas tus
> órdenes abiertas** automáticamente (recibirás los reports con reason
> `disconnect` al reconectar... si llegas a verlos). Mantén tu proceso vivo.

## Market data

El estado se actualiza solo en los atributos de `md`:

| Qué | Cómo |
|---|---|
| Libro de órdenes | `md.book` → `{"bids": [[precio, qty], ...], "asks": [...]}` |
| Mejor bid / offer / mid | `md.best_bid()`, `md.best_ask()`, `md.mid()` |
| Último precio | `md.last_price` |
| Noticias | `md.news` (la más reciente primero) |
| Últimos trades | `md.trades` |
| ¿Mercado abierto? | `md.market_open()` |

O reacciona a eventos sobreescribiendo: `on_book`, `on_trade`, `on_news`
(cada uno recibe el dict del evento).

Nota sobre el libro: `on_book` siempre entrega un **snapshot completo** del top 10
(nunca deltas) — cada mensaje reemplaza al anterior, no necesitas mantener estado.
También se llama al conectar (y reconectar) con el libro inicial.

⏱ **La market data pública se difunde en pulsos de 1 segundo** (como la bolsa
chilena): trades y libro llegan agrupados, máximo una vez por segundo. Tus
**execution reports privados sí son inmediatos** — te enteras de tus fills antes
de que el resto del mercado vea el trade. Reaccionar en menos de 1s a data
pública no tiene sentido; diseña tu estrategia en esa escala de tiempo.

## Órdenes

Todas las órdenes son **límite DAY** (viven hasta ejecutarse, cancelarse o la liquidación).

```python
r = trading.new_order(side="buy", price=1000, qty=5)   # place
order_id = r["order"]["id"]

trading.replace_order(order_id, price=1001)            # replace
trading.cancel_order(order_id)                         # cancel
trading.cancel_all()
trading.account()    # {'cash', 'position', 'pnl', 'equity', 'open_orders', ...}
```

Si el exchange rechaza la orden, el método lanza `CipcError` con el motivo.

**Reglas de prioridad del replace** (importantes para tu estrategia):
- Bajar `qty` al mismo precio → **conservas tu lugar en la cola** (mismo id).
- Cambiar `price` o subir `qty` → cancel-replace: **vas al final de la cola** del
  nuevo nivel y la orden **cambia de id** (el nuevo viene en la respuesta).

## Execution reports

Después de `trading.connect()` recibes tus eventos (solo los tuyos) en los métodos
que sobreescribas en tu subclase:

```python
class MyTrading(TradingConnection):
    def on_fill(self, report):       # {'order_id', 'side', 'price', 'qty', 'remaining', 'order_status'}
        ...
    def on_cancelled(self, report):  # {'order_id', 'reason': 'user' | 'replaced' | 'settle' | 'disconnect'}
        ...
    def on_settled(self, report):    # {'price', 'pnl'}  ← fin de la ronda
        ...
    def on_pnl(self, report):        # {'pnl', 'realized', 'unrealized', 'position', 'equity'} — cada ~2s
        ...
    def on_busted(self, report):     # tu equity llegó a 0: posiciones cerradas, no puedes seguir
        ...
    def on_execution_report(self, report):  # genérico: fills/cancels/settle (no incluye pnl)
        ...
```

## Límites del exchange

- Posición máxima: **±100**
- Cantidad máxima por orden: **50** · máximo **25 órdenes abiertas**
- Banda de precios: **±20%** del último precio
- Rate limit: **4 operaciones/segundo** (burst 8) — superarlo lanza `CipcError`

## Cómo se gana

Cada equipo arranca con la misma plata (la cuenta es compartida por el equipo).
Tu **PnL = realizado + no realizado**:
el realizado es lo que aseguraste cerrando posiciones; el no realizado marca tu
posición abierta contra el último precio. Al cierre, el mercado se liquida a un
valor fundamental oculto que deriva lentamente. Si el staff publica una **noticia**,
suele mover ese valor — reaccionar rápido es señal.

> ⚠️ **Regla de quiebra**: si tu equity (plata inicial + PnL total) llega a 0,
> el exchange cierra tus posiciones automáticamente y no puedes seguir enviando
> órdenes por el resto de la ronda. Administra tu riesgo.
