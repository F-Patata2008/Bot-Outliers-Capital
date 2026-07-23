# Notas de papers aplicadas al bot CIPC

Estas notas resumen los cambios de `zanni_quant_bot.py` que vienen de literatura
de market making y microestructura. Los parametros son `CIPC_*` para poder
ajustarlos sin editar codigo durante la ronda.

## Market making con inventario

Avellaneda y Stoikov modelan al market maker como un agente que cotiza alrededor
de un precio de reserva que baja cuando esta largo y sube cuando esta corto. En
el bot esto queda en:

- `CIPC_INVENTORY_SKEW`: mueve ambos quotes contra la posicion.
- `CIPC_POSITION_EDGE_STEP`: exige mas edge para aumentar inventario y menos edge
  para descargarlo.
- `CIPC_VOL_EDGE_MULT`: abre el spread cuando sube la volatilidad reciente.

## Informacion del libro

Los papers de OFI, queue imbalance y MLOFI muestran que el libro tiene senal de
corto plazo, no solo el ultimo trade. En el bot esto queda en:

- `microprice()`: mueve el valor justo hacia el lado con mayor presion en top of
  book.
- `CIPC_BOOK_DEPTH`: niveles del libro usados para imbalance.
- `CIPC_IMBALANCE_WEIGHT`: peso del imbalance multi-nivel en el valor justo.
- `CIPC_FLOW_WEIGHT`: peso del flujo de trades agresores.

## Costos de transaccion y prioridad

Reemplazar precio pierde prioridad en la cola; sobre-operar tambien aumenta
exposicion a seleccion adversa. En el bot esto queda en:

- `CIPC_MIN_REPRICE`: no reemplaza por diferencias pequenas de precio.
- `CIPC_STALE_EDGE_RATIO`: cancela ordenes cuyo edge quedo demasiado malo.
- `MAX_OPEN_ORDERS`: mantiene limite operativo bajo el maximo del exchange.

## Defaults sugeridos

Perfil conservador:

```bash
CIPC_MIN_EDGE=45 CIPC_ORDER_QTY=3 CIPC_MAX_POSITION=30 .venv/bin/python zanni_quant_bot.py
```

Perfil mas agresivo:

```bash
CIPC_MIN_EDGE=30 CIPC_ORDER_QTY=5 CIPC_MAX_POSITION=60 CIPC_TAKE_PROFIT=70 .venv/bin/python zanni_quant_bot.py
```

